import uuid
from datetime import date, time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from fateweave.models.facts import PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.services.analysis import AnalysisError, AnalysisService
from fateweave.storage.db import make_sessionmaker


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


def _service(engine: AsyncEngine) -> AnalysisService:
    return AnalysisService(make_sessionmaker(engine), clock=_clock)


async def _count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def test_prepare_individual_persists_snapshot(engine: AsyncEngine):
    svc = _service(engine)
    prepared = await svc.prepare_analysis("individual", [_profile()])
    assert isinstance(prepared, PreparedAnalysis)
    assert prepared.status == "PREPARED"
    assert prepared.mode == "individual"
    assert list(prepared.facts) == ["self"]
    assert prepared.evidence_catalog
    assert prepared.policy_version == "manse-v1" and prepared.rule_version == "rules-v1"
    assert (prepared.start_year, prepared.horizon_years) == (2026, 10)
    assert [s.year for s in prepared.facts["self"].sewoon] == list(range(2026, 2036))

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT mode, status, participant_ids, snapshot, snapshot_hash "
                    "FROM analysis_runs WHERE id = :i"
                ),
                {"i": prepared.analysis_id},
            )
        ).one()
        prof = (
            await conn.execute(
                text("SELECT has_birth_time, timezone, birth_input FROM birth_profiles")
            )
        ).one()
    assert (row.mode, row.status) == ("individual", "PREPARED")
    assert len(row.participant_ids) == 1 and len(row.snapshot_hash) == 64
    assert row.snapshot["start_year"] == 2026
    assert set(row.snapshot) >= {
        "mode",
        "facts",
        "evidence_catalog",
        "missing_data",
        "horizon_years",
        "start_year",
        "policy_version",
        "rule_version",
    }
    assert prof.has_birth_time is True and prof.timezone == "Asia/Seoul"
    assert prof.birth_input["birth_date"] == "1990-05-15"

    again = await svc.get_prepared(prepared.analysis_id)
    assert again == prepared


async def test_prepare_couple_persists_two_participants(engine: AsyncEngine):
    prepared = await _service(engine).prepare_analysis(
        "couple", [_profile(), _profile(birth_date="1992-03-02", gender_for_daewoon="male")]
    )
    assert list(prepared.facts) == ["A", "B"]
    ids = {e.id for e in prepared.evidence_catalog}
    assert any(i.startswith("E-A-") for i in ids) and any(i.startswith("E-B-") for i in ids)
    assert any("COUPLE" in i for i in ids)
    assert await _count(engine, "birth_profiles") == 2
    async with engine.connect() as conn:
        n = (
            await conn.execute(text("SELECT cardinality(participant_ids) FROM analysis_runs"))
        ).scalar_one()
    assert n == 2


@pytest.mark.parametrize(
    ("mode", "count", "horizon"),
    [
        ("individual", 2, 10),
        ("individual", 0, 10),
        ("couple", 1, 10),
        ("couple", 3, 10),
        ("individual", 1, 0),
        ("individual", 1, 31),
    ],
)
async def test_invalid_profile_count_fails_without_insert(engine, mode, count, horizon):
    with pytest.raises(AnalysisError) as exc:
        await _service(engine).prepare_analysis(mode, [_profile()] * count, horizon)
    assert exc.value.code == "INVALID_INPUT"
    assert await _count(engine, "birth_profiles") == 0
    assert await _count(engine, "analysis_runs") == 0


async def test_bad_birth_input_fails_without_insert(engine: AsyncEngine):
    with pytest.raises(AnalysisError) as exc:
        await _service(engine).prepare_analysis(
            "couple", [_profile(), _profile(timezone="America/New_York")]
        )
    assert exc.value.code == "INVALID_INPUT"
    assert "UNSUPPORTED_TIMEZONE" in exc.value.message
    assert await _count(engine, "birth_profiles") == 0
    assert await _count(engine, "analysis_runs") == 0


async def test_missing_hour_returns_limitation(engine: AsyncEngine):
    prepared = await _service(engine).prepare_analysis(
        "individual", [_profile(birth_time=None, longitude=None)]
    )
    assert prepared.facts["self"].hour_pillar is None
    joined = " ".join(prepared.missing_data)
    assert "hour" in joined.lower() and "longitude" in joined.lower()
    assert "1990" not in joined and "14:30" not in joined


async def test_recomputed_facts_same_policy_are_deterministic(engine: AsyncEngine):
    svc = _service(engine)
    first = await svc.prepare_analysis("individual", [_profile()])
    second = await svc.prepare_analysis("individual", [_profile()])
    assert first.analysis_id != second.analysis_id
    assert first.facts == second.facts
    assert [e.id for e in first.evidence_catalog] == [e.id for e in second.evidence_catalog]
    async with engine.connect() as conn:
        hashes = (await conn.execute(text("SELECT snapshot_hash FROM analysis_runs"))).scalars()
        assert len(set(hashes)) == 1


async def test_get_prepared_unknown_returns_none(engine: AsyncEngine):
    assert await _service(engine).get_prepared(uuid.uuid4()) is None


async def test_get_prepared_detects_tampering(engine: AsyncEngine):
    svc = _service(engine)
    prepared = await svc.prepare_analysis("individual", [_profile()])
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE analysis_runs SET snapshot = jsonb_set(snapshot, '{start_year}', '1999') "
                "WHERE id = :i"
            ),
            {"i": prepared.analysis_id},
        )
    with pytest.raises(AnalysisError) as exc:
        await svc.get_prepared(prepared.analysis_id)
    assert exc.value.code == "SNAPSHOT_INTEGRITY"


async def test_storage_failure_maps_to_storage_unavailable():
    bad = create_async_engine("postgresql+asyncpg://x:y@127.0.0.1:1/none")
    svc = AnalysisService(make_sessionmaker(bad), clock=_clock)
    try:
        with pytest.raises(AnalysisError) as exc:
            await svc.prepare_analysis("individual", [_profile()])
        assert exc.value.code == "STORAGE_UNAVAILABLE"
    finally:
        await bad.dispose()


@pytest.mark.parametrize(
    "kw",
    [
        dict(birth_date="1990-02-30"),
        dict(birth_date="1990-02-31", calendar="lunar"),
        dict(birth_date="1990-05-15", leap_month=True),
        dict(birth_date="0999-01-01"),
        dict(birth_date="1990-05-15", timezone="America/New_York"),
    ],
)
async def test_input_errors_do_not_leak_birth_data(engine: AsyncEngine, kw):
    with pytest.raises(AnalysisError) as exc:
        await _service(engine).prepare_analysis("individual", [_profile(**kw)])
    assert exc.value.code == "INVALID_INPUT"
    date_text = kw["birth_date"]
    assert date_text not in exc.value.message and date_text not in str(exc.value)
