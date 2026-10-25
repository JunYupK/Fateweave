import asyncio
import uuid
from datetime import date, time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fateweave.domain.validation import REQUIRED_SECTIONS
from fateweave.models.facts import PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.models.reports import Claim, ReportDraft
from fateweave.services.analysis import AnalysisService
from fateweave.services.reports import (
    MARKDOWN_RENDERER_VERSION,
    FinalizeResult,
    ReportError,
    ReportService,
    render_markdown_v1,
)
from fateweave.storage.db import make_sessionmaker
from fateweave.storage.repository import AnalysisRepository

BADGE = "검증 범위: structured_fact_validation (구조화된 계산 주장만 기계 검증됨)"


def _clock() -> date:
    return date(2026, 10, 25)


def _profile(**kw) -> BirthProfileInput:
    base = dict(
        birth_date="1990-05-15",
        calendar="solar",
        birth_time=time(14, 30),
        gender_for_daewoon="female",
        longitude=127.0,
    )
    base.update(kw)
    return BirthProfileInput(**base)


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
        sections={name: f"{name} 본문" for name in REQUIRED_SECTIONS[prepared.mode]},
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


async def _prepared(engine: AsyncEngine, mode: str = "individual") -> PreparedAnalysis:
    svc = AnalysisService(make_sessionmaker(engine), clock=_clock)
    profiles = (
        [_profile()]
        if mode == "individual"
        else [_profile(), _profile(birth_date="1988-03-02", gender_for_daewoon="male")]
    )
    return await svc.prepare_analysis(mode, profiles)


def _reports(engine: AsyncEngine) -> ReportService:
    return ReportService(make_sessionmaker(engine))


async def _count_reports(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM report_versions"))).scalar_one()


async def _run_row(engine: AsyncEngine, analysis_id: uuid.UUID):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT status, attempt_count, last_validation_errors "
                    "FROM analysis_runs WHERE id = :i"
                ),
                {"i": analysis_id},
            )
        ).one()


async def test_success_creates_version_one(engine: AsyncEngine):
    prepared = await _prepared(engine)
    draft = valid_draft(prepared)
    result = await _reports(engine).finalize_report(prepared.analysis_id, draft, "key-1")

    assert isinstance(result, FinalizeResult)
    assert result.status == "FINALIZED"
    assert result.version == 1 and result.report_id is not None
    assert result.validation_errors == []

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT * FROM report_versions WHERE report_id = :r"),
                {"r": result.report_id},
            )
        ).one()
    assert row.version == 1 and row.analysis_id == prepared.analysis_id
    assert row.idempotency_key == "key-1" and len(row.payload_hash) == 64
    assert row.report_type == "individual"
    assert row.body == draft.model_dump(mode="json")
    assert (row.generated_by, row.prompt_version) == ("claude-test", "prompt-v1")
    assert row.validation["structured_fact_validation"] == "passed"
    assert row.validation["schema_version"] == "report-v1"
    assert row.validation["renderer_version"] == MARKDOWN_RENDERER_VERSION == "md-v1"
    assert row.validation["checked_at"].endswith("+00:00")
    assert BADGE in row.markdown
    assert str(result.report_id) in row.markdown
    assert "1990-05-15" not in row.markdown and "14:30" not in row.markdown

    run = await _run_row(engine, prepared.analysis_id)
    assert run.status == "FINALIZED" and run.last_validation_errors is None


async def test_markdown_is_deterministic_and_ordered(engine: AsyncEngine):
    prepared = await _prepared(engine, "couple")
    sections = {name: f"{name} 본문" for name in reversed(REQUIRED_SECTIONS["couple"])}
    sections["zz_extra"] = "추가 z"
    sections["aa_extra"] = "추가 a"
    draft = valid_draft(prepared, sections=sections)
    rid = uuid.uuid4()
    md = render_markdown_v1(report_id=rid, version=1, draft=draft, prepared=prepared)
    assert md == render_markdown_v1(report_id=rid, version=1, draft=draft, prepared=prepared)

    order = [*REQUIRED_SECTIONS["couple"], "aa_extra", "zz_extra"]
    positions = [md.index(f"{name} 본문" if "extra" not in name else name) for name in order]
    assert positions == sorted(positions)
    for needle in (
        str(rid),
        str(prepared.analysis_id),
        "manse-v1",
        "rules-v1",
        "report-v1",
        "claude-test",
        "prompt-v1",
        BADGE,
        *prepared.missing_data,
        *draft.caveats,
    ):
        assert needle in md
    for claim in draft.claims:
        assert claim.rule_code in md and claim.kind in md
        for eid in claim.evidence_ids:
            ev = next(e for e in prepared.evidence_catalog if e.id == eid)
            assert md.count(eid) >= 2  # cited in the claims list and in the appendix
            assert ev.text_ko in md
            for a in ev.assumptions:
                assert a in md
    assert "1990-05-15" not in md and "1988-03-02" not in md and "14:30" not in md


async def test_failed_validation_has_no_final_report(engine: AsyncEngine):
    prepared = await _prepared(engine)
    result = await _reports(engine).finalize_report(
        prepared.analysis_id, invalid_draft(prepared), "key-1"
    )
    assert result.status == "VALIDATION_FAILED"
    assert result.report_id is None and result.version is None
    assert [e.code for e in result.validation_errors] == ["FACT_MISMATCH"]
    assert await _count_reports(engine) == 0

    run = await _run_row(engine, prepared.analysis_id)
    assert run.status == "VALIDATION_FAILED" and run.attempt_count == 1
    assert [e["code"] for e in run.last_validation_errors] == ["FACT_MISMATCH"]
    stored = str(run.last_validation_errors)
    assert "계산된 사실" not in stored and "본문" not in stored  # no report text persisted


