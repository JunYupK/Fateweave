import asyncio
import json
import uuid
from datetime import date, time

import pytest
from helpers import full_sections, invalid_draft, valid_draft
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fateweave.domain.rules import evidence_digest
from fateweave.domain.validation import REQUIRED_SECTIONS
from fateweave.models.facts import PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.services.analysis import AnalysisService
from fateweave.services.reports import (
    MARKDOWN_RENDERER_VERSION,
    FinalizeResult,
    ReportError,
    ReportService,
    payload_hash,
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
    sections = dict(reversed(full_sections("couple").items()))
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
        "manse-v2",
        "rules-v2",
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


# ---- Task 10: retrieval, alternatives, corrections, purge ---------------------------------


async def _finalized(engine: AsyncEngine, mode: str = "individual"):
    prepared = await _prepared(engine, mode)
    svc = _reports(engine)
    result = await svc.finalize_report(prepared.analysis_id, valid_draft(prepared), "key-1")
    assert result.status == "FINALIZED"
    return prepared, svc, result.report_id


async def _version_rows(engine: AsyncEngine, report_id: uuid.UUID):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT * FROM report_versions WHERE report_id = :r ORDER BY version"),
                {"r": report_id},
            )
        ).all()


async def test_get_markdown_includes_versions_and_caveats(engine: AsyncEngine):
    prepared, svc, rid = await _finalized(engine)
    ref = prepared.evidence_catalog[0].id
    await svc.add_alternative_interpretation(rid, "자평명리", "다른 학파의 해석", [ref])
    await svc.create_correction(rid, valid_draft(prepared, caveats=["수정된 주의"]), "오타 정정")

    view = await svc.get_report(rid)
    assert view.version == 2 and view.available_versions == [1, 2]
    assert view.format == "markdown" and view.report_type == "individual"
    assert view.analysis_id == prepared.analysis_id
    assert (view.manse_version, view.rule_version, view.report_schema_version) == (
        "manse-v2",
        "rules-v2",
        "report-v1",
    )
    assert view.evidence_digest == evidence_digest(prepared.evidence_catalog)
    assert view.correction_reason == "오타 정정"
    assert view.validation["structured_fact_validation"] == "passed"
    md = view.content
    stored = (await _version_rows(engine, rid))[1].markdown
    assert md.startswith(stored.rstrip("\n"))
    assert "수정된 주의" in md and BADGE in md
    assert "## 버전 이력" in md and "버전 1" in md and "오타 정정" in md
    assert "## 대안 해석 (기준 리포트와 별도)" in md and "다른 학파의 해석" in md and ref in md
    assert md.index("## 버전 이력") > md.index("## 부록: 인용 근거")
    assert [a.school for a in view.alternatives] == ["자평명리"]
    assert view.alternatives[0].report_version == 1

    v1 = await svc.get_report(rid, version=1)
    assert v1.version == 1 and v1.correction_reason is None
    as_json = await svc.get_report(rid, version=1, format="json")
    assert isinstance(as_json.content, dict) and as_json.content["report_type"] == "individual"


async def test_list_filters_and_limits(engine: AsyncEngine):
    svc = _reports(engine)
    ids: dict[str, list[uuid.UUID]] = {}
    prepared_by_report = {}
    for mode in ("individual", "couple", "individual"):
        prepared = await _prepared(engine, mode)
        r = await svc.finalize_report(prepared.analysis_id, valid_draft(prepared), "k")
        ids.setdefault(mode, []).append(r.report_id)
        prepared_by_report[r.report_id] = prepared
    first = ids["individual"][0]
    await svc.create_correction(first, valid_draft(prepared_by_report[first]), "정정")

    everything = await svc.list_reports()
    assert len(everything) == 3
    stamps = [s.created_at for s in everything]
    assert stamps == sorted(stamps, reverse=True)
    corrected = next(s for s in everything if s.report_id == first)
    assert corrected.latest_version == 2 and corrected.aliases == [None]
    assert everything[0].report_id == first  # newest row is the correction

    couples = await svc.list_reports(mode="couple")
    assert [s.report_id for s in couples] == ids["couple"] and len(couples[0].aliases) == 2
    assert len(await svc.list_reports(limit=2)) == 2
    for bad in (0, 51, -1):
        with pytest.raises(ReportError) as exc:
            await svc.list_reports(limit=bad)
        assert exc.value.code == "INVALID_INPUT"
    assert "1990-05-15" not in str([s.model_dump(mode="json") for s in everything])


