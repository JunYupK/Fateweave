"""Deterministic end-to-end report workflow: no LLM, no network, synthetic births only.

The real Claude chat / ChatGPT handoff is a manual acceptance checklist (scripts/acceptance.md).
"""

import re
import uuid
from datetime import date, time

from helpers import invalid_draft, run_deterministic_e2e, valid_draft
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fateweave.models.inputs import BirthProfileInput
from fateweave.services.analysis import AnalysisService
from fateweave.services.reports import ReportService
from fateweave.storage.db import make_sessionmaker

EVIDENCE_ID = re.compile(r"E-[A-Za-z0-9]+-[A-Za-z0-9_]+-[0-9a-f]{8}")


def _births(mode: str) -> list[BirthProfileInput]:
    first = BirthProfileInput(
        birth_date="1990-01-01",
        calendar="solar",
        birth_time=time(9, 0),
        gender_for_daewoon="female",
        longitude=127.0,
    )
    if mode == "individual":
        return [first]
    second = BirthProfileInput(
        birth_date="1992-05-15",
        calendar="solar",
        birth_time=None,
        gender_for_daewoon="male",
        longitude=127.0,
    )
    return [first, second]


async def _count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def test_individual_complete_without_external_llm(engine: AsyncEngine):
    report_id = await run_deterministic_e2e(engine, "individual", _births("individual"))
    assert isinstance(report_id, uuid.UUID)
    assert await _count(engine, "report_versions") == 1


async def test_couple_complete_without_external_llm(engine: AsyncEngine):
    report_id = await run_deterministic_e2e(engine, "couple", _births("couple"))
    assert isinstance(report_id, uuid.UUID)
    assert await _count(engine, "report_versions") == 1


async def test_invalid_report_leaves_prepared_state(engine: AsyncEngine):
    """An invalid draft stores no report. Per Task 9 semantics the run is marked
    VALIDATION_FAILED (error list + attempt count recorded) rather than staying PREPARED;
    it is never FINALIZED, and a later valid draft can still finalize it."""
    sessionmaker = make_sessionmaker(engine)
    prepared = await AnalysisService(
        sessionmaker, clock=lambda: date(2026, 10, 25)
    ).prepare_analysis("individual", _births("individual"))
    reports = ReportService(sessionmaker)

    result = await reports.finalize_report(
        prepared.analysis_id, invalid_draft(prepared), "e2e-invalid"
    )
    assert result.status == "VALIDATION_FAILED" and result.validation_errors
    assert result.report_id is None
    assert await _count(engine, "report_versions") == 0
    async with engine.connect() as conn:
        status, attempts = (
            await conn.execute(
                text("SELECT status, attempt_count FROM analysis_runs WHERE id = :i"),
                {"i": prepared.analysis_id},
            )
        ).one()
    assert status == "VALIDATION_FAILED" and attempts == 1

    ok = await reports.finalize_report(prepared.analysis_id, valid_draft(prepared), "e2e-valid")
    assert ok.status == "FINALIZED"


async def test_chatgpt_export_has_no_broken_evidence_refs(engine: AsyncEngine):
    for mode in ("individual", "couple"):
        report_id = await run_deterministic_e2e(engine, mode, _births(mode))
        sessionmaker = make_sessionmaker(engine)
        view = await ReportService(sessionmaker).get_report(report_id, format="markdown")
        assert isinstance(view.content, str)
        prepared = await AnalysisService(sessionmaker).get_prepared(view.analysis_id)
        assert prepared is not None
        catalog = {e.id for e in prepared.evidence_catalog}

        _, _, appendix = view.content.partition("## 부록: 인용 근거")
        assert appendix, "markdown has an evidence appendix"
        appendix_ids = set(re.findall(r"^### (E-\S+)$", appendix, flags=re.M))
        referenced = set(EVIDENCE_ID.findall(view.content))
        assert referenced, "markdown cites evidence"
        assert referenced <= catalog, f"{mode}: unknown evidence ids {referenced - catalog}"
        assert referenced <= appendix_ids, f"{mode}: ids missing from appendix"
