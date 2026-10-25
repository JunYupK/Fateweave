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
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fateweave.domain.rules import evidence_digest
from fateweave.domain.validation import PROBABILITY_PATTERNS, REQUIRED_SECTIONS, validate_report
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

    def __init__(
        self, code: str, message: str, validation_errors: list[ValidationError] | None = None
    ):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.validation_errors = validation_errors or []


class FinalizeResult(BaseModel):
    status: Literal["FINALIZED", "VALIDATION_FAILED", "REPORT_CONFLICT", "IDEMPOTENCY_CONFLICT"]
    report_id: uuid.UUID | None = None
    version: int | None = None
    validation_errors: list[ValidationError] = []


MAX_ALTERNATIVE_CHARS = 20_000
MAX_SCHOOL_CHARS = 100
MAX_LIST_LIMIT = 50
_ALTERNATIVES_END = "_(대안 해석 끝 — 위 인용문은 기준 리포트가 아님)_"
_HISTORY_HEADING = "## 버전 이력"
_ALTERNATIVES_HEADING = "## 대안 해석 (기준 리포트와 별도)"


class AlternativeView(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    report_version: int
    school: str
    evidence_refs: list[str]
    created_at: datetime


class AlternativeDetail(BaseModel):
    id: uuid.UUID
    school: str
    report_version: int
    created_at: datetime
    evidence_refs: list[str]
    content: str


class ReportView(BaseModel):
    report_id: uuid.UUID
    version: int
    format: Literal["markdown", "json"]
    content: str | dict[str, Any]
    report_type: str
    analysis_id: uuid.UUID
    created_at: datetime
    manse_version: str
    rule_version: str
    report_schema_version: str
    evidence_digest: str
    validation: dict[str, Any]
    correction_reason: str | None = None
    available_versions: list[int]
    alternatives: list[AlternativeDetail]


class ReportSummary(BaseModel):
    report_id: uuid.UUID
    latest_version: int
    report_type: str
    aliases: list[str | None]
    created_at: datetime


def payload_hash(draft: ReportDraft) -> str:
    canonical = json.dumps(
        draft.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- 없음"]


def render_markdown_v1(
    *,
    report_id: uuid.UUID,
    version: int,
    draft: ReportDraft,
    prepared: PreparedAnalysis,
    correction: tuple[int, str] | None = None,
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
    if correction is not None:
        previous, reason = correction
        note = " ".join(reason.split())
        lines.append(f"- 정정: 버전 {previous}을(를) 대체하는 정정본 — 사유: {note}")
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

    # ---- retrieval -------------------------------------------------------------------------

    async def get_report(
        self,
        report_id: uuid.UUID,
        version: int | None = None,
        format: Literal["markdown", "json"] = "markdown",
    ) -> ReportView:
        if format not in ("markdown", "json"):
            raise ReportError("INVALID_INPUT", "format must be 'markdown' or 'json'")
        if version is not None and (
            isinstance(version, bool) or not isinstance(version, int) or version < 1
        ):
            raise ReportError("INVALID_INPUT", "version must be a positive integer")
        try:
            async with self._sessionmaker() as session:
                repo = AnalysisRepository(session)
                row = (
                    await repo.get_latest_report(report_id)
                    if version is None
                    else await repo.get_report(report_id, version)
                )
                if row is None:
                    raise ReportError("REPORT_NOT_FOUND", "no such report or version")
                versions = await repo.list_report_versions(report_id)
                alternatives = await repo.list_alternatives(report_id)
                run = await repo.get_run(row.analysis_id)
        except (SQLAlchemyError, OSError) as exc:
            log.error("loading report failed: %s", type(exc).__name__)
            raise ReportError("STORAGE_UNAVAILABLE", "the report could not be loaded") from exc
        if run is None:
            raise ReportError("STORAGE_UNAVAILABLE", "the report's analysis is missing")
        try:
            prepared = prepared_from_row(run)
        except AnalysisError as exc:
            raise ReportError(exc.code, exc.message) from exc

        details = [
            AlternativeDetail(
                id=a.id,
                school=a.school,
                report_version=a.report_version,
                created_at=a.created_at,
                evidence_refs=list(a.evidence_refs),
                content=a.content,
            )
            for a in alternatives
        ]
        content: str | dict[str, Any]
        if format == "json":
            content = row.body
        else:
            content = _compose_markdown(row.markdown, versions, details)
        return ReportView(
            report_id=report_id,
            version=row.version,
            format=format,
            content=content,
            report_type=row.report_type,
            analysis_id=row.analysis_id,
            created_at=row.created_at,
            manse_version=prepared.policy_version,
            rule_version=prepared.rule_version,
            report_schema_version=row.validation.get("schema_version", "report-v1"),
            evidence_digest=evidence_digest(prepared.evidence_catalog),
            validation=row.validation,
            correction_reason=row.correction_reason,
            available_versions=[v.version for v in versions],
            alternatives=details,
        )

    async def list_reports(
        self, mode: Literal["individual", "couple"] | None = None, limit: int = 20
    ) -> list[ReportSummary]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ReportError("INVALID_INPUT", f"limit must be 1..{MAX_LIST_LIMIT}")
        if not 1 <= limit <= MAX_LIST_LIMIT:
            raise ReportError("INVALID_INPUT", f"limit must be 1..{MAX_LIST_LIMIT}")
        if mode not in (None, "individual", "couple"):
            raise ReportError("INVALID_INPUT", "mode must be 'individual' or 'couple'")
        try:
            async with self._sessionmaker() as session:
                repo = AnalysisRepository(session)
                rows = await repo.list_reports(limit=limit, mode=mode)
                participants: dict[uuid.UUID, list[uuid.UUID]] = {}
                for row in rows:
                    run = await repo.get_run(row.analysis_id)
                    participants[row.analysis_id] = list(run.participant_ids) if run else []
                aliases = await repo.participant_aliases(participants)
        except (SQLAlchemyError, OSError) as exc:
            log.error("listing reports failed: %s", type(exc).__name__)
            raise ReportError("STORAGE_UNAVAILABLE", "reports could not be listed") from exc
        return [
            ReportSummary(
                report_id=r.report_id,
                latest_version=r.version,
                report_type=r.report_type,
                aliases=aliases.get(r.analysis_id, []),
                created_at=r.created_at,
            )
            for r in rows
        ]

    # ---- alternatives and corrections --------------------------------------------------------

    async def add_alternative_interpretation(
        self, report_id: uuid.UUID, school: str, content: str, evidence_refs: list[str]
    ) -> AlternativeView:
        if not isinstance(school, str) or not school.strip():
            raise ReportError("INVALID_INPUT", "school must not be blank")
        if len(school.strip().splitlines()) != 1 or len(school.strip()) > MAX_SCHOOL_CHARS:
            raise ReportError(
                "INVALID_INPUT", f"school must be a single line of at most {MAX_SCHOOL_CHARS} chars"
            )
        if not isinstance(content, str) or not content.strip():
            raise ReportError("INVALID_INPUT", "content must not be blank")
        if len(content) > MAX_ALTERNATIVE_CHARS:
            raise ReportError(
                "REPORT_TOO_LARGE", f"content is limited to {MAX_ALTERNATIVE_CHARS} characters"
            )
        if not isinstance(evidence_refs, list) or not all(
            isinstance(r, str) for r in evidence_refs
        ):
            raise ReportError("INVALID_INPUT", "evidence_refs must be a list of strings")
        if any(p.search(t) for p in PROBABILITY_PATTERNS for t in (school, content)):
            raise ReportError("UNSUPPORTED_CLAIM", "unsupported marriage probability expression")

        school = school.strip()
        try:
            async with self._sessionmaker() as session:
                repo = AnalysisRepository(session)
                first = await repo.get_latest_report(report_id)
                if first is None:
                    raise ReportError("REPORT_NOT_FOUND", "no such report")
                run = await repo.lock_run(first.analysis_id)
                if run is None:
                    raise ReportError("STORAGE_UNAVAILABLE", "the report's analysis is missing")
                # Re-read under the lock so the alternative attaches to the true latest version.
                latest = await repo.get_latest_report(report_id)
                if latest is None:
                    raise ReportError("REPORT_NOT_FOUND", "no such report")
                try:
                    prepared = prepared_from_row(run)
                except AnalysisError as exc:
                    raise ReportError(exc.code, exc.message) from exc
                known = {ev.id for ev in prepared.evidence_catalog}
                unknown = [r for r in evidence_refs if r not in known]
                if unknown:
                    raise ReportError(
                        "UNKNOWN_EVIDENCE", f"{len(unknown)} evidence ref(s) not in the catalog"
                    )
                alt_id = await repo.add_alternative(
                    report_id=report_id,
                    report_version=latest.version,
                    school=school,
                    content=content,
                    evidence_refs=list(evidence_refs),
                )
                created = next(
                    a.created_at for a in await repo.list_alternatives(report_id) if a.id == alt_id
                )
                await session.commit()
        except (SQLAlchemyError, OSError) as exc:
            log.error("saving alternative failed: %s", type(exc).__name__)
            raise ReportError("STORAGE_UNAVAILABLE", "the alternative could not be saved") from exc
        return AlternativeView(
            id=alt_id,
            report_id=report_id,
            report_version=latest.version,
            school=school,
            evidence_refs=list(evidence_refs),
            created_at=created,
        )

    async def create_correction(
        self, report_id: uuid.UUID, corrected: ReportDraft, reason: str
    ) -> ReportView:
        """Admin-only: append version max+1; earlier versions stay untouched."""
        if not isinstance(reason, str) or not reason.strip():
            raise ReportError("INVALID_INPUT", "reason must not be blank")
        reason = reason.strip()
        digest = payload_hash(corrected)
        try:
            async with self._sessionmaker() as session:
                repo = AnalysisRepository(session)
                first = await repo.get_latest_report(report_id)
                if first is None:
                    raise ReportError("REPORT_NOT_FOUND", "no such report")
                run = await repo.lock_run(first.analysis_id)
                if run is None:
                    raise ReportError("STORAGE_UNAVAILABLE", "the report's analysis is missing")
                try:
                    prepared = prepared_from_row(run)
                except AnalysisError as exc:
                    raise ReportError(exc.code, exc.message) from exc
                result = validate_report(corrected, prepared)
                if not result.valid:
                    raise ReportError(
                        "VALIDATION_FAILED", "the correction failed validation", result.errors
                    )
                latest = await repo.get_latest_report(report_id)  # under the run lock
                if latest is None:
                    raise ReportError("REPORT_NOT_FOUND", "no such report")
                previous, version = latest.version, latest.version + 1
                await repo.add_report_version(
                    report_id=report_id,
                    version=version,
                    analysis_id=latest.analysis_id,
                    idempotency_key=None,
                    payload_hash=digest,
                    report_type=corrected.report_type,
                    body=corrected.model_dump(mode="json"),
                    markdown=render_markdown_v1(
                        report_id=report_id,
                        version=version,
                        draft=corrected,
                        prepared=prepared,
                        correction=(previous, reason),
                    ),
                    generated_by=corrected.generated_by,
                    prompt_version=corrected.prompt_version,
                    validation={
                        "structured_fact_validation": "passed",
                        "schema_version": corrected.schema_version,
                        "renderer_version": MARKDOWN_RENDERER_VERSION,
                        "checked_at": datetime.now(UTC).isoformat(),
                        "errors": [],
                        "corrects_version": previous,
                    },
                    correction_reason=reason,
                )
                await session.commit()
        except (SQLAlchemyError, OSError) as exc:
            log.error("saving correction failed: %s", type(exc).__name__)
            raise ReportError("STORAGE_UNAVAILABLE", "the correction could not be saved") from exc
        return await self.get_report(report_id, version)


def _compose_markdown(
    stored: str, versions: list[Any], alternatives: list[AlternativeDetail]
) -> str:
    """Stored canonical Markdown plus clearly separated, non-canonical history/alternatives."""
    out = [stored.rstrip("\n"), "", "---", "", _HISTORY_HEADING, ""]
    out += ["(아래 블록은 정본(canonical) 리포트의 일부가 아닙니다.)", ""]
    for v in versions:
        line = f"- 버전 {v.version} — {v.created_at.isoformat()}"
        if v.correction_reason:
            line += f" — 정정 사유: {' '.join(v.correction_reason.split())}"
        out.append(line)
    out += ["", _ALTERNATIVES_HEADING, ""]
    out.append("(아래 블록은 정본(canonical) 리포트의 일부가 아니며 기계 검증 대상이 아닙니다.)")
    if not alternatives:
        out += ["", "- 없음"]
    for i, a in enumerate(alternatives, start=1):
        refs = ", ".join(a.evidence_refs) or "없음"
        school = " ".join(a.school.split()).replace("\\", "\\\\")
        quoted = [f"> {line}" if line.strip() else ">" for line in a.content.strip().splitlines()]
        out += [
            "",
            f"### 대안 {i}: {school}",
            "",
            f"- 기준 버전: {a.report_version}",
            f"- 근거: {refs}",
            f"- 등록: {a.created_at.isoformat()}",
            "",
            *quoted,
        ]
    out += ["", _ALTERNATIVES_END]
    return "\n".join(out) + "\n"