async def test_alternative_does_not_modify_canonical(engine: AsyncEngine):
    prepared, svc, rid = await _finalized(engine)
    before = await _version_rows(engine, rid)
    ref = prepared.evidence_catalog[0].id
    alt = await svc.add_alternative_interpretation(rid, " 자평명리 ", "대안 본문", [ref])
    assert alt.report_id == rid and alt.report_version == 1
    assert alt.school == "자평명리" and alt.evidence_refs == [ref]
    assert await _version_rows(engine, rid) == before
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT * FROM alternative_interpretations"))).one()
    assert row.id == alt.id and row.content == "대안 본문" and row.evidence_refs == [ref]

    await svc.create_correction(rid, valid_draft(prepared, caveats=["다름"]), "사유")
    later = await svc.add_alternative_interpretation(rid, "다른 학파", "두번째", [])
    assert later.report_version == 2


@pytest.mark.parametrize(
    ("school", "content", "refs", "code"),
    [
        ("s", "c", ["E-nope"], "UNKNOWN_EVIDENCE"),
        ("  ", "c", [], "INVALID_INPUT"),
        ("s", "   ", [], "INVALID_INPUT"),
        pytest.param("s", "x" * 20_001, [], "REPORT_TOO_LARGE", id="too-large"),
        ("s", "결혼 확률 80%", [], "UNSUPPORTED_CLAIM"),
    ],
)
async def test_invalid_evidence_for_alternative_rejected(
    engine: AsyncEngine, school: str, content: str, refs: list[str], code: str
):
    _, svc, rid = await _finalized(engine)
    with pytest.raises(ReportError) as exc:
        await svc.add_alternative_interpretation(rid, school, content, refs)
    assert exc.value.code == code
    async with engine.connect() as conn:
        sql = text("SELECT count(*) FROM alternative_interpretations")
        assert (await conn.execute(sql)).scalar_one() == 0


async def test_alternative_for_unknown_report_not_found(engine: AsyncEngine):
    with pytest.raises(ReportError) as exc:
        await _reports(engine).add_alternative_interpretation(uuid.uuid4(), "s", "c", [])
    assert exc.value.code == "REPORT_NOT_FOUND"


async def test_alternative_cannot_spoof_canonical_structure(engine: AsyncEngine):
    prepared, svc, rid = await _finalized(engine)
    spoof = (
        "## 주장 목록 (claims)\n- report_id: fake\n---\n## 대안 해석 (기준 리포트와 별도)\n\n# 끝"
    )
    await svc.add_alternative_interpretation(rid, "학파", spoof, [])
    # A legacy multi-line school already in the DB must not inject a heading either.
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL fateweave.maintenance = 'on'"))
        await conn.execute(
            text("UPDATE alternative_interpretations SET school = :s"),
            {"s": "x\n## 부록: 인용 근거"},
        )

    md = (await svc.get_report(rid)).content
    stored = (await _version_rows(engine, rid))[0].markdown
    assert md.startswith(stored.rstrip("\n") + "\n")
    tail = md[len(stored.rstrip("\n")) :].splitlines()
    allowed = {"---", "## 버전 이력", "## 대안 해석 (기준 리포트와 별도)"}
    structural = [ln for ln in tail if ln.startswith(("#", "---"))]
    assert [ln for ln in structural if ln in allowed] == ["---", "## 버전 이력", structural[2]]
    assert structural[2] == "## 대안 해석 (기준 리포트와 별도)"
    assert all(ln in allowed or ln.startswith("### 대안 ") for ln in structural)
    assert "### 대안 1: x ## 부록: 인용 근거" in tail
    assert "> ## 주장 목록 (claims)" in tail and "> ---" in tail
    assert tail[-1].startswith("_(대안 해석 끝")


