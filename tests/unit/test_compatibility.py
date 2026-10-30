"""compat-score-v1: rule-table examples from the design spec and evaluator invariants."""

from datetime import time

import pytest

from fateweave.domain.calendar import normalize_birth
from fateweave.domain.compatibility import assess, policies, scoring
from fateweave.domain.couple import build_couple_evidence
from fateweave.domain.manse import compute_chart
from fateweave.models.facts import ChartSnapshot
from fateweave.models.inputs import BirthProfileInput

V1 = policies.get("compat-score-v1")


def chart(birth_date: str, birth_time: time | None, gender: str) -> ChartSnapshot:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date=birth_date,
            calendar="solar",
            birth_time=birth_time,
            gender_for_daewoon=gender,
            longitude=126.9784,
        )
    )
    return compute_chart(birth, sewoon_start_year=2026, sewoon_years=10)


@pytest.fixture(scope="module")
def jia() -> ChartSnapshot:
    snap = chart("1990-03-10", time(10, 0), "male")  # 庚午 己卯 甲戌 己巳
    assert (snap.day_pillar, snap.certainty) == ("甲戌", "CONFIRMED")
    return snap


@pytest.fixture(scope="module")
def gui() -> ChartSnapshot:
    snap = chart("1990-03-19", time(10, 0), "female")  # 庚午 己卯 癸未 丁巳
    assert (snap.day_pillar, snap.certainty) == ("癸未", "CONFIRMED")
    return snap


def test_policy_weights_sum_to_one():
    assert V1.version == "compat-score-v1"
    assert V1.weights == {
        "day_master": 0.20,
        "spouse_palace": 0.35,
        "element_balance": 0.30,
        "overall_structure": 0.15,
    }
    assert round(sum(V1.weights.values()), 10) == 1.0
    with pytest.raises(KeyError):
        policies.get("compat-score-v0")


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("巳", "申", 75),  # 六合 +25 and 破 -10 hold together: max positive + max negative
        ("子", "未", 40),  # 害 -15 and 怨嗔 -20: only the larger negative applies
        ("子", "午", 25),  # 沖 -35
        ("午", "未", 85),  # 六合
        ("寅", "午", 75),  # same 三合 group (半合) +15
        ("子", "子", 60),  # same branch, no 自刑: neutral
        ("辰", "辰", 40),  # 自刑 -20
        ("子", "卯", 40),  # 刑 -20
        ("卯", "申", 40),  # 怨嗔 -20 and 鬼門 -10
    ],
)
def test_spouse_palace_rule_table(a, b, expected):
    result = scoring.spouse_palace(a, b, V1)
    assert result.score == expected
    assert scoring.spouse_palace(b, a, V1).score == expected  # order independent


def test_spouse_palace_keeps_every_relation_fact():
    result = scoring.spouse_palace("巳", "申", V1)
    applied = {(c.rule, c.points) for c in result.contributions if c.applied}
    ignored = {c.rule for c in result.contributions if not c.applied}
    assert applied == {("P.合", 25), ("P.破", -10)}
    assert ignored == set()
    result = scoring.spouse_palace("子", "未", V1)
    assert {c.rule for c in result.contributions if c.applied} == {"P.怨嗔"}
    assert {c.rule for c in result.contributions if not c.applied} == {"P.害"}


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("甲", "己", 90),  # 天干合 (also 甲剋己: the 合 takes precedence, no double count)
        ("甲", "庚", 25),  # 天干沖
        ("甲", "丙", 75),  # 相生
        ("甲", "乙", 60),  # 比和
        ("甲", "戊", 40),  # 相剋 without 沖
        ("戊", "己", 60),  # 比和 (戊己 沖 is not used)
    ],
)
def test_day_master_relation_table(a, b, expected):
    # Only the relation contribution is checked here (spouse-star bonuses are tested below).
    result = scoring.day_master(a, "子", "male", b, "子", "male", V1)
    base = next(c for c in result.contributions if c.rule.startswith("D.relation"))
    assert base.points == expected


def test_day_master_spouse_star_bonus():
    # 甲(male) and 己(female): 己 is 甲's 正財 (+10); 甲 is 己's 正官 (+10); 合 90 -> capped 100.
    result = scoring.day_master("甲", "子", "male", "己", "子", "female", V1)
    assert result.score == 100
    bonuses = sorted(c.rule for c in result.contributions if c.rule.startswith("D.spouse"))
    assert bonuses == ["D.spouse_star_stem", "D.spouse_star_stem"]


