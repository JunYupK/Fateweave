"""rules-v5: the couple `assessments` block, its evidence, and the §8 validation rules."""

from datetime import time
from functools import lru_cache
from uuid import uuid4

import pytest

from fateweave.domain.assessments import build_couple_assessments, scoring_versions
from fateweave.domain.calendar import normalize_birth
from fateweave.domain.compatibility import policies
from fateweave.domain.couple import build_couple_evidence
from fateweave.domain.guide import SECTIONS, writing_guide
from fateweave.domain.manse import compute_chart
from fateweave.domain.validation import validate_report
from fateweave.models.facts import ChartSnapshot, Evidence, PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.models.reports import Claim, ReportDraft

START, YEARS = 2026, 10


@lru_cache
def chart(birth_date: str, hour: int | None, gender: str) -> ChartSnapshot:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date=birth_date,
            calendar="solar",
            birth_time=time(hour, 30) if hour is not None else None,
            gender_for_daewoon=gender,
        )
    )
    return compute_chart(birth, sewoon_start_year=START, sewoon_years=YEARS)


def jia(hour: int | None = 10) -> ChartSnapshot:
    return chart("1990-03-10", hour, "male")  # 庚午 己卯 甲戌 己巳


def gui(hour: int | None = 10) -> ChartSnapshot:
    return chart("1990-03-19", hour, "female")  # 庚午 己卯 癸未 丁巳


def assessed(a: ChartSnapshot, b: ChartSnapshot) -> tuple[dict, list[Evidence]]:
    catalog = build_couple_evidence(a, b, START, years=YEARS)
    block, scored = build_couple_assessments(a, b, catalog, START, YEARS)
    return block, catalog + scored


@lru_cache
def prepared() -> PreparedAnalysis:
    block, catalog = assessed(jia(), gui())
    return PreparedAnalysis(
        analysis_id=uuid4(),
        mode="couple",
        facts={"A": jia(), "B": gui()},
        evidence_catalog=catalog,
        missing_data=[],
        policy_version="manse-v2",
        rule_version="rules-v5",
        horizon_years=YEARS,
        start_year=START,
        writing_guide=writing_guide("couple"),
        assessments=block,
        scoring_versions=scoring_versions("couple"),
    )


def by_rule(catalog: list[Evidence], rule: str) -> list[Evidence]:
    return [e for e in catalog if e.rule_code == rule]


# ---- the block ---------------------------------------------------------------------------


def test_block_matches_its_evidence():
    run = prepared()
    comp = run.assessments["compatibility"]
    (score,) = by_rule(run.evidence_catalog, "COMPAT_SCORE")
    assert comp["evidence_id"] == score.id
    assert comp["score"] == score.operands["score"] == 67
    assert comp["score_type"] == score.operands["score_type"] == "interpretive_index"
    assert comp["grade"] == score.operands["grade"] == "보통"
    assert comp["scoring_version"] == "compat-score-v1" and comp["scale"] == 100
    assert "확률이 아님" in score.text_ko

    components = {
        e.operands["component"]: e for e in by_rule(run.evidence_catalog, "COMPAT_COMPONENT")
    }
    assert set(components) == set(comp["components"])
    for key, item in comp["components"].items():
        assert components[key].id == comp["component_evidence_ids"][key]
        assert components[key].operands["score"] == item["score"]
        assert components[key].operands["weight"] == comp["weights"][key]
    assert {k: c["score"] for k, c in comp["components"].items()} == {
        "day_master": 85,
        "spouse_palace": 50,
        "element_balance": 75,
        "overall_structure": 69,
    }
    # Applied rules cite the Fact evidence they score (P.破 → the day-branch 破 item).
    (palace,) = [e for e in by_rule(run.evidence_catalog, "COUPLE_DAY_BRANCH")]
    assert components["spouse_palace"].operands["applied"] == [
        {"rule": "P.破", "points": -10.0, "evidence_id": palace.id}
    ]


