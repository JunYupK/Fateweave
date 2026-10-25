import re
from datetime import time
from typing import Any

import pytest

from fateweave.domain.calendar import normalize_birth
from fateweave.domain.couple import COUPLE_RULE_ORDER, build_couple_evidence
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import BOUNDARY_ASSUMPTION, build_individual_evidence
from fateweave.models.facts import ChartSnapshot, Evidence
from fateweave.models.inputs import BirthProfileInput

ID_RE = re.compile(r"^E-(?P<subject>[A-Za-z0-9]+)-(?P<rule>[A-Z_]+)-(?P<digest>[0-9a-f]{8})$")
TIMING_ASSUMPTION = "traditional timing cue; not a prediction of marriage"


def chart(
    birth_date: str, birth_time: time | None, gender: str, sewoon_start_year: int = 2026
) -> ChartSnapshot:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date=birth_date,
            calendar="solar",
            birth_time=birth_time,
            gender_for_daewoon=gender,
        )
    )
    return compute_chart(birth, sewoon_start_year=sewoon_start_year, sewoon_years=3)


def pillars(snap: ChartSnapshot) -> tuple:
    return (snap.year_pillar, snap.month_pillar, snap.day_pillar, snap.hour_pillar)


@pytest.fixture(scope="module")
def zi() -> ChartSnapshot:
    # 庚午 己卯 丙子 癸巳, male: spouse star 庚/辛 (偏財/正財).
    snap = chart("1990-03-12", time(10, 30), "male")
    assert pillars(snap) == ("庚午", "己卯", "丙子", "癸巳")
    assert snap.certainty == "CONFIRMED"
    return snap


@pytest.fixture(scope="module")
def chou() -> ChartSnapshot:
    # 庚午 己卯 丁丑 乙巳, female: spouse star 壬/癸 (正官/偏官).
    snap = chart("1990-03-13", time(10, 30), "female")
    assert pillars(snap) == ("庚午", "己卯", "丁丑", "乙巳")
    assert snap.certainty == "CONFIRMED"
    return snap


@pytest.fixture(scope="module")
def jia() -> ChartSnapshot:
    # 庚午 己卯 甲戌 己巳, male: spouse star 戊/己 (偏財/正財).
    snap = chart("1990-03-10", time(10, 30), "male")
    assert pillars(snap) == ("庚午", "己卯", "甲戌", "己巳")
    return snap


@pytest.fixture(scope="module")
def gui() -> ChartSnapshot:
    # 庚午 己卯 癸未 丁巳, female: spouse star 戊/己 (正官/偏官).
    snap = chart("1990-03-19", time(10, 30), "female")
    assert pillars(snap) == ("庚午", "己卯", "癸未", "丁巳")
    return snap


def pair_items(evidence: list[Evidence]) -> list[Evidence]:
    return [e for e in evidence if e.rule_code in COUPLE_RULE_ORDER]


def by_rule(evidence: list[Evidence], code: str) -> list[Evidence]:
    return [e for e in evidence if e.rule_code == code]