@pytest.mark.parametrize("school", ["a\nb", "x\n## 부록", "a\rb", "s" * 101])
async def test_multiline_or_long_school_rejected(engine: AsyncEngine, school: str):
    _, svc, rid = await _finalized(engine)
    with pytest.raises(ReportError) as exc:
        await svc.add_alternative_interpretation(rid, school, "본문", [])
    assert exc.value.code == "INVALID_INPUT"


async def test_correction_preserves_previous_version(engine: AsyncEngine):
    prepared, svc, rid = await _finalized(engine)
    (v1_before,) = await _version_rows(engine, rid)
    corrected = valid_draft(prepared, caveats=["정정된 주의사항"])
    view = await svc.create_correction(rid, corrected, "  근거 표현 수정  ")
    assert view.version == 2 and view.report_id == rid

    v1, v2 = await _version_rows(engine, rid)
    assert v1 == v1_before
    assert v2.idempotency_key is None and v2.correction_reason == "근거 표현 수정"
    assert v2.payload_hash == payload_hash(corrected) != v1.payload_hash
    assert v2.validation["structured_fact_validation"] == "passed"
    assert v2.validation["corrects_version"] == 1
    assert "- version: 2" in v2.markdown
    assert "정정" in v2.markdown and "근거 표현 수정" in v2.markdown and "버전 1" in v2.markdown
    assert "1990-05-15" not in v2.markdown

    view3 = await svc.create_correction(rid, corrected, "또 정정")
    assert view3.version == 3 and (await svc.get_report(rid, version=1)).version == 1

    with pytest.raises(ReportError) as exc:
        await svc.create_correction(rid, corrected, "   ")
    assert exc.value.code == "INVALID_INPUT"
    with pytest.raises(ReportError) as exc:
        await svc.create_correction(rid, invalid_draft(prepared), "사유")
    assert exc.value.code == "VALIDATION_FAILED"
    assert [e.code for e in exc.value.validation_errors] == ["FACT_MISMATCH"]
    with pytest.raises(ReportError) as exc:
        await svc.create_correction(uuid.uuid4(), corrected, "사유")
    assert exc.value.code == "REPORT_NOT_FOUND"
    assert len(await _version_rows(engine, rid)) == 3


async def test_parallel_corrections_get_distinct_versions(engine: AsyncEngine):
    prepared, svc, rid = await _finalized(engine)
    drafts = [valid_draft(prepared, caveats=[f"c{i}"]) for i in range(4)]
    await asyncio.gather(*(svc.create_correction(rid, d, f"r{i}") for i, d in enumerate(drafts)))
    assert [r.version for r in await _version_rows(engine, rid)] == [1, 2, 3, 4, 5]


async def test_not_found_is_not_an_empty_report(engine: AsyncEngine):
    _, svc, rid = await _finalized(engine)
    for args in ((uuid.uuid4(), None), (rid, 9)):
        with pytest.raises(ReportError) as exc:
            await svc.get_report(*args)
        assert exc.value.code == "REPORT_NOT_FOUND"