def test_timing_candidates_cite_their_year_evidence():
    run = prepared()
    window = run.assessments["timing_overlap"]
    assert window["timing_version"] == "timing-score-v1"
    assert (window["from_year"], window["to_year"]) == (2026, 2035)
    assert [c["year"] for c in window["candidates"]] == [2035, 2028, 2027, 2029, 2030, 2026]
    assert window["candidates"][1] | {"evidence_ids": []} == {
        "year": 2028,
        "pillar": "戊申",
        "a_signal": 4,
        "b_signal": 7,
        "evidence_ids": [],
    }
    years = {e.id: e.operands["year"] for e in by_rule(run.evidence_catalog, "COUPLE_TIMING")}
    for c in window["candidates"]:
        assert [years[i] for i in c["evidence_ids"]] == [c["year"]]
    (overlap,) = by_rule(run.evidence_catalog, "COUPLE_TIMING_OVERLAP")
    assert window["evidence_id"] == overlap.id
    assert [c["year"] for c in overlap.operands["candidates"]] == [
        c["year"] for c in window["candidates"]
    ]
    life = run.assessments["life_overlap"]
    assert life["ages"] == [20, 50] and life["candidates"]
    (life_ev,) = by_rule(run.evidence_catalog, "COUPLE_LIFE_TIMING")
    assert life["evidence_id"] == life_ev.id


def test_score_evidence_is_order_independent():
    _, ab = assessed(jia(), gui())
    _, ba = assessed(gui(), jia())
    scored = ("COMPAT_SCORE", "COMPAT_COMPONENT")
    assert [e.id for e in ab if e.rule_code in scored] == [
        e.id for e in ba if e.rule_code in scored
    ]


def test_unknown_hour_is_partial_not_zero():
    block, catalog = assessed(jia(), gui(hour=None))
    comp = block["compatibility"]
    assert comp["status"] == "PARTIAL" and comp["score"] > 0
    assert comp["components"]["element_balance"]["status"] == "REDUCED_SCOPE"
    assert comp["components"]["overall_structure"]["status"] == "REDUCED_SCOPE"
    (score,) = by_rule(catalog, "COMPAT_SCORE")
    assert any("REDUCED_SCOPE" in a for a in score.assumptions)
    if comp["score_range"]:
        low, high = comp["score_range"]
        assert score.operands["score_range"] == [low, high]
        assert f"{low}~{high}" in score.text_ko


@pytest.mark.parametrize(
    ("score", "label"),
    [(100, "매우 조화"), (85, "매우 조화"), (84, "조화"), (70, "조화"), (69, "보통"),
     (55, "보통"), (54, "노력 필요"), (40, "노력 필요"), (39, "긴장 큼"), (0, "긴장 큼")],
)  # fmt: skip
def test_grade_bands(score, label):
    assert policies.grade(policies.COMPAT_SCORE_V1, score) == label


def test_scoring_versions_and_guide():
    assert scoring_versions("individual") == {"timing_score": "timing-score-v1"}
    assert scoring_versions("couple") == {
        "timing_score": "timing-score-v1",
        "compat_score": "compat-score-v1",
    }
    guide = writing_guide("couple")
    assert guide["required_score_rule"] == "COMPAT_SCORE"
    assert any("SCORE_MISMATCH" in r for r in guide["style_rules"])
    assert "required_score_rule" not in writing_guide("individual")


# ---- validation (spec §8) ----------------------------------------------------------------


