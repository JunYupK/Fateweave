import re
from datetime import time
from typing import Any

import pytest

from fateweave.domain.calendar import normalize_birth
from fateweave.domain.couple import COUPLE_RULE_ORDER, build_couple_evidence
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import (
    BOUNDARY_ASSUMPTION,
    DAEWOON_PRIMARY_ONLY,
    DAEWOON_START_APPROXIMATE,
    build_individual_evidence,
    sort_key,
)
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
    assert day_branch[0].text_ko == "A 일지 자 · B 일지 축: 육합(자축합) 관계"
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
    # Pair evidence follows the fixed rule order, then the year (timing rules), then id.
    keys = [sort_key(COUPLE_RULE_ORDER)(e) for e in pair_ab]
    assert keys == sorted(keys)


def timing_rows(evidence: list[Evidence]) -> dict[int, Evidence]:
    return {e.operands["year"]: e for e in by_rule(evidence, "COUPLE_TIMING")}


def test_couple_timing_records_every_year(jia, gui):
    # Snapshot sewoon covers 2026-2028 only; later years come from 60-cycle arithmetic.
    rows = timing_rows(build_couple_evidence(jia, gui, 2026, years=10))
    assert sorted(rows) == list(range(2026, 2036))
    # 2028 戊申: 戊 is 甲(male)'s 偏財 and 癸(female)'s 正官 — both carry a spouse-star cue.
    e2028 = rows[2028]
    assert e2028.operands["year_pillar"] == "戊申"
    assert e2028.operands["both_core"] is True
    for entry in e2028.operands["entries"]:
        assert "SPOUSE_STAR_STEM" in entry["cues"]
    assert sorted(e["day_pillar"] for e in e2028.operands["entries"]) == ["甲戌", "癸未"]
    # Joint ranks are a permutation, and years where both carry core cues come first.
    ranks = {y: e.operands["joint_rank"] for y, e in rows.items()}
    assert sorted(ranks.values()) == list(range(1, 11))
    both = [y for y, e in rows.items() if e.operands["both_core"]]
    assert both and max(ranks[y] for y in both) < min(
        ranks[y] for y in rows if y not in both
    )
    for e in rows.values():
        assert TIMING_ASSUMPTION in e.assumptions
        assert ID_RE.match(e.id)["subject"] == "AB"
        assert "COUPLE_TIMING" in e.source_ref
        assert not re.search(r"[\u4e00-\u9fff]", e.text_ko), e.text_ko
        assert e.operands["both_core"] == all(x["core_count"] > 0 for x in e.operands["entries"])
    # A narrower window lists only its own years.
    narrow = timing_rows(build_couple_evidence(jia, gui, 2029, years=1))
    assert list(narrow) == [2029]


def test_couple_timing_spouse_palace_hap():
    # Both day branches 戌: 卯 years form 卯戌合 with each spouse palace (2035 乙卯).
    a = chart("1990-03-10", time(10, 30), "male")  # 甲戌
    b = chart("1990-03-22", time(10, 30), "female")  # 丙戌
    assert a.day_pillar[1] == b.day_pillar[1] == "戌"
    rows = timing_rows(build_couple_evidence(a, b, 2030, years=10))
    for entry in rows[2035].operands["entries"]:
        assert "SPOUSE_PALACE_HAP" in entry["cues"]
    assert rows[2035].operands["both_core"] is True


def test_couple_extra_pair_rules(jia, gui):
    evidence = build_couple_evidence(jia, gui, 2026, years=3)
    (element,) = by_rule(evidence, "COUPLE_DAY_STEM_ELEMENT")
    # 甲(木) and 癸(水): 水生木.
    assert (element.operands["relation"], element.operands["from"], element.operands["to"]) == (
        "相生",
        "水",
        "木",
    )
    (match,) = by_rule(evidence, "COUPLE_SPOUSE_STAR_MATCH")
    by_stem = {e["day_stem"]: e for e in match.operands["entries"]}
    # 甲 male: partner 癸 is 正印 (not a spouse star); 癸 female: partner 甲 is 傷官.
    assert by_stem["甲"]["partner_stem_ten_god"] == "正印"
    assert by_stem["癸"]["partner_stem_ten_god"] == "傷官"
    assert not by_stem["甲"]["stem_is_spouse_star"] and not by_stem["癸"]["stem_is_spouse_star"]
    (complement,) = by_rule(evidence, "COUPLE_ELEMENT_COMPLEMENT")
    for entry in complement.operands["entries"]:
        assert set(entry["partner_has"]) <= set(entry["lacking"])


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