async def test_retry_with_corrected_draft_succeeds(engine: AsyncEngine):
    prepared = await _prepared(engine)
    svc = _reports(engine)
    failed = await svc.finalize_report(prepared.analysis_id, invalid_draft(prepared), "key-1")
    assert failed.status == "VALIDATION_FAILED"
    again = await svc.finalize_report(prepared.analysis_id, invalid_draft(prepared), "key-1")
    assert again.status == "VALIDATION_FAILED"
    assert (await _run_row(engine, prepared.analysis_id)).attempt_count == 2

    ok = await svc.finalize_report(prepared.analysis_id, valid_draft(prepared), "key-1")
    assert ok.status == "FINALIZED" and ok.version == 1
    assert await _count_reports(engine) == 1
    run = await _run_row(engine, prepared.analysis_id)
    assert run.status == "FINALIZED" and run.last_validation_errors is None
    assert run.attempt_count == 2

    # An invalid draft after finalization does not touch the finalized run.
    late = await svc.finalize_report(prepared.analysis_id, invalid_draft(prepared), "key-2")
    assert late.status == "VALIDATION_FAILED"
    run = await _run_row(engine, prepared.analysis_id)
    assert run.status == "FINALIZED" and run.attempt_count == 2
    assert run.last_validation_errors is None


async def test_same_key_replay_returns_existing_report(engine: AsyncEngine):
    prepared = await _prepared(engine)
    svc = _reports(engine)
    first = await svc.finalize_report(prepared.analysis_id, valid_draft(prepared), "key-1")
    second = await svc.finalize_report(prepared.analysis_id, valid_draft(prepared), "key-1")
    assert second.status == "FINALIZED"
    assert (second.report_id, second.version) == (first.report_id, first.version)
    assert await _count_reports(engine) == 1


async def test_same_key_different_payload_conflicts(engine: AsyncEngine):
    prepared = await _prepared(engine)
    svc = _reports(engine)
    await svc.finalize_report(prepared.analysis_id, valid_draft(prepared), "key-1")
    changed = valid_draft(prepared, caveats=["다른 주의사항"])
    result = await svc.finalize_report(prepared.analysis_id, changed, "key-1")
    assert result.status == "IDEMPOTENCY_CONFLICT"
    assert result.report_id is None and result.validation_errors == []
    assert await _count_reports(engine) == 1


async def test_other_key_after_finalize_is_report_conflict(engine: AsyncEngine):
    prepared = await _prepared(engine)
    svc = _reports(engine)
    await svc.finalize_report(prepared.analysis_id, valid_draft(prepared), "key-1")
    result = await svc.finalize_report(prepared.analysis_id, valid_draft(prepared), "key-2")
    assert result.status == "REPORT_CONFLICT" and result.report_id is None
    assert await _count_reports(engine) == 1


async def test_parallel_finalize_single_winner(engine: AsyncEngine):
    prepared = await _prepared(engine)
    svc = _reports(engine)
    draft = valid_draft(prepared)
    keys = ["same-key"] * 4 + [f"other-{i}" for i in range(4)]
    results = await asyncio.gather(
        *(svc.finalize_report(prepared.analysis_id, draft, k) for k in keys)
    )

    assert await _count_reports(engine) == 1
    async with engine.connect() as conn:
        winner_key = (
            await conn.execute(text("SELECT idempotency_key FROM report_versions"))
        ).scalar_one()
    finalized = {r.report_id for r in results if r.status == "FINALIZED"}
    assert len(finalized) == 1
    for key, r in zip(keys, results, strict=True):
        if key == winner_key:
            assert r.status == "FINALIZED" and r.version == 1
        else:
            assert r.status == "REPORT_CONFLICT" and r.report_id is None


async def test_service_storage_failure_never_returns_finalized(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    prepared = await _prepared(engine)

    async def failing_commit(self):
        raise OperationalError("COMMIT", {}, ConnectionError("connection lost"))

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    with pytest.raises(ReportError) as exc:
        await _reports(engine).finalize_report(prepared.analysis_id, valid_draft(prepared), "k")
    assert exc.value.code == "STORAGE_UNAVAILABLE"
    monkeypatch.undo()

    assert await _count_reports(engine) == 0
    assert (await _run_row(engine, prepared.analysis_id)).status == "PREPARED"


async def test_insert_race_is_resolved_once_without_duplicate(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    prepared = await _prepared(engine)
    real_insert = AnalysisRepository.add_report_version
    calls = 0

    async def racing_insert(self, **kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        return await real_insert(self, **kw)

    monkeypatch.setattr(AnalysisRepository, "add_report_version", racing_insert)
    result = await _reports(engine).finalize_report(
        prepared.analysis_id, valid_draft(prepared), "k"
    )
    assert result.status == "FINALIZED" and calls == 2
    assert await _count_reports(engine) == 1


async def test_unknown_analysis_raises_not_found(engine: AsyncEngine):
    prepared = await _prepared(engine)
    with pytest.raises(ReportError) as exc:
        await _reports(engine).finalize_report(uuid.uuid4(), valid_draft(prepared), "k")
    assert exc.value.code == "ANALYSIS_NOT_FOUND"


@pytest.mark.parametrize("key", ["", "x" * 129, "has space", "슬래시/", "a\nb"])
async def test_bad_idempotency_key_is_invalid_input(engine: AsyncEngine, key: str):
    prepared = await _prepared(engine)
    with pytest.raises(ReportError) as exc:
        await _reports(engine).finalize_report(prepared.analysis_id, valid_draft(prepared), key)
    assert exc.value.code == "INVALID_INPUT"
    assert await _count_reports(engine) == 0
