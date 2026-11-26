"""rules-v6 general (종합 사주) evidence: distribution, palaces, kinship, aptitude, flows."""

from datetime import time

import pytest
from korean_saju import GyeokgukCalculator

from fateweave.domain import depth, rules
from fateweave.domain import tables as t
from fateweave.domain.calendar import normalize_birth
from fateweave.domain.general import (
    CATEGORY,
    GENERAL_NEW_RULES,
    GYEOKGUK_GROUP,
    aptitude,
    build_general_evidence,
    kinship,
    ten_god_distribution,
)
from fateweave.domain.glossary import has_hanja
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import build_individual_evidence
from fateweave.models.facts import ChartSnapshot, Evidence, PillarAlternative
from fateweave.models.inputs import BirthProfileInput


def chart(birth_date: str, birth_time: time | None, gender: str) -> ChartSnapshot:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date=birth_date,
            calendar="solar",
            birth_time=birth_time,
            gender_for_daewoon=gender,
        )
    )
    return compute_chart(birth, sewoon_start_year=2026, sewoon_years=3)


@pytest.fixture(scope="module")
def zi() -> ChartSnapshot:
    snap = chart("1990-03-12", time(10, 30), "male")  # 庚午 己卯 丙子 癸巳, synthetic
    assert (snap.year_pillar, snap.month_pillar, snap.day_pillar, snap.hour_pillar) == (
        "庚午",
        "己卯",
        "丙子",
        "癸巳",
    )
    return snap


def jiazi(base: ChartSnapshot, hour: bool = True) -> ChartSnapshot:
    """A pure 甲子 chart (only pillar-derived functions may read it)."""
    return base.model_copy(
        update={
            "year_pillar": "甲子",
            "month_pillar": "甲子",
            "day_pillar": "甲子",
            "hour_pillar": "甲子" if hour else None,
            "alternatives": [],
        }
    )


def by_rule(evidence: list[Evidence], rule: str) -> list[Evidence]:
    return [e for e in evidence if e.rule_code == rule]


def levels(d: dict) -> dict[str, str]:
    return {g: v["level"] for g, v in d["groups"].items()}


def test_individual_catalog_unchanged(zi):
    assert [e.id for e in build_individual_evidence(zi, "self")] == [
        e.id for e in rules.build_evidence(zi, "self", rules.RULES, rules.RULE_ORDER)
    ]


def test_distribution_known_hour(zi):
    d = ten_god_distribution(zi)
    assert {g: v["surface"] for g, v in d["groups"].items()} == {
        "比劫": 2,
        "食傷": 1,
        "財星": 1,
        "官星": 2,
        "印星": 1,
    }
    assert {g: v["hidden"] for g, v in d["groups"].items()} == pytest.approx(
        {"比劫": 0.3, "食傷": 0.9, "財星": 0.6, "官星": 0.3, "印星": 0.3}
    )
    assert levels(d) == {
        "比劫": "normal",
        "食傷": "weak",
        "財星": "weak",
        "官星": "normal",
        "印星": "weak",
    }
    assert d["groups"]["官星"]["ten_gods"] == {"正官": 2}
    assert d["dominant"] == ["比劫", "官星"] and d["missing"] == []
    assert d["known_positions"] == ["year", "month", "day", "hour"]


def test_missing_group_is_none_with_hour_and_unconfirmed_without(zi):
    d = ten_god_distribution(jiazi(zi))
    assert d["missing"] == ["食傷", "財星", "官星"] and d["groups"]["食傷"]["level"] == "none"
    assert d["groups"]["比劫"]["level"] == "strong" and d["groups"]["印星"]["level"] == "strong"
    d2 = ten_god_distribution(jiazi(zi, hour=False))
    assert d2["missing"] == [] and d2["groups"]["食傷"]["level"] == "unconfirmed"
    assert d2["known_positions"] == ["year", "month", "day"]