TRANSITION = "daewoon transition year; boundary depends on start age convention"


def daewoon_by_year(evidence: list[Evidence]) -> dict[int, Evidence]:
    return {e.operands["year"]: e for e in by_rule(evidence, "COUPLE_LUCK_OVERLAP")}


def test_luck_overlap_symmetric_record(zi, chou):
    # zi: forward daewoon from 7y12m (庚辰, 辛巳 from 17, ...); chou: backward from 2y5m.
    assert (zi.daewoon.start_age, zi.daewoon.start_months_offset) == (7, 12)
    assert (chou.daewoon.start_age, chou.daewoon.start_months_offset) == (2, 5)
    ab = build_couple_evidence(zi, chou, 2026)
    ba = build_couple_evidence(chou, zi, 2026)
    luck_ab, luck_ba = by_rule(ab, "COUPLE_LUCK_OVERLAP"), by_rule(ba, "COUPLE_LUCK_OVERLAP")
    assert [(e.id, e.operands) for e in luck_ab] == [(e.id, e.operands) for e in luck_ba]
    # One record per window year, with no selection condition.
    assert sorted(daewoon_by_year(ab)) == list(range(2026, 2036))
    e = daewoon_by_year(ab)[2027]
    assert e.kind == "computed" and ID_RE.match(e.id)["subject"] == "AB"
    assert e.operands["year_pillar"] == "丁未"
    # zi is 37 in 2027 (壬午 27-36 → 癸未 from 37 or 38): both listed; chou 乙亥 (32-41).
    assert sorted(map(tuple, (d["daewoon"] for d in e.operands["entries"]))) == [
        ("乙亥",),
        ("壬午", "癸未"),
    ]
    assert e.text_ko == "2027년 정미: A 대운 임오 → 계미 (전환 연도), B 대운 을해"
    assert TRANSITION in e.assumptions
    assert not any("condition" in x.operands for x in luck_ab)


def test_luck_overlap_transition_and_window(zi, chou):
    evidence = build_couple_evidence(zi, chou, 2007, years=3)
    records = daewoon_by_year(evidence)
    assert sorted(records) == [2007, 2008, 2009]  # nothing outside the window
    a_lines = {y: next(d["daewoon"] for d in r.operands["entries"] if "辛巳" in d["daewoon"])
               for y, r in records.items()}
    # 辛巳 starts at 17 (2007) or 17y12m (2008), depending on the start-offset convention.
    assert a_lines == {2007: ["庚辰", "辛巳"], 2008: ["庚辰", "辛巳"], 2009: ["辛巳"]}
    assert TRANSITION in records[2007].assumptions and TRANSITION in records[2008].assumptions
    assert TRANSITION not in records[2009].assumptions  # chou: 丁丑 all of 2009

    # Before the first daewoon starts, the person's daewoon is recorded as unavailable.
    early = daewoon_by_year(build_couple_evidence(zi, chou, 1990, years=1))[1990]
    assert [d["daewoon"] for d in early.operands["entries"]] == [["unavailable"]] * 2
    assert early.text_ko == "1990년 경오: A 대운 자료 없음, B 대운 자료 없음"


def test_luck_overlap_partial_carries_daewoon_assumptions(chou):
    unknown = chart("1990-01-01", None, "male")  # PARTIAL, DAEWOON_START_APPROXIMATE
    records = by_rule(build_couple_evidence(unknown, chou, 2026), "COUPLE_LUCK_OVERLAP")
    assert len(records) == 10
    for e in records:
        assert DAEWOON_PRIMARY_ONLY in e.assumptions
        assert DAEWOON_START_APPROXIMATE in e.assumptions
    confirmed = by_rule(build_couple_evidence(chou, chou, 2026), "COUPLE_LUCK_OVERLAP")
    assert not any(DAEWOON_PRIMARY_ONLY in e.assumptions for e in confirmed)


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
