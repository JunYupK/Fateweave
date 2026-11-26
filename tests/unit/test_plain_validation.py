"""rules-v6 plain-language checks: JARGON_HEAVY and the 1% hanja limit, for every mode."""

from datetime import time
from functools import lru_cache
from uuid import uuid4

import pytest

from fateweave.domain.calendar import normalize_birth
from fateweave.domain.guide import SECTIONS, rule_version_number, writing_guide
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import build_individual_evidence
from fateweave.domain.validation import validate_report
from fateweave.models.facts import PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.models.reports import Claim, ReportDraft

JARGON = "천간 무토가 상관이라 말이 앞선다. "
PLAIN = "겉으로 드러나는 기운이 틀을 깨는 표현력과 말솜씨라서 말이 먼저 나간다. "


@lru_cache
def _run() -> PreparedAnalysis:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date="1990-01-01",
            calendar="solar",
            birth_time=time(16, 30),
            gender_for_daewoon="male",
        )
    )
    snap = compute_chart(birth, sewoon_start_year=2026, sewoon_years=3)
    return PreparedAnalysis(
        analysis_id=uuid4(),
        mode="individual",
        facts={"self": snap},
        evidence_catalog=build_individual_evidence(snap, "self"),
        missing_data=[],
        policy_version="manse-v2",
        rule_version="rules-v6",
        horizon_years=3,
        start_year=2026,
    )


@pytest.fixture(scope="module")
def run_v6() -> PreparedAnalysis:
    return _run()


def claims(run: PreparedAnalysis) -> list[Claim]:
    row = next(e for e in run.evidence_catalog if e.rule_code == "YEAR_TIMING")
    return [
        Claim(
            kind="computed",
            rule_code="YEAR_TIMING",
            evidence_ids=[row.id],
            computed_values={"year": row.operands["year"]},
            statement="연도별 단서",
        )
    ]


def check(run: PreparedAnalysis, overrides: dict[str, str] | None = None) -> list[str]:
    secs = {s.key: "가나다라 마바사. " * (s.min_chars // 9 + 1) for s in SECTIONS["individual"]}
    secs.update(overrides or {})
    d = ReportDraft(
        report_type="individual",
        sections=secs,
        claims=claims(run),
        generated_by="claude",
        prompt_version="p1",
    )
    return [e.code for e in validate_report(d, run).errors]


def test_rule_version_number():
    assert rule_version_number("rules-v6") == 6 and rule_version_number("rules-v10") == 10


def test_jargon_heavy_section_rejected(run_v6):
    assert check(run_v6, {"personality": JARGON * 40}) == ["JARGON_HEAVY"]


def test_jargon_message_names_terms_and_plain_meaning(run_v6):
    d = ReportDraft(
        report_type="individual",
        sections={
            **{s.key: "가나다라 마바사. " * (s.min_chars // 9 + 1) for s in SECTIONS["individual"]},
            "personality": JARGON * 40,
        },
        claims=claims(run_v6),
        generated_by="claude",
        prompt_version="p1",
    )
    (err,) = validate_report(d, run_v6).errors
    assert err.path == "sections.personality"
    assert "상관" in err.message and "틀을 깨는 표현력·말솜씨" in err.message


def test_plain_section_passes(run_v6):
    assert check(run_v6, {"personality": PLAIN * 20}) == []


def test_few_terms_are_allowed(run_v6):
    # 1 term per 300 chars: two terms in a ~700-char section pass.
    text = "겉으로 드러나는 기운이 틀을 깨는 표현력(상관)이라 말이 먼저 나간다. " + PLAIN * 18
    assert check(run_v6, {"personality": text}) == []


def test_evidence_explanation_is_exempt(run_v6):
    text = "천간 무토가 상관, 지지 자수가 편관. " * 20
    assert check(run_v6, {"evidence_explanation": text}) == []


def test_hanja_limit_is_one_percent(run_v6):
    text = "가" * 980 + "甲" * 20  # 2%
    assert check(run_v6, {"personality": text}) == ["HANJA_HEAVY"]


def test_rules_v5_run_keeps_old_checks(run_v6):
    old = run_v6.model_copy(update={"rule_version": "rules-v5"})
    assert check(old, {"personality": JARGON * 40}) == []
    assert check(old, {"personality": "가" * 980 + "甲" * 20}) == []


def test_guide_carries_plain_terms():
    for mode in ("individual", "couple"):
        g = writing_guide(mode)
        assert g["plain_terms"]["상관"] == "틀을 깨는 표현력·말솜씨"
        assert any("plain_terms" in r for r in g["style_rules"])
        assert not any("바로 뒤에 일상 언어로 풀어" in r for r in g["style_rules"])
