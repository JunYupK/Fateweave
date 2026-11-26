"""rules-v6 general (종합 사주) sections, writing guide and validation rules."""

from datetime import time
from functools import lru_cache
from uuid import uuid4

from fateweave.domain.calendar import normalize_birth
from fateweave.domain.general import build_general_evidence
from fateweave.domain.guide import (
    GENERAL_REQUIRED_CITATIONS,
    SECTIONS,
    required_sections,
    writing_guide,
)
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import build_individual_evidence
from fateweave.domain.validation import validate_report
from fateweave.models.facts import PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.models.reports import Claim, ReportDraft

FILLER = "가나다라 마바사. "
DISCLAIMER = "의학적 진단이 아니며 몸에 이상이 있으면 의료진과 상담하세요."
CITED = ("TEN_GOD_DISTRIBUTION", "APTITUDE_CUES", "KINSHIP", "PALACES", "LUCK_FLOW")


@lru_cache
def run() -> PreparedAnalysis:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date="1990-03-12",
            calendar="solar",
            birth_time=time(10, 30),
            gender_for_daewoon="male",
        )
    )
    snap = compute_chart(birth, sewoon_start_year=2026, sewoon_years=3)
    return PreparedAnalysis(
        analysis_id=uuid4(),
        mode="general",
        facts={"self": snap},
        evidence_catalog=build_general_evidence(snap),
        missing_data=[],
        policy_version="manse-v2",
        rule_version="rules-v6",
        horizon_years=3,
        start_year=2026,
        writing_guide=writing_guide("general"),
    )


def first(rule: str):
    return next(e for e in run().evidence_catalog if e.rule_code == rule)


def anchor() -> Claim:
    e = first("PILLARS")
    return Claim(
        kind="computed",
        rule_code="PILLARS",
        evidence_ids=[e.id],
        computed_values={"position": e.operands["position"], "pillar": e.operands["pillar"]},
        statement="기둥",
    )


def cite(rule: str) -> Claim:
    return Claim(
        kind="interpretation", rule_code=rule, evidence_ids=[first(rule).id], statement="해석"
    )


def check(
    sections: dict[str, str] | None = None,
    drop_rule: str | None = None,
    caveats: list[str] | None = None,
    health: str | None = None,
    health_extra: str = "",
) -> list[str]:
    secs = {s.key: FILLER * (s.min_chars // 9 + 1) for s in SECTIONS["general"]}
    secs["health"] = health if health is not None else f"{DISCLAIMER} {health_extra} " + FILLER * 45
    secs.update(sections or {})
    draft = ReportDraft(
        report_type="general",
        sections=secs,
        claims=[*(cite(r) for r in CITED if r != drop_rule), anchor()],
        caveats=caveats
        if caveats is not None
        else ["전통 해석이며 시각 경계에 따라 달라질 수 있다."],
        generated_by="claude",
        prompt_version="p1",
    )
    return [e.code for e in validate_report(draft, run()).errors]


def test_valid_general_draft_passes():
    assert check() == []


def test_required_sections():
    assert required_sections("general", "rules-v6") == (
        "summary",
        "temperament",
        "career",
        "wealth",
        "health",
        "family_relations",
        "life_flow",
        "year_flow",
    )
    mins = {s.key: s.min_chars for s in SECTIONS["general"]}
    assert mins["temperament"] == mins["career"] == mins["family_relations"] == 1000
    assert sum(mins.values()) == 5600


def test_short_strengthened_section():
    assert check(sections={"career": "짧다. " * 50}) == ["SECTION_TOO_SHORT"]


def test_missing_citation():
    assert check(drop_rule="APTITUDE_CUES") == ["UNSUPPORTED_CLAIM"]


def test_kinship_or_palaces_satisfies():
    assert check(drop_rule="KINSHIP") == []


def test_missing_luck_flow_citation():
    assert "UNSUPPORTED_CLAIM" in check(drop_rule="LUCK_FLOW")


def test_missing_caveats():
    assert check(caveats=[]) == ["MISSING_CAVEATS"]
    assert check(caveats=["  "]) == ["MISSING_CAVEATS"]


def test_health_disclaimer_missing():
    assert check(health="오행 기운이 치우쳐 쉽게 지친다. " * 30) == ["HEALTH_DISCLAIMER_MISSING"]


def test_health_medical_claim():
    assert check(health_extra="고혈압을 조심하고 한약을 복용하면 좋다.") == ["HEALTH_MEDICAL_CLAIM"]


def test_disclaimer_sentence_may_name_treatment():  # Review Focus 5
    assert check(health_extra="이 내용은 질환을 진단하거나 치료하는 것이 아니다.") == []


def test_traditional_organ_mapping_is_allowed():
    text = "전통적으로 금 기운이 약하면 폐와 호흡기, 피부 쪽을 아끼라고 본다."
    assert check(health_extra=text) == []


def test_general_jargon_is_checked():
    assert check(sections={"temperament": "천간 무토가 상관이라 말이 앞선다. " * 70}) == [
        "JARGON_HEAVY"
    ]


def test_guide_general():
    g = writing_guide("general")
    assert g["required_timing_rule"] == "LUCK_FLOW" and "plain_terms" in g
    assert g["required_citations"] == [list(x) for x in GENERAL_REQUIRED_CITATIONS]
    assert any("진단" in r for r in g["style_rules"])
    assert any("caveats" in r for r in g["style_rules"])
    assert "required_citations" not in writing_guide("individual")


def test_two_sentence_disclaimer_passes():  # final review
    text = "이 풀이는 의학적 진단이 아닙니다. 혹시 질환이 의심되면 꼭 의료진과 상담하세요."
    assert check(health=text + " " + FILLER * 45) == []
    text2 = "의학적 진단이 아니다. 몸이 불편하면 병원에서 진찰과 처방을 받는 것이 우선이다."
    assert check(health=text2 + " " + FILLER * 45) == []


def test_doctor_counts_as_referral():
    assert check(health="의학적 진단이 아니니 불편하면 의사와 상담하세요. " + FILLER * 45) == []


def test_named_disease_in_a_diagnosis_sentence_is_rejected():
    assert check(health_extra="토 기운이 넘치면 당뇨 진단을 받기 쉬운 체질로 본다.") == [
        "HEALTH_MEDICAL_CLAIM"
    ]


def test_general_guide_has_no_marriage_rules():
    rules = writing_guide("general")["style_rules"]
    assert not any("결혼 시기는 연도와 월" in r for r in rules)
    assert not any("limitations" in r for r in rules)
    assert any("결혼 시기는 연도와 월" in r for r in writing_guide("individual")["style_rules"])


def test_hour_unknown_spouse_star_is_not_absent():
    snap = compute_chart(
        normalize_birth(
            BirthProfileInput(birth_date="1995-09-09", calendar="solar", gender_for_daewoon="male")
        ),
        sewoon_start_year=2026,
        sewoon_years=3,
    )
    general = next(e for e in build_general_evidence(snap) if e.rule_code == "SPOUSE_STAR")
    assert "확인 불가" in general.text_ko
    individual = next(
        e for e in build_individual_evidence(snap, "self") if e.rule_code == "SPOUSE_STAR"
    )
    assert individual.id == general.id and "확인 불가" not in individual.text_ko
