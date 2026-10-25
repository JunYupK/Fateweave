import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from fateweave.storage.db import make_sessionmaker
from fateweave.storage.repository import AnalysisRepository

REPORT_KW = dict(
    payload_hash="h",
    report_type="individual",
    body={"sections": []},
    markdown="# r",
    generated_by="claude",
    prompt_version="p1",
    validation={"ok": True},
)


async def _profile(repo: AnalysisRepository) -> uuid.UUID:
    return await repo.add_profile(
        alias="a", birth_input={"y": 1990}, has_birth_time=True, timezone="Asia/Seoul"
    )


async def _run(repo: AnalysisRepository, pids: list[uuid.UUID], mode="individual") -> uuid.UUID:
    return await repo.create_run(
        mode=mode,
        participant_ids=pids,
        snapshot={"s": 1},
        snapshot_hash="sh",
        policy_version="manse-v1",
        rule_version="rules-v1",
    )


async def test_migration_creates_four_tables(engine: AsyncEngine):
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
    assert {
        "birth_profiles",
        "analysis_runs",
        "report_versions",
        "alternative_interpretations",
    } <= names


async def test_unique_report_version(engine: AsyncEngine):
    maker = make_sessionmaker(engine)
    async with maker() as s:
        repo = AnalysisRepository(s)
        run_id = await _run(repo, [await _profile(repo)])
        rid = uuid.uuid4()
        await repo.add_report_version(report_id=rid, version=1, analysis_id=run_id, **REPORT_KW)
        await s.commit()
    async with maker() as s:
        repo = AnalysisRepository(s)
        with pytest.raises(IntegrityError):
            await repo.add_report_version(report_id=rid, version=1, analysis_id=run_id, **REPORT_KW)
    async with maker() as s:
        repo = AnalysisRepository(s)
        await repo.add_report_version(
            report_id=uuid.uuid4(), version=1, analysis_id=run_id, idempotency_key="k", **REPORT_KW
        )
        await s.commit()
        with pytest.raises(IntegrityError):
            await repo.add_report_version(
                report_id=uuid.uuid4(),
                version=1,
                analysis_id=run_id,
                idempotency_key="k",
                **REPORT_KW,
            )


async def test_immutable_versions(engine: AsyncEngine):
    maker = make_sessionmaker(engine)
    async with maker() as s:
        repo = AnalysisRepository(s)
        run_id = await _run(repo, [await _profile(repo)])
        rid = uuid.uuid4()
        await repo.add_report_version(report_id=rid, version=1, analysis_id=run_id, **REPORT_KW)
        await repo.add_alternative(
            report_id=rid, report_version=1, school="x", content="c", evidence_refs=[]
        )
        await s.commit()
    for sql in (
        "UPDATE report_versions SET markdown = 'x'",
        "DELETE FROM report_versions",
        "UPDATE alternative_interpretations SET content = 'x'",
        "DELETE FROM alternative_interpretations",
    ):
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError, match="immutable"):
                await conn.execute(text(sql))
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL fateweave.maintenance = 'on'"))
        await conn.execute(text("DELETE FROM alternative_interpretations"))
        res = await conn.execute(text("DELETE FROM report_versions"))
        assert res.rowcount == 1


async def _reset_status(maker, run_id):
    async with maker() as s:
        await AnalysisRepository(s).update_run_status(run_id, "PREPARED")
        await s.commit()


async def test_transaction_rollback_keeps_prepared(engine: AsyncEngine):
    maker = make_sessionmaker(engine)
    async with maker() as s:
        repo = AnalysisRepository(s)
        run_id = await _run(repo, [await _profile(repo)])
        await s.commit()
    async with maker() as s:
        await AnalysisRepository(s).update_run_status(
            run_id, "VALIDATION_FAILED", last_validation_errors=[{"e": 1}], increment_attempt=True
        )
        await s.rollback()
    async with maker() as s:
        repo = AnalysisRepository(s)
        await repo.update_run_status(run_id, "ABANDONED", last_validation_errors=None)
        await s.commit()
    async with engine.connect() as conn:
        is_null = await conn.scalar(
            text("SELECT last_validation_errors IS NULL FROM analysis_runs WHERE id = :i"),
            {"i": run_id},
        )
        assert is_null is True
    await _reset_status(maker, run_id)
    async with maker() as s:
        run = await AnalysisRepository(s).get_run(run_id)
        assert run.status == "PREPARED"
        assert run.attempt_count == 0
        assert run.last_validation_errors is None