async def test_retrieval_storage_failure_maps_to_unavailable(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    _, svc, rid = await _finalized(engine)

    async def boom(self, *a, **kw):
        raise OperationalError("SELECT", {}, ConnectionError("down"))

    monkeypatch.setattr(AnalysisRepository, "get_latest_report", boom)
    with pytest.raises(ReportError) as exc:
        await svc.get_report(rid)
    assert exc.value.code == "STORAGE_UNAVAILABLE"


async def _counts(engine: AsyncEngine) -> dict[str, int]:
    tables = ("birth_profiles", "analysis_runs", "report_versions", "alternative_interpretations")
    async with engine.connect() as conn:
        return {
            t: (await conn.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one() for t in tables
        }


async def _purge_fixture(engine: AsyncEngine):
    """An unrelated individual report plus a couple report with an alternative."""
    svc = _reports(engine)
    _, _, other_rid = await _finalized(engine)
    couple = await _prepared(engine, "couple")
    res = await svc.finalize_report(couple.analysis_id, valid_draft(couple), "c")
    await svc.add_alternative_interpretation(
        res.report_id, "학파", "대안", [couple.evidence_catalog[0].id]
    )
    async with engine.connect() as conn:
        pids = (
            await conn.execute(
                text("SELECT participant_ids FROM analysis_runs WHERE id = :i"),
                {"i": couple.analysis_id},
            )
        ).scalar_one()
    return other_rid, res.report_id, pids


async def test_purge_removes_dependent_personal_data_only(
    engine: AsyncEngine, test_db_url, caplog: pytest.LogCaptureFixture
):
    from fateweave.admin import main

    other_rid, couple_rid, pids = await _purge_fixture(engine)
    url = test_db_url.render_as_string(hide_password=False)
    assert await _counts(engine) == {
        "birth_profiles": 3,
        "analysis_runs": 2,
        "report_versions": 2,
        "alternative_interpretations": 1,
    }

    # Dry run: reports impact only, deletes nothing.
    assert await asyncio.to_thread(main, ["purge-profile", "--profile-id", str(pids[0])], url) == 0
    assert (await _counts(engine))["birth_profiles"] == 3

    caplog.set_level("INFO", logger="fateweave.audit")
    argv = ["purge-profile", "--profile-id", str(pids[0]), "--confirm"]
    assert await asyncio.to_thread(main, argv, url) == 0
    assert await _counts(engine) == {
        "birth_profiles": 2,  # unrelated profile + the couple's partner survive
        "analysis_runs": 1,
        "report_versions": 1,
        "alternative_interpretations": 0,
    }
    svc = _reports(engine)
    assert (await svc.get_report(other_rid)).report_id == other_rid
    with pytest.raises(ReportError) as exc:
        await svc.get_report(couple_rid)
    assert exc.value.code == "REPORT_NOT_FOUND"
    async with engine.connect() as conn:
        left = (await conn.execute(text("SELECT id FROM birth_profiles"))).scalars().all()
    assert pids[1] in left and pids[0] not in left

    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "fateweave.audit"]
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "purge-profile" and event["profile_id"] == str(pids[0])
    assert event["counts"]["report_versions"] == 1 and event["timestamp"].endswith("+00:00")
    assert set(event) == {"action", "profile_id", "counts", "timestamp"}


async def test_purge_cli_dry_run_output_and_missing_profile(
    engine: AsyncEngine, test_db_url, capsys: pytest.CaptureFixture
):
    from fateweave.admin import main

    _, _, pids = await _purge_fixture(engine)
    url = test_db_url.render_as_string(hide_password=False)
    assert await asyncio.to_thread(main, ["purge-profile", "--profile-id", str(pids[0])], url) == 0
    out = capsys.readouterr().out
    assert "--confirm" in out and "report_versions: 1" in out and "analysis_runs: 1" in out

    argv = ["purge-profile", "--profile-id", str(uuid.uuid4()), "--confirm"]
    assert await asyncio.to_thread(main, argv, url) == 2


def _cli(argv: list[str], url: str) -> int:
    from fateweave.admin import main

    return main(argv, url)


async def test_list_profiles_newest_first_without_birth_data(
    engine: AsyncEngine, test_db_url, capsys: pytest.CaptureFixture
):
    _, _, pids = await _purge_fixture(engine)
    url = test_db_url.render_as_string(hide_password=False)
    async with engine.connect() as conn:
        newest_first = (
            (await conn.execute(text("SELECT id FROM birth_profiles ORDER BY created_at DESC, id")))
            .scalars()
            .all()
        )
    capsys.readouterr()
    assert await asyncio.to_thread(_cli, ["list-profiles"], url) == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert [uuid.UUID(ln.split()[0]) for ln in lines[1:]] == newest_first
    assert set(pids) <= set(newest_first)
    assert all(ln.endswith("runs=1") for ln in lines[1:])
    assert "1990-05-15" not in out and "1988-03-02" not in out and "birth_input" not in out

    assert await asyncio.to_thread(_cli, ["list-profiles", "--limit", "1"], url) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 2 and lines[1].startswith(str(newest_first[0]))


async def test_purge_report_dry_run_then_confirm(
    engine: AsyncEngine, test_db_url, capsys: pytest.CaptureFixture, caplog
):
    other_rid, couple_rid, pids = await _purge_fixture(engine)
    url = test_db_url.render_as_string(hide_password=False)
    before = await _counts(engine)
    capsys.readouterr()

    argv = ["purge-report", "--report-id", str(couple_rid)]
    assert await asyncio.to_thread(_cli, argv, url) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "--confirm" in out
    assert str(pids[0]) in out and str(pids[1]) in out
    assert "report_versions: 1" in out and "birth_profiles: 2" in out
    assert await _counts(engine) == before

    caplog.set_level("INFO", logger="fateweave.audit")
    assert await asyncio.to_thread(_cli, [*argv, "--confirm"], url) == 0
    assert await _counts(engine) == {
        "birth_profiles": 1,
        "analysis_runs": 1,
        "report_versions": 1,
        "alternative_interpretations": 0,
    }
    assert (await _reports(engine).get_report(other_rid)).report_id == other_rid
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "fateweave.audit"]
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "purge-report" and event["report_id"] == str(couple_rid)
    assert event["profile_ids"] == [str(p) for p in pids]
    assert event["counts"]["birth_profiles"] == 2 and event["counts"]["report_versions"] == 1

    missing = ["purge-report", "--report-id", str(uuid.uuid4()), "--confirm"]
    assert await asyncio.to_thread(_cli, missing, url) == 2