def test_unknown_hour_scales_thresholds():
    # 庚午 己卯 丙子 without hour: weights 比劫/官星/印星 1.15, 食傷 1.3, 財星 1.0;
    # thresholds x5/7 (weak < 1.071, normal < 2.143).
    d = ten_god_distribution(chart("1990-03-12", None, "male"))
    assert levels(d) == {
        "比劫": "normal",
        "食傷": "normal",
        "財星": "weak",
        "官星": "normal",
        "印星": "normal",
    }


# ---- Task 4: palaces and kinship ---------------------------------------------------------


def test_palaces_known_and_unknown_hour(zi):
    items = by_rule(build_general_evidence(zi), "PALACES")
    assert [e.operands["palace"] for e in items] == [
        "ancestry_youth",
        "parents_siblings_society",
        "self_spouse",
        "children_later_life",
    ]
    month = next(e for e in items if e.operands["position"] == "month")
    assert (month.operands["stem_ten_god"], month.operands["branch_ten_god"]) == ("傷官", "正印")
    day = next(e for e in items if e.operands["position"] == "day")
    assert day.operands["stem_ten_god"] is None
    no_hour = by_rule(build_general_evidence(chart("1990-03-12", None, "male")), "PALACES")
    assert no_hour[-1].operands == {
        "index": 3,
        "position": "hour",
        "palace": "children_later_life",
        "status": "unknown",
    }
    assert "태어난 시각" in no_hour[-1].text_ko


def test_kinship_found_none_unconfirmed(zi):
    k = {e["relative"]: e for e in kinship(jiazi(zi))}
    assert list(k) == ["mother", "father", "siblings", "spouse", "son", "daughter"]
    assert k["mother"]["status"] == "found" and k["mother"]["count"] == 4
    assert k["father"]["status"] == "none" and k["father"]["count"] == 0
    k2 = {e["relative"]: e for e in kinship(jiazi(zi, hour=False))}
    assert k2["father"]["status"] == "unconfirmed" and k2["son"]["status"] == "unconfirmed"


def test_kinship_hidden_hits_are_listed_not_counted(zi):
    k = {e["relative"]: e for e in kinship(jiazi(zi))}
    # 子's 餘氣 壬 is 偏印, not 正印: the mother count stays surface-only.
    assert all(f["position"].endswith("_branch") for f in k["mother"]["found"])
    as_female = zi.model_copy(update={"gender_for_daewoon": "female"})
    female = {e["relative"]: e for e in kinship(as_female)}
    assert female["spouse"]["ten_gods"] == ["正官", "偏官"]
    assert female["son"]["ten_gods"] == ["傷官"] and female["son"]["status"] == "found"


# ---- Task 5: aptitude --------------------------------------------------------------------


def test_aptitude_follows_gyeokguk_and_dominant(zi):
    a = aptitude(zi)
    expected = GyeokgukCalculator.determine(depth.library_saju(zi)).gyeokguk.hanja
    assert a["basis"] == "gyeokguk" and a["gyeokguk"] == expected
    assert a["groups"][0] == GYEOKGUK_GROUP[expected]
    assert 1 <= len(a["groups"]) <= 2 and a["categories"] == [CATEGORY[g] for g in a["groups"]]
    assert a["special_structure"] is None and a["alternative"] is None


def test_aptitude_follows_special_structure(monkeypatch, zi):
    accepted = [{"type": "從財格", "name_ko": "종재격", "verdict": "GENUINE", "score": 80}]
    monkeypatch.setattr(
        depth, "special_structures", lambda c: {"checked": 16, "accepted": accepted}
    )
    a = aptitude(zi)
    assert (a["basis"], a["groups"], a["special_structure"]) == (
        "special_structure",
        ["財星"],
        "從財格",
    )
    assert a["categories"] == ["business_management"]
    assert a["alternative"]["basis"] == "gyeokguk"


def test_aptitude_ignores_special_structure_without_group(monkeypatch, zi):
    accepted = [
        {"type": "甲己合化土格", "name_ko": "갑기합화토격", "verdict": "GENUINE", "score": 90}
    ]
    monkeypatch.setattr(
        depth, "special_structures", lambda c: {"checked": 16, "accepted": accepted}
    )
    assert aptitude(zi)["basis"] == "gyeokguk"


