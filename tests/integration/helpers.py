"""Shared integration-test helpers (synthetic data only)."""

import uuid
from datetime import date
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncEngine

from fateweave.domain.guide import SECTIONS, TIMING_RULES
from fateweave.models.facts import PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.models.reports import Claim, ReportDraft
from fateweave.services.analysis import AnalysisService
from fateweave.services.reports import ReportService
from fateweave.storage.db import make_sessionmaker


def full_sections(mode: str) -> dict[str, str]:
    """Hangul sections at each rules-v2 minimum length."""
    return {
        s.key: f"{s.key} 본문. " + "전통 명리 해석 문장. " * (s.min_chars // 11 + 1)
        for s in SECTIONS[mode]
    }


def valid_draft(prepared: PreparedAnalysis, **overrides) -> ReportDraft:
    """A draft that passes validate_report: required sections, real evidence IDs and operands."""
    computed = next(e for e in prepared.evidence_catalog if e.kind == "computed")
    values = {k: v for k, v in computed.operands.items() if isinstance(v, str | int | float)}
    claims = [
        Claim(
            kind="computed",
            rule_code=computed.rule_code,
            evidence_ids=[computed.id],
            computed_values=values,
            statement="계산된 사실을 그대로 인용한다.",
        )
    ]
    timing_rule = TIMING_RULES[prepared.mode]
    timing = next((e for e in prepared.evidence_catalog if e.rule_code == timing_rule), None)
    if timing is not None:
        claims.append(
            Claim(
                kind="interpretation",
                rule_code=timing_rule,
                evidence_ids=[timing.id],
                statement="전통적으로 인연이 움직이는 시기 단서로 본다.",
            )
        )
    cue = next((e for e in prepared.evidence_catalog if e.kind == "interpretation_cue"), None)
    if cue is not None:
        claims.append(
            Claim(
                kind="interpretation",
                rule_code=cue.rule_code,
                evidence_ids=[cue.id],
                statement="학파에 따라 해석이 달라질 수 있다.",
            )
        )
    data = dict(
        report_type=prepared.mode,
        sections=full_sections(prepared.mode),
        claims=claims,
        caveats=["전통 명리 해석이며 확률이 아니다."],
        generated_by="claude-test",
        prompt_version="prompt-v1",
    )
    data.update(overrides)
    return ReportDraft(**data)


def invalid_draft(prepared: PreparedAnalysis) -> ReportDraft:
    good = valid_draft(prepared)
    first = good.claims[0]
    key = next(iter(first.computed_values or {}))
    bad = first.model_copy(update={"computed_values": {key: "WRONG-VALUE"}})
    return good.model_copy(update={"claims": [bad, *good.claims[1:]]})


async def run_deterministic_e2e(
    engine: AsyncEngine,
    mode: Literal["individual", "couple"],
    prepared_births: list[BirthProfileInput],
) -> uuid.UUID:
    """prepare -> valid fake structured draft -> finalize -> get; no LLM, no network.

    ``prepared_births`` are synthetic birth inputs. Returns the finalized report_id.
    """
    sessionmaker = make_sessionmaker(engine)
    analysis = AnalysisService(sessionmaker, clock=lambda: date(2026, 10, 25))
    prepared = await analysis.prepare_analysis(mode, prepared_births)
    reports = ReportService(sessionmaker)
    result = await reports.finalize_report(
        prepared.analysis_id, valid_draft(prepared), f"e2e-{prepared.analysis_id}"
    )
    assert result.status == "FINALIZED", result
    assert result.report_id is not None and result.version == 1
    view = await reports.get_report(result.report_id)
    assert (view.report_id, view.version) == (result.report_id, 1)
    assert view.analysis_id == prepared.analysis_id and view.report_type == mode
    return result.report_id