def test_element_direction_formula():
    # need(A) = {水, 金}; B has 水 only -> 50 + 50 * 1/2 = 75.
    counts_b = {"木": 2, "火": 2, "土": 2, "金": 0, "水": 2}
    assert scoring.element_direction({"水", "金"}, set(), counts_b, V1) == 75
    # Nothing needed -> neutral 70.
    assert scoring.element_direction(set(), set(), counts_b, V1) == 70
    # B piles onto A's excess 火 (3 or more) -> -15.
    heavy = {"木": 1, "火": 3, "土": 2, "金": 1, "水": 1}
    assert scoring.element_direction({"水"}, {"火"}, heavy, V1) == 100 - 15


def test_assess_is_deterministic_and_order_independent(jia, gui):
    ab = assess(jia, gui)
    ba = assess(gui, jia)
    assert ab == assess(jia, gui)
    assert ab.score == ba.score
    assert ab.score_type == "interpretive_index" and ab.scale == 100
    assert ab.scoring_version == "compat-score-v1"
    for key in V1.weights:
        assert ab.components[key].score == ba.components[key].score
    e_ab, e_ba = ab.components["element_balance"].details, ba.components["element_balance"].details
    assert (e_ab["a_to_b"], e_ab["b_to_a"]) == (e_ba["b_to_a"], e_ba["a_to_b"])
    # Weighted sum of the components, rounded.
    expected = sum(V1.weights[k] * ab.components[k].score for k in V1.weights)
    assert ab.score == round(expected)
    assert 0 <= ab.score <= 100
    assert ab.status == "OK" and ab.score_range is None


def test_assess_links_contributions_to_fact_evidence(jia, gui):
    evidence = build_couple_evidence(jia, gui, 2026, years=3)
    ids = {e.id for e in evidence}
    result = assess(jia, gui, evidence=evidence)
    linked = [
        c
        for comp in result.components.values()
        for c in comp.contributions
        if c.evidence_id is not None
    ]
    assert linked and all(c.evidence_id in ids for c in linked)
    # The day-stem element relation is a fact the day-master score must cite.
    d = result.components["day_master"].contributions
    assert any(c.evidence_id and "COUPLE_DAY_STEM_ELEMENT" in c.evidence_id for c in d)


def test_unknown_hour_reduces_scope_never_zero(jia):
    unknown = chart("1990-03-19", None, "female")
    assert unknown.hour_pillar is None
    result = assess(jia, unknown)
    assert result.status == "PARTIAL"
    assert result.components["element_balance"].status == "REDUCED_SCOPE"
    assert result.components["overall_structure"].status == "REDUCED_SCOPE"
    assert result.components["day_master"].status == "OK"
    assert all(c.score is not None and c.score > 0 for c in result.components.values())
    assert any("시주" in note for note in result.excluded)
    # No hour position is used by the overall-structure pairs.
    w = result.components["overall_structure"].contributions
    assert not any("hour" in c.basis for c in w)


def test_day_pillar_ambiguity_reports_a_range(jia):
    # 1990-01-01 with the hour unknown: an alternative day pillar exists (乙丑 vs 丙寅).
    ambiguous = chart("1990-01-01", None, "female")
    assert ambiguous.certainty == "PARTIAL"
    assert any(a.day_pillar != ambiguous.day_pillar for a in ambiguous.alternatives)
    result = assess(jia, ambiguous)
    assert result.status == "PARTIAL"
    low, high = result.score_range
    assert low <= result.score <= high


def test_overall_structure_caps_and_counts_mixed_pairs(jia, gui):
    result = assess(jia, gui).components["overall_structure"]
    details = result.details
    assert 0 <= details["positive"] <= V1.structure_cap
    assert -V1.structure_cap <= details["negative"] <= 0
    assert result.score == round(
        max(0, min(100, V1.structure_base + details["positive"] + details["negative"]))
    )
    # The day stem-stem and day branch-branch pairs belong to D and P, never to W.
    assert not any(
        c.basis.startswith("A 일간") and "B 일간" in c.basis for c in result.contributions
    )
    assert not any(
        c.basis.startswith("A 일지") and "B 일지" in c.basis for c in result.contributions
    )


def test_overall_structure_counts_each_fact_once(jia, gui):
    # Both charts have 庚午 year and 己卯 month: A年·B月 and A月·B年 are the same fact.
    evidence = build_couple_evidence(jia, gui, 2026, years=3)
    w = assess(jia, gui, evidence=evidence).components["overall_structure"].contributions
    cited = [c.evidence_id for c in w if c.evidence_id]
    assert len(cited) == len(set(cited))