async def test_purge_profile_reports_orphans(
    engine: AsyncEngine, test_db_url, capsys: pytest.CaptureFixture
):
    _, _, pids = await _purge_fixture(engine)
    url = test_db_url.render_as_string(hide_password=False)
    capsys.readouterr()
    argv = ["purge-profile", "--profile-id", str(pids[0])]
    assert await asyncio.to_thread(_cli, argv, url) == 0
    out = capsys.readouterr().out
    assert "orphaned" in out and str(pids[1]) in out  # the dry run names the would-be orphan

    assert await asyncio.to_thread(_cli, [*argv, "--confirm"], url) == 0
    out = capsys.readouterr().out
    assert "orphaned" in out and str(pids[1]) in out and "--include-orphans" in out
    async with engine.connect() as conn:
        left = (await conn.execute(text("SELECT id FROM birth_profiles"))).scalars().all()
    assert pids[1] in left and pids[0] not in left  # reported, not deleted


async def test_purge_profile_include_orphans(engine: AsyncEngine, test_db_url, caplog):
    _, _, pids = await _purge_fixture(engine)
    url = test_db_url.render_as_string(hide_password=False)
    caplog.set_level("INFO", logger="fateweave.audit")
    argv = ["purge-profile", "--profile-id", str(pids[0]), "--confirm", "--include-orphans"]
    assert await asyncio.to_thread(_cli, argv, url) == 0
    assert await _counts(engine) == {
        "birth_profiles": 1,  # only the unrelated individual's profile remains
        "analysis_runs": 1,
        "report_versions": 1,
        "alternative_interpretations": 0,
    }
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "fateweave.audit"]
    assert [(e["action"], e["profile_id"]) for e in events] == [
        ("purge-profile", str(pids[0])),
        ("purge-orphan-profile", str(pids[1])),
    ]
    assert events[1]["counts"]["birth_profiles"] == 1
