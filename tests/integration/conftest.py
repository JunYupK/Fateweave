"""Disposable-database fixtures for storage integration tests.

Tests read ``TEST_DATABASE_URL`` (a server URL such as
``postgresql+asyncpg://postgres:test@127.0.0.1:55432/postgres``). They never fall back to
``FATEWEAVE_DATABASE_URL``. A fresh database is created per session and dropped afterwards.
"""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from fateweave.storage.db import make_engine, make_sessionmaker

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("alternative_interpretations", "report_versions", "analysis_runs", "birth_profiles")


async def _admin(url: URL, *statements: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            for stmt in statements:
                await conn.execute(text(stmt))
    finally:
        await engine.dispose()


def alembic_config(url: URL) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["url"] = url.render_as_string(hide_password=False)
    return cfg


@pytest.fixture(scope="session")
def server_url() -> URL:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip(
            "TEST_DATABASE_URL is not set; integration tests need a disposable Postgres "
            "(see README 'Running integration tests')"
        )
    return make_url(raw)


@pytest.fixture(scope="session")
def test_db_url(server_url: URL) -> Iterator[URL]:
    name = f"fateweave_test_{secrets.token_hex(4)}"
    asyncio.run(_admin(server_url, f'CREATE DATABASE "{name}"'))
    url = server_url.set(database=name)
    try:
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        asyncio.run(_admin(server_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest_asyncio.fixture
async def engine(test_db_url: URL) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(test_db_url.render_as_string(hide_password=False))
    async with eng.begin() as conn:
        await conn.execute(text("SET LOCAL fateweave.maintenance = 'on'"))
        for table in TABLES:
            await conn.execute(text(f"DELETE FROM {table}"))
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with make_sessionmaker(engine)() as s:
        yield s
