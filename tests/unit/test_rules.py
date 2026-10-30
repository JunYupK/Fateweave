import hashlib
import json
import re
from datetime import time

import pytest

from fateweave.domain import rules
from fateweave.domain.calendar import normalize_birth
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import RULE_ORDER, build_individual_evidence, evidence_digest
from fateweave.models.facts import ChartSnapshot, Evidence
from fateweave.models.inputs import BirthProfileInput

ELEMENTS = set("木火土金水")
ID_RE = re.compile(r"^E-(?P<subject>[A-Za-z0-9]+)-(?P<rule>[A-Z_]+)-(?P<digest>[0-9a-f]{8})$")
BOUNDARY = "depends on primary pillar set; alternatives exist (BOUNDARY_REVIEW_REQUIRED)"
PRIMARY_ONLY = "computed for primary pillar set only"


def chart(birth_time: time | None) -> ChartSnapshot:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date="1990-01-01",
            calendar="solar",
            birth_time=birth_time,
            gender_for_daewoon="male",
        )
    )
    return compute_chart(birth, sewoon_start_year=2026, sewoon_years=3)


@pytest.fixture(scope="module")
def known() -> ChartSnapshot:
    # 己巳 丙子 丙寅 丙申, CONFIRMED (16:30 KST at Seoul = 申時 local mean time).
    snap = chart(time(16, 30))
    assert (snap.year_pillar, snap.month_pillar, snap.day_pillar, snap.hour_pillar) == (
        "己巳",
        "丙子",
        "丙寅",
        "丙申",
    )
    assert snap.certainty == "CONFIRMED"
    return snap


@pytest.fixture(scope="module")
def unknown() -> ChartSnapshot:
    # 己巳 丙子 丙寅 (hour unknown), PARTIAL: one alternative with day pillar 乙丑.
    snap = chart(None)
    assert snap.hour_pillar is None
    assert snap.certainty == "PARTIAL"
    assert [(a.year_pillar, a.month_pillar, a.day_pillar) for a in snap.alternatives] == [
        ("己巳", "丙子", "乙丑")
    ]
    return snap


