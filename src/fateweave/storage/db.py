from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fateweave.config import get_settings


def make_engine(url: str) -> AsyncEngine:
    """Create an async engine; the URL must use the asyncpg driver."""
    if not url.startswith("postgresql+asyncpg://"):
        raise ValueError("database URL must start with postgresql+asyncpg://")
    # hide_parameters: SQL error strings and logs never carry draft or birth data.
    return create_async_engine(url, pool_pre_ping=True, hide_parameters=True)


def select_migration_url(
    *, attribute: str | None, x_url: str | None, env_url: str | None
) -> str:
    """Alembic URL precedence: programmatic attribute > ``-x url=`` > FATEWEAVE_DATABASE_URL.

    An explicit ``-x url`` must beat the ambient env var, so a command aimed at a scratch
    database can never silently run against the database exported in the shell.
    """
    url = attribute or x_url or env_url
    if not url:
        raise RuntimeError("Set FATEWEAVE_DATABASE_URL or pass `-x url=postgresql+asyncpg://...`")
    return url


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@lru_cache
def _default_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(make_engine(get_settings().database_url))


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session bound to the configured database. Callers own commit/rollback."""
    async with _default_sessionmaker()() as session:
        yield session
