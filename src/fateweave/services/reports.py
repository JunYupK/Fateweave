"""Finalize a validated ReportDraft into the immutable canonical report v1 (atomic, idempotent).

A FINALIZED result is returned only after the commit succeeded. Draft text, Markdown and birth
data are never logged.
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fateweave.domain.validation import REQUIRED_SECTIONS, validate_report
from fateweave.models.facts import PreparedAnalysis
from fateweave.models.reports import ReportDraft, ValidationError
from fateweave.services.analysis import AnalysisError, prepared_from_row
from fateweave.storage.repository import AnalysisRepository

log = logging.getLogger(__name__)

MARKDOWN_RENDERER_VERSION = "md-v1"
VALIDATION_BADGE = "검증 범위: structured_fact_validation (구조화된 계산 주장만 기계 검증됨)"
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{1,128}")

_TITLES = {"individual": "개인 결혼 사주 리포트", "couple": "커플 궁합 리포트"}
_SECTION_LABELS = {
    "summary": "요약",
    "personality": "성향",
    "relationship_style": "연애·관계 스타일",
    "spouse_profile": "배우자상",
    "married_life": "결혼 생활",
    "marriage_timing": "결혼 시기",
    "evidence_explanation": "근거 설명",
    "limitations": "한계",
    "marital_compatibility": "부부 궁합",
    "relationship_potential": "관계 발전 가능성",
}


class ReportError(Exception):
    """Service failure with a stable `code`; `message` never contains report text or birth data."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class FinalizeResult(BaseModel):
    status: Literal["FINALIZED", "VALIDATION_FAILED", "REPORT_CONFLICT", "IDEMPOTENCY_CONFLICT"]
    report_id: uuid.UUID | None = None
    version: int | None = None
    validation_errors: list[ValidationError] = []