def test_symmetrical_couple_relation_facts(zi, chou):
    ab = build_couple_evidence(zi, chou, 2026)
    ba = build_couple_evidence(chou, zi, 2026)

    # Individual catalogs are included verbatim under the R7 subject keys.
    individual = [e for e in ab if e.rule_code not in COUPLE_RULE_ORDER]
    assert individual == build_individual_evidence(zi, "A") + build_individual_evidence(chou, "B")

    # Pair evidence: identical IDs and operands regardless of argument order.
    pair_ab, pair_ba = pair_items(ab), pair_items(ba)
    assert pair_ab
    assert [(e.id, e.operands) for e in pair_ab] == [(e.id, e.operands) for e in pair_ba]
    for e in pair_ab:
        m = ID_RE.match(e.id)
        assert m and m["subject"] == "AB" and m["rule"] == e.rule_code, e.id

    # Only the individual items swap labels.
    def relabel(items: list[Evidence], subject: str) -> set[tuple[str, str]]:
        return {(e.id.split("-", 2)[2], e.text_ko) for e in items if e.id.split("-")[1] == subject}

    assert relabel(ab, "A") == relabel(ba, "B")
    assert relabel(ab, "B") == relabel(ba, "A")

    # Day branches 子/丑: 六合 (no 沖/刑/破/害 for this pair); day stems 丙/丁: no stem relation.
    day_branch = by_rule(ab, "COUPLE_DAY_BRANCH")
    assert [(e.operands["relation"], e.operands["name"]) for e in day_branch] == [("合", "子丑合")]
    # Entries are stored in canonical-JSON order (丑 U+4E11 before 子 U+5B50), not by subject.
    assert day_branch[0].operands["entries"] == [
        {"position": "day_branch", "value": "丑"},
        {"position": "day_branch", "value": "子"},
    ]
    assert day_branch[0].text_ko == "A 일지 子 · B 일지 丑: 육합(子丑合) 관계"
    assert by_rule(ab, "COUPLE_DAY_STEM") == []

    # Cross pillars: year branches 午/午 自刑, and 午/卯 破 (A年·B月 and A月·B年 are one fact).
    cross = {(e.operands["name"], tuple(sorted(d["position"] for d in e.operands["entries"])))
             for e in by_rule(ab, "COUPLE_CROSS_PILLARS")}
    assert ("午午刑", ("year_branch", "year_branch")) in cross
    assert ("卯午破", ("month_branch", "year_branch")) in cross
    assert not any("day_branch" in positions and positions.count("day_branch") == 2
                   for _, positions in cross)

    ids = [e.id for e in ab]
    assert len(ids) == len(set(ids))
    # Pair evidence follows the fixed rule order, then id.
    keys = [(COUPLE_RULE_ORDER.index(e.rule_code), e.id) for e in pair_ab]
    assert keys == sorted(keys)


def test_couple_year_candidates_inside_window(jia, gui):
    # Snapshot sewoon covers 2026-2028 only; later years come from 60-cycle arithmetic.
    evidence = build_couple_evidence(jia, gui, 2026, years=10)
    timing = by_rule(evidence, "COUPLE_YEAR_WINDOW")
    # 2028 戊申 and 2029 己酉: 戊/己 are 甲(male)'s 財 and 癸(female)'s 官. 2038/2039 are outside.
    assert sorted((e.operands["year"], e.operands["year_pillar"]) for e in timing) == [
        (2028, "戊申"),
        (2029, "己酉"),
    ]
    for e in timing:
        assert e.operands["condition"] == "SEWOON_STEM_SPOUSE_STAR"
        assert 2026 <= e.operands["year"] < 2036
        assert TIMING_ASSUMPTION in e.assumptions
        assert e.source_ref and "COUPLE_YEAR_WINDOW" in e.source_ref
        assert ID_RE.match(e.id)["subject"] == "AB"
    gods_2028 = sorted(
        (d["day_stem"], d["gender_for_daewoon"], d["ten_god"])
        for d in next(e for e in timing if e.operands["year"] == 2028).operands["entries"]
    )
    assert gods_2028 == [("甲", "male", "偏財"), ("癸", "female", "正官")]

    # A narrower window lists only its own years.
    narrow = by_rule(build_couple_evidence(jia, gui, 2029, years=1), "COUPLE_YEAR_WINDOW")
    assert [e.operands["year"] for e in narrow] == [2029]
    # Same IDs whichever window found them (operands carry the year, not the window).
    assert narrow[0].id == next(e.id for e in timing if e.operands["year"] == 2029)