def base_sections(extra: dict[str, str] | None = None) -> dict[str, str]:
    secs = {
        s.key: f"{s.key} 본문. " + "전통 명리 해석 문장. " * (s.min_chars // 11 + 1)
        for s in SECTIONS["couple"]
    }
    for key, text in (extra or {}).items():
        secs[key] = text + " " + secs[key]
    return secs


def score_claim(value: int | None = None) -> Claim:
    (score,) = by_rule(prepared().evidence_catalog, "COMPAT_SCORE")
    return Claim(
        kind="computed",
        rule_code="COMPAT_SCORE",
        evidence_ids=[score.id],
        computed_values={"score": score.operands["score"] if value is None else value},
        statement="궁합 지수",
    )


def timing_claim() -> Claim:
    e = by_rule(prepared().evidence_catalog, "COUPLE_TIMING")[0]
    return Claim(
        kind="computed",
        rule_code="COUPLE_TIMING",
        evidence_ids=[e.id],
        computed_values={"year": e.operands["year"]},
        statement="연도별 단서",
    )


def check(extra=None, claims=None) -> list[str]:
    report = ReportDraft(
        report_type="couple",
        sections=base_sections(extra),
        claims=claims if claims is not None else [timing_claim(), score_claim()],
        caveats=[],
        generated_by="claude",
        prompt_version="p1",
    )
    result = validate_report(report, prepared())
    return [e.code for e in result.errors]


def test_valid_couple_draft_passes():
    assert check() == []


def test_score_claim_is_required():
    assert check(claims=[timing_claim()]) == ["UNSUPPORTED_CLAIM"]


def test_score_claim_with_another_value_is_score_mismatch():
    assert check(claims=[timing_claim(), score_claim(80)]) == ["SCORE_MISMATCH"]


@pytest.mark.parametrize(
    "text",
    [
        "두 사람의 궁합 지수는 67점으로 보통 등급이다.",
        "궁합 점수: 67점",
        "궁합 지수는 100점 만점에 67점이다.",
        "궁합 지수 67/100",
        "배우자궁 점수는 50점, 일간 관계 85점, 오행 보완 영역 75점, 전체 명식 조화 69점이다.",
        "배우자궁 합 단서는 1점을 더한다.",  # not a quoted area score
    ],
)
def test_quoted_server_scores_pass(text):
    assert check({"marital_compatibility": text}) == []


@pytest.mark.parametrize(
    "text",
    [
        "두 사람의 궁합 지수는 80점이다.",
        "궁합 점수 100점 만점에 90점",
        "배우자궁 점수는 70점이다.",
        "오행 보완 60점",
    ],
)
def test_changed_scores_are_rejected(text):
    assert check({"summary": text}) == ["SCORE_MISMATCH"]


def _non_candidate_year() -> int:
    run = prepared()
    candidates = {
        c["year"]
        for key in ("timing_overlap", "life_overlap")
        for c in run.assessments[key]["candidates"]
    }
    return next(y for y in range(START, START + YEARS) if y not in candidates)


@pytest.mark.parametrize(
    "text",
    [
        "두 사람 모두에게 유리한 공통 후보는 2035년과 2028년이다.",
        "2026~2035년 중 공통 유리 시기 1순위는 2035년이다.",
        "| 2028 | 무신 | 4 | 7 | 공통 후보 2순위 |",
        "1990년생 두 사람의 공통 유리 시기는 2035년이다.",
    ],
)
def test_candidate_years_pass(text):
    assert check({"marriage_timing": text}) == []


def test_non_candidate_years_are_rejected():
    year = _non_candidate_year()
    for text in (
        f"두 사람의 공통 유리 시기는 {year}년이다.",
        f"결혼 적기는 {year}년으로 본다.",
        f"| {year} | 간지 | 3 | 3 | 공통 후보 1순위 |",
    ):
        assert check({"marriage_timing": text}) == ["TIMING_NOT_CANDIDATE"], text


def test_non_candidate_year_may_be_named_as_such():
    year = _non_candidate_year()
    for text in (
        f"{year}년은 한쪽에만 유리해 공통 후보가 아니다.",
        f"| {year} | 간지 | 3 | 3 | 공통 후보 아님 |",
        f"{year}년은 공통 후보에서 빠졌다.",
    ):
        assert check({"marriage_timing": text}) == [], text


def test_no_candidate_means_no_best_year():
    run = prepared()
    catalog = [
        e.model_copy(update={"operands": {**e.operands, "candidates": []}})
        if e.rule_code in ("COUPLE_TIMING_OVERLAP", "COUPLE_LIFE_TIMING")
        else e
        for e in run.evidence_catalog
    ]
    empty = run.model_copy(update={"evidence_catalog": catalog})
    report = ReportDraft(
        report_type="couple",
        sections=base_sections({"marriage_timing": "그래도 최적의 해는 2035년이다."}),
        claims=[timing_claim(), score_claim()],
        generated_by="claude",
        prompt_version="p1",
    )
    assert [e.code for e in validate_report(report, empty).errors] == ["TIMING_NOT_CANDIDATE"]