async def test_update_run_status_and_list_reports(engine: AsyncEngine):
    maker = make_sessionmaker(engine)
    async with maker() as s:
        repo = AnalysisRepository(s)
        run_id = await _run(repo, [await _profile(repo)])
        await repo.update_run_status(
            run_id, "VALIDATION_FAILED", [{"e": 1}], increment_attempt=True
        )
        r1, r2 = uuid.uuid4(), uuid.uuid4()
        await repo.add_report_version(report_id=r1, version=1, analysis_id=run_id, **REPORT_KW)
        await repo.add_report_version(
            report_id=r1, version=2, analysis_id=run_id, correction_reason="fix", **REPORT_KW
        )
        await s.commit()  # created_at is now(), i.e. per transaction
        await repo.add_report_version(
            report_id=r2, version=1, analysis_id=run_id, **{**REPORT_KW, "report_type": "couple"}
        )
        await s.commit()
        run = await repo.get_run(run_id)
        assert (run.status, run.attempt_count) == ("VALIDATION_FAILED", 1)
        got = await repo.get_report(r1, 2)
        assert got.correction_reason == "fix"
        assert await repo.get_report(r1, 9) is None
        latest = await repo.list_reports(limit=10)
        assert {(r.report_id, r.version) for r in latest} == {(r1, 2), (r2, 1)}
        assert latest[0].report_id == r2  # newest first
        only = await repo.list_reports(limit=10, mode="individual")
        assert [(r.report_id, r.version) for r in only] == [(r1, 2)]


async def test_purge_profile_and_dependents(engine: AsyncEngine):
    maker = make_sessionmaker(engine)
    async with maker() as s:
        repo = AnalysisRepository(s)
        a, b, c = await _profile(repo), await _profile(repo), await _profile(repo)
        solo = await _run(repo, [a])
        couple = await _run(repo, [a, b], mode="couple")
        other = await _run(repo, [c])
        for run_id in (solo, couple, other):
            rid = uuid.uuid4()
            await repo.add_report_version(report_id=rid, version=1, analysis_id=run_id, **REPORT_KW)
            await repo.add_alternative(
                report_id=rid, report_version=1, school="x", content="c", evidence_refs=[]
            )
        await s.commit()
    async with maker() as s:
        repo = AnalysisRepository(s)
        counts = await repo.purge_profile_and_dependents(a)
        await s.commit()
        assert counts == {
            "alternative_interpretations": 2,
            "report_versions": 2,
            "analysis_runs": 2,
            "birth_profiles": 1,
        }
    async with engine.connect() as conn:
        for table, n in (("birth_profiles", 2), ("analysis_runs", 1), ("report_versions", 1)):
            assert (await conn.scalar(text(f"SELECT count(*) FROM {table}"))) == n
        # immutability is back on after the purge transaction
        with pytest.raises(DBAPIError, match="immutable"):
            await conn.execute(text("DELETE FROM report_versions"))


async def test_separate_database_role_denied_cross_database(server_url, test_db_url, engine):
    db = test_db_url.database
    role, other = "fateweave_app_test", "other_project_test"
    admin = create_async_engine(server_url, isolation_level="AUTOCOMMIT")

    def as_role(database: str):
        return create_async_engine(
            server_url.set(username=role, password="rolepw", database=database)
        )

    try:
        async with admin.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {other} WITH (FORCE)"))
            await conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'rolepw'"))
            await conn.execute(text(f"CREATE DATABASE {other}"))
            await conn.execute(text(f'ALTER DATABASE "{db}" OWNER TO {role}'))
            for name in (other, db):
                await conn.execute(text(f'REVOKE CONNECT ON DATABASE "{name}" FROM PUBLIC'))
            await conn.execute(text(f"REVOKE CONNECT ON DATABASE {other} FROM {role}"))
            await conn.execute(text(f'GRANT CONNECT ON DATABASE "{db}" TO {role}'))

        own = as_role(db)
        try:
            async with own.connect() as conn:
                assert await conn.scalar(text("SELECT 1")) == 1
        finally:
            await own.dispose()
        denied = as_role(other)
        try:
            with pytest.raises(Exception, match="permission denied"):
                async with denied.connect():
                    pass
        finally:
            await denied.dispose()
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {other} WITH (FORCE)"))
            await conn.execute(text(f'ALTER DATABASE "{db}" OWNER TO {server_url.username}'))
            await conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        await admin.dispose()