def test_year_window_branch_condition():
    # Both day branches 戌: 卯 years form 卯戌合 with each spouse palace (2035 乙卯).
    a = chart("1990-03-10", time(10, 30), "male")  # 甲戌
    b = chart("1990-03-22", time(10, 30), "female")  # 丙戌
    assert a.day_pillar[1] == b.day_pillar[1] == "戌"
    timing = by_rule(build_couple_evidence(a, b, 2030, years=10), "COUPLE_YEAR_WINDOW")
    assert [(e.operands["year"], e.operands["condition"]) for e in timing] == [
        (2035, "SEWOON_BRANCH_HAP_SPOUSE_PALACE")
    ]
    assert timing[0].operands["entries"] == [{"day_branch": "戌", "name": "卯戌合"}] * 2


def test_zero_overlap_does_not_invent_year(zi, chou, jia, gui):
    # 丙(male) wants 庚/辛, 丁(female) wants 壬/癸; day branches 子/丑 need 丑/子 years.
    for start in (1990, 2026, 2050):
        evidence = build_couple_evidence(zi, chou, start, years=30)
        assert by_rule(evidence, "COUPLE_YEAR_WINDOW") == []
    # A window that misses the matching years yields nothing either (2030-2034).
    assert by_rule(build_couple_evidence(jia, gui, 2030, years=5), "COUPLE_YEAR_WINDOW") == []


@pytest.mark.parametrize("years", [0, 31, -1, 2.5, True, "10"])
def test_window_years_validated(zi, chou, years):
    with pytest.raises(ValueError):
        build_couple_evidence(zi, chou, 2026, years=years)


@pytest.mark.parametrize("start_year", [2026.0, "2026", None, True])
def test_window_start_year_validated(zi, chou, start_year):
    with pytest.raises(ValueError):
        build_couple_evidence(zi, chou, start_year)


def test_unknown_hour_no_hour_pair_claims(chou):
    # 己巳 丙子 丙寅 (hour unknown) PARTIAL: an alternative has day pillar 乙丑.
    unknown = chart("1990-01-01", None, "male")
    assert unknown.hour_pillar is None and unknown.certainty == "PARTIAL"
    # 庚午 己卯 乙亥 辛巳 (hour known).
    other = chart("1990-03-11", time(10, 30), "female")
    assert pillars(other) == ("庚午", "己卯", "乙亥", "辛巳")

    for evidence in (
        build_couple_evidence(unknown, other, 2026),
        build_couple_evidence(other, unknown, 2026),
    ):
        pair = pair_items(evidence)
        assert pair
        for e in pair:
            positions = [d.get("position", "") for d in e.operands.get("entries", [])]
            assert not any(p.startswith("hour") for p in positions), e
            assert "시" not in e.text_ko.replace("시기", ""), e
        # Day branches 寅/亥: 合 and 破, both depending on the ambiguous day pillar.
        day_branch = by_rule(evidence, "COUPLE_DAY_BRANCH")
        assert sorted(e.operands["name"] for e in day_branch) == ["寅亥合", "寅亥破"]
        assert all(e.assumptions.count(BOUNDARY_ASSUMPTION) == 1 for e in day_branch)

    # CONFIRMED pair without hour ambiguity carries no boundary assumption.
    assert not any(
        BOUNDARY_ASSUMPTION in e.assumptions
        for e in pair_items(build_couple_evidence(other, chou, 2026))
    )


FORBIDDEN = ("probability", "score", "확률", "o/x", "점수", "verdict", "outcome", "예측", "보장")


def _keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [k for k in value] + [k2 for v in value.values() for k2 in _keys(v)]
    if isinstance(value, list):
        return [k for v in value for k in _keys(v)]
    return []


def test_no_ox_or_probability_field(zi, chou, jia, gui):
    for a, b in ((zi, chou), (jia, gui), (gui, jia)):
        evidence = build_couple_evidence(a, b, 2026, years=30)
        assert evidence
        for e in evidence:
            dumped = e.model_dump(mode="json")
            names = [k.lower() for k in _keys(dumped)]
            texts = [e.text_ko.lower(), e.rule_code.lower()]
            for bad in FORBIDDEN:
                assert not any(bad in n for n in names), (bad, e)
                assert not any(bad in t for t in texts), (bad, e)
            assert not re.search(r"\b[OX]\b", e.text_ko), e