def test_aptitude_without_hour_uses_dominant():
    snap = chart("1990-03-12", None, "male")
    a = aptitude(snap)
    assert a["basis"] == "dominant" and a["gyeokguk"] is None
    assert a["groups"] == ten_god_distribution(snap)["dominant"][:2]


def test_aptitude_lists_work_sinsal(zi):
    present = {s["sinsal"] for s in depth.sinsal(zi)}
    assert set(aptitude(zi)["sinsal"]) == present & {"驛馬", "華蓋", "天乙貴人", "魁罡", "羊刃"}


# ---- Task 6: flows and the full catalog --------------------------------------------------


def test_luck_and_year_flow(zi):
    ev = build_general_evidence(zi)
    luck = by_rule(ev, "LUCK_FLOW")
    assert len(luck) == len(zi.daewoon.entries)
    first = luck[0].operands
    assert set(first) >= {
        "index",
        "start_age",
        "end_age",
        "pillar",
        "stem_ten_god",
        "branch_ten_god",
        "groups",
        "relations",
        "favorable_match",
    }
    assert first["end_age"] == first["start_age"] + 9
    assert [e.operands["index"] for e in luck] == list(range(len(luck)))
    favorable = set(depth.favorable_elements(zi))
    for e in luck:
        p = e.operands["pillar"]
        elements = {t.STEM_ELEMENT[p[0]], t.BRANCH_ELEMENT[p[1]]}
        assert e.operands["favorable_match"] == sorted(elements & favorable)
    years = by_rule(ev, "YEAR_FLOW")
    assert [e.operands["year"] for e in years] == [s.year for s in zi.sewoon]
    assert all("signal" not in e.operands and "rank" not in e.operands for e in years)
    assert all(e.operands["daewoon"] for e in years)


def test_general_catalog_has_no_marriage_timing(zi):
    codes = {e.rule_code for e in build_general_evidence(zi)}
    assert not codes & {"DAEWOON_FLOW", "YEAR_TIMING", "MONTH_TIMING", "LIFE_TIMING"}
    assert {"SPOUSE_PALACE", "SPOUSE_STAR", *GENERAL_NEW_RULES} <= codes


def test_partial_chart_flags_boundary(zi):  # Review Focus 4
    alt = PillarAlternative(
        year_pillar="辛未",
        month_pillar=zi.month_pillar,
        day_pillar=zi.day_pillar,
        hour_pillar=zi.hour_pillar,
        reasons=["SOLAR_TERM"],
        local_windows=[],
    )
    snap = zi.model_copy(update={"alternatives": [alt], "certainty": "PARTIAL"})
    ev = build_general_evidence(snap)
    for rule in ("TEN_GOD_DISTRIBUTION", "APTITUDE_CUES", "LUCK_FLOW", "KINSHIP"):
        assert rules.BOUNDARY_ASSUMPTION in by_rule(ev, rule)[0].assumptions, rule
    palaces = {e.operands["position"]: e for e in by_rule(ev, "PALACES")}
    assert rules.BOUNDARY_ASSUMPTION in palaces["year"].assumptions
    assert rules.BOUNDARY_ASSUMPTION not in palaces["day"].assumptions


def test_new_text_has_no_hanja(zi):
    for snap in (zi, chart("1990-03-12", None, "male")):
        for e in build_general_evidence(snap):
            if e.rule_code in GENERAL_NEW_RULES:
                assert not has_hanja(e.text_ko), e.text_ko


def test_luck_flow_marks_spouse_star(zi):
    stars = set(t.SPOUSE_STARS[zi.gender_for_daewoon])
    for e in by_rule(build_general_evidence(zi), "LUCK_FLOW"):
        ops = e.operands
        expected = ops["stem_ten_god"] in stars or ops["branch_ten_god"] in stars
        assert ops["spouse_star"] is expected
        assert ("배우자 기운" in e.text_ko) is expected