def canonical(operands: dict) -> str:
    return json.dumps(operands, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def by_rule(evidence: list[Evidence], code: str) -> list[Evidence]:
    return [e for e in evidence if e.rule_code == code]


def test_fact_reference_is_stable(known):
    first = build_individual_evidence(known, "A")
    # Same snapshot after a storage round trip (Task 7 recomputes from stored snapshots).
    restored = ChartSnapshot.model_validate_json(known.model_dump_json())
    second = build_individual_evidence(restored, "A")
    assert first == second
    assert evidence_digest(first) == evidence_digest(second)

    ids = [e.id for e in first]
    assert len(ids) == len(set(ids))
    for e in first:
        m = ID_RE.match(e.id)
        assert m, e.id
        assert m["subject"] == "A"
        assert m["rule"] == e.rule_code
        assert m["digest"] == hashlib.sha256(canonical(e.operands).encode()).hexdigest()[:8]

    # The subject key only changes the prefix.
    other = build_individual_evidence(known, "B")
    assert [e.id.replace("E-B-", "E-A-", 1) for e in other] == ids

    # Concrete facts are pinned to their exact references.
    day = next(e for e in by_rule(first, "PILLARS") if e.operands["position"] == "day")
    assert day.operands == {"position": "day", "pillar": "丙寅"}
    expected_digest = hashlib.sha256(canonical(day.operands).encode()).hexdigest()[:8]
    assert day.id == f"E-A-PILLARS-{expected_digest}"
    chung = [e for e in by_rule(first, "BRANCH_RELATIONS") if e.operands["relation"] == "沖"]
    assert [e.operands for e in chung] == [
        {
            "relation": "沖",
            "name": "寅申沖",
            "positions": ["day_branch", "hour_branch"],
            "branches": ["寅", "申"],
        }
    ]
    assert "일지 인" in chung[0].text_ko and "시지 신" in chung[0].text_ko
    (palace,) = by_rule(first, "SPOUSE_PALACE")
    assert palace.operands == {"position": "day_branch", "branch": "寅", "ten_god": "偏印"}

    for bad in ["", "A-B", "가", "A B", "self!"]:
        with pytest.raises(ValueError):
            build_individual_evidence(known, bad)


def _mentions_hour(e: Evidence) -> bool:
    return "hour" in canonical(e.operands)


def test_missing_hour_excludes_hour_evidence(known, unknown):
    with_hour = build_individual_evidence(known, "self")
    assert any(_mentions_hour(e) for e in with_hour)  # the check below is not vacuous
    hour_relations = {
        e.operands["name"] for e in by_rule(with_hour, "BRANCH_RELATIONS") if _mentions_hour(e)
    }
    assert hour_relations == {"巳申合", "巳申破", "寅申沖", "寅巳申三刑"}

    evidence = build_individual_evidence(unknown, "self")
    assert not any(_mentions_hour(e) for e in evidence)
    assert not any("시주" in e.text_ko and e.kind != "interpretation_cue" for e in evidence)
    assert {e.operands["position"] for e in by_rule(evidence, "PILLARS")} == {
        "year",
        "month",
        "day",
    }
    assert {e.operands["position"] for e in by_rule(evidence, "TEN_GODS")} == {
        "year_stem",
        "month_stem",
        "year_branch",
        "month_branch",
        "day_branch",
    }
    # Only the year/day branch 害 survives without the hour branch.
    assert [e.operands["name"] for e in by_rule(evidence, "BRANCH_RELATIONS")] == ["寅巳害"]
    elements, with_hidden = sorted(
        by_rule(evidence, "ELEMENTS"), key=lambda e: e.operands["basis"], reverse=True
    )
    assert with_hidden.operands["basis"] == "stems_and_all_hidden_stems"
    assert elements.operands["positions"] == ["year", "month", "day"]
    assert sum(elements.operands["counts"].values()) == 6
    # 格局 needs the hour stem (月支 透干 check), so it is not determined.
    assert [e.kind for e in by_rule(evidence, "GYEOKGUK")] == ["interpretation_cue"]

    # PARTIAL: the day pillar differs in an alternative, so day-dependent items say so;
    # year/month-only and sewoon items do not.
    flagged = {e.id for e in evidence if BOUNDARY in e.assumptions}
    for e in evidence:
        ops = canonical(e.operands)
        if e.rule_code == "PILLARS":
            assert (e.id in flagged) == (e.operands["position"] == "day"), e
        if e.rule_code in ("TEN_GODS", "SPOUSE_PALACE", "ELEMENTS"):
            assert e.id in flagged, e  # every ten god is measured against the day stem
        if e.rule_code == "BRANCH_RELATIONS":
            assert ("day_branch" in ops) == (e.id in flagged), e
        if e.rule_code == "SEWOON":
            assert e.id not in flagged
        if e.rule_code == "DAEWOON":
            assert PRIMARY_ONLY in e.assumptions
    assert by_rule(evidence, "DAEWOON")
    assert not any(BOUNDARY in e.assumptions or PRIMARY_ONLY in e.assumptions for e in with_hour)


def test_school_dependent_judgements_name_their_method(known, unknown):
    for snap in (known, unknown):
        evidence = build_individual_evidence(snap, "A")
        (strength,) = by_rule(evidence, "STRENGTH")
        (yongsin,) = by_rule(evidence, "YONGSIN")
        assert strength.kind == yongsin.kind == "rule_derived"  # never "computed"
        assert any("method" in a for a in strength.assumptions)
        assert any("억부 candidates only" in a for a in yongsin.assumptions)
        assert set(yongsin.operands["elements"]) <= ELEMENTS
        for e in by_rule(evidence, "JOHU"):
            assert e.kind == "rule_derived" and e.assumptions
        # No other rule asserts a 用神 / 喜神 / 忌神 result.
        for e in evidence:
            assert not re.search("用神|喜神|忌神", canonical(e.operands)), e
    # 1990-01-01 丙寅 일주 in 子月: 中和 either way (unknown hour rescales the known 8 points).
    levels = [by_rule(build_individual_evidence(s, "A"), "STRENGTH")[0].operands for s in
              (known, unknown)]
    assert [x["level"] for x in levels] == ["中和", "中和"]
    assert levels[1]["birth_time_known"] is False
    (johu,) = by_rule(build_individual_evidence(known, "A"), "JOHU")
    assert johu.operands["elements"] == ["火"]  # winter month: 火


def test_text_ko_is_hangul(known, unknown):
    for snap in (known, unknown):
        for e in build_individual_evidence(snap, "A"):
            assert not re.search(r"[\u4e00-\u9fff]", e.text_ko), e.text_ko


def test_evidence_sources_are_identified(known, unknown):
    library = f"korean-saju=={known.library_version}"
    assert library == "korean-saju==0.3.0"
    for snap in (known, unknown):
        evidence = build_individual_evidence(snap, "A")
        assert {e.rule_code for e in evidence} <= set(RULE_ORDER)
        for e in evidence:
            assert e.text_ko.strip()
            assert e.source_ref, e
            assert e.source_ref.startswith(("manse-v2#", "rules-v2#", library)), e
        for e in evidence:
            if e.rule_code in ("TEN_GODS", "DAEWOON", "SEWOON"):
                assert e.kind == "computed" and e.source_ref.startswith(library), e
            if e.rule_code == "PILLARS":
                assert e.kind == "computed" and e.source_ref == "manse-v2#PILLARS"
            if e.rule_code in ("SPOUSE_PALACE", "ELEMENTS", "BRANCH_RELATIONS"):
                assert e.kind == "rule_derived"
                assert e.source_ref == f"rules-v2#{e.rule_code}"
            if e.rule_code == "GYEOKGUK" and e.kind == "rule_derived":
                assert e.source_ref.startswith(library)
                assert e.assumptions  # the school-dependent criterion is stated
    # With the hour known the library 格局 is reported as a rule-derived result.
    (gyeok,) = by_rule(build_individual_evidence(known, "A"), "GYEOKGUK")
    assert gyeok.kind == "rule_derived"
    assert gyeok.operands["gyeokguk"].endswith("格")


def test_rule_order_does_not_change_digest(known, unknown, monkeypatch):
    for snap in (known, unknown):
        baseline = build_individual_evidence(snap, "A")
        # Output is sorted by rule order, then id.
        keys = [rules.sort_key(RULE_ORDER)(e) for e in baseline]
        assert keys == sorted(keys)
        assert evidence_digest(baseline) == evidence_digest(list(reversed(baseline)))

        monkeypatch.setattr(rules, "RULES", dict(reversed(list(rules.RULES.items()))))
        shuffled = build_individual_evidence(snap, "A")
        monkeypatch.undo()
        assert [e.id for e in shuffled] == [e.id for e in baseline]
        assert evidence_digest(shuffled) == evidence_digest(baseline)
    assert set(rules.RULES) == set(RULE_ORDER)
    assert len(RULE_ORDER) == 20