def payload_hash(draft: ReportDraft) -> str:
    canonical = json.dumps(
        draft.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- 없음"]


def render_markdown_v1(
    *, report_id: uuid.UUID, version: int, draft: ReportDraft, prepared: PreparedAnalysis
) -> str:
    """Deterministic Markdown for a validated draft (renderer `md-v1`); no birth dates/times."""
    required = REQUIRED_SECTIONS[draft.report_type]
    extras = sorted(k for k in draft.sections if k not in required)
    lines = [
        f"# {_TITLES[draft.report_type]}",
        "",
        f"- report_id: {report_id}",
        f"- version: {version}",
        f"- analysis_id: {prepared.analysis_id}",
        f"- report_type: {draft.report_type}",
        f"- manse_version: {prepared.policy_version}",
        f"- rule_version: {prepared.rule_version}",
        f"- report_schema_version: {draft.schema_version}",
        f"- renderer_version: {MARKDOWN_RENDERER_VERSION}",
        f"- generated_by: {draft.generated_by}",
        f"- prompt_version: {draft.prompt_version}",
        f"- {VALIDATION_BADGE}",
    ]
    for key in [*required, *extras]:
        if key not in draft.sections:
            continue
        label = _SECTION_LABELS.get(key)
        heading = f"{label} ({key})" if label else key
        lines += ["", f"## {heading}", "", draft.sections[key].strip()]

    lines += ["", "## 주장 목록 (claims)", ""]
    if draft.claims:
        for i, claim in enumerate(draft.claims, start=1):
            ids = ", ".join(claim.evidence_ids) or "없음"
            lines.append(f"{i}. [{claim.kind}] {claim.rule_code}: {claim.statement.strip()}")
            lines.append(f"   - 근거: {ids}")
    else:
        lines.append("- 없음")

    lines += ["", "## 주의사항 (caveats)", "", *_bullets(draft.caveats)]
    lines += ["", "## 누락·제약 데이터 (missing_data)", "", *_bullets(prepared.missing_data)]

    catalog = {ev.id: ev for ev in prepared.evidence_catalog}
    cited = sorted({eid for c in draft.claims for eid in c.evidence_ids if eid in catalog})
    lines += ["", "## 부록: 인용 근거 (evidence appendix)"]
    if not cited:
        lines += ["", "- 없음"]
    for eid in cited:
        ev = catalog[eid]
        lines += ["", f"### {ev.id}", "", f"- kind: {ev.kind}", f"- rule_code: {ev.rule_code}"]
        lines.append(f"- text_ko: {ev.text_ko}")
        lines.append("- assumptions:")
        lines += [f"  - {a}" for a in ev.assumptions] or ["  - 없음"]
    return "\n".join(lines) + "\n"


class ReportService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def finalize_report(
        self, analysis_id: uuid.UUID, draft: ReportDraft, idempotency_key: str
    ) -> FinalizeResult:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ReportError(
                "INVALID_INPUT", "idempotency_key must be 1..128 chars of [A-Za-z0-9._:-]"
            )
        digest = payload_hash(draft)
        prepared = await self._load(analysis_id)
        result = validate_report(draft, prepared)

        try:
            if not result.valid:
                await self._record_failure(analysis_id, result.errors)
                return FinalizeResult(status="VALIDATION_FAILED", validation_errors=result.errors)
            for attempt in (1, 2):
                try:
                    return await self._resolve_and_insert(prepared, draft, idempotency_key, digest)
                except IntegrityError:
                    log.warning(
                        "finalize insert race for analysis %s (attempt %d)", analysis_id, attempt
                    )
            raise ReportError("STORAGE_UNAVAILABLE", "the report could not be saved")
        except (SQLAlchemyError, OSError) as exc:
            log.error("finalizing report failed: %s", type(exc).__name__)
            raise ReportError("STORAGE_UNAVAILABLE", "the report could not be saved") from exc

    async def _load(self, analysis_id: uuid.UUID) -> PreparedAnalysis:
        try:
            async with self._sessionmaker() as session:
                run = await AnalysisRepository(session).get_run(analysis_id)
        except (SQLAlchemyError, OSError) as exc:
            log.error("loading analysis failed: %s", type(exc).__name__)
            raise ReportError("STORAGE_UNAVAILABLE", "the analysis could not be loaded") from exc
        if run is None:
            raise ReportError("ANALYSIS_NOT_FOUND", "no prepared analysis with this id")
        try:
            return prepared_from_row(run)
        except AnalysisError as exc:
            raise ReportError(exc.code, exc.message) from exc

    async def _record_failure(self, analysis_id: uuid.UUID, errors: list[ValidationError]) -> None:
        async with self._sessionmaker() as session:
            repo = AnalysisRepository(session)
            run = await repo.lock_run(analysis_id)
            if run is not None and run.status != "FINALIZED":
                await repo.update_run_status(
                    analysis_id,
                    "VALIDATION_FAILED",
                    last_validation_errors=[e.model_dump(mode="json") for e in errors],
                    increment_attempt=True,
                )
            await session.commit()

    async def _resolve_and_insert(
        self, prepared: PreparedAnalysis, draft: ReportDraft, key: str, digest: str
    ) -> FinalizeResult:
        analysis_id = prepared.analysis_id
        async with self._sessionmaker() as session:
            repo = AnalysisRepository(session)
            run = await repo.lock_run(analysis_id)
            if run is None:
                raise ReportError("ANALYSIS_NOT_FOUND", "no prepared analysis with this id")
            existing = await repo.get_report_by_idempotency_key(analysis_id, key)
            if existing is not None:
                if existing.payload_hash == digest:
                    return FinalizeResult(
                        status="FINALIZED", report_id=existing.report_id, version=existing.version
                    )
                return FinalizeResult(status="IDEMPOTENCY_CONFLICT")
            if run.status == "FINALIZED":
                return FinalizeResult(status="REPORT_CONFLICT")

            report_id, version = uuid.uuid4(), 1
            await repo.add_report_version(
                report_id=report_id,
                version=version,
                analysis_id=analysis_id,
                idempotency_key=key,
                payload_hash=digest,
                report_type=draft.report_type,
                body=draft.model_dump(mode="json"),
                markdown=render_markdown_v1(
                    report_id=report_id, version=version, draft=draft, prepared=prepared
                ),
                generated_by=draft.generated_by,
                prompt_version=draft.prompt_version,
                validation={
                    "structured_fact_validation": "passed",
                    "schema_version": draft.schema_version,
                    "renderer_version": MARKDOWN_RENDERER_VERSION,
                    "checked_at": datetime.now(UTC).isoformat(),
                    "errors": [],
                },
            )
            await repo.update_run_status(analysis_id, "FINALIZED", last_validation_errors=None)
            await session.commit()
        return FinalizeResult(status="FINALIZED", report_id=report_id, version=version)
