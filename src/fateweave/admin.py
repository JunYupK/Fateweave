"""Local admin CLI: ``python -m fateweave.admin purge-profile --profile-id UUID [--confirm]``.

Server-internal only (no MCP tool). Audit events carry counts and ids, never birth data or aliases.
"""

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from fateweave.config import get_settings
from fateweave.storage.db import make_engine, make_sessionmaker
from fateweave.storage.repository import AnalysisRepository

audit = logging.getLogger("fateweave.audit")

EXIT_OK, EXIT_ERROR, EXIT_NOT_FOUND = 0, 1, 2


def _emit_audit(action: str, profile_id: uuid.UUID, counts: dict[str, int]) -> None:
    audit.info(
        json.dumps(
            {
                "action": action,
                "profile_id": str(profile_id),
                "counts": counts,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
        )
    )


async def _purge(url: str, profile_id: uuid.UUID, confirm: bool) -> int:
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine)() as session:
            repo = AnalysisRepository(session)
            if not await repo.profile_exists(profile_id):
                print(f"profile {profile_id} not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            if not confirm:
                counts = await repo.purge_impact(profile_id)
                print(f"DRY RUN: purging profile {profile_id} would delete:")
                for table, n in counts.items():
                    print(f"  {table}: {n}")
                print("Re-run with --confirm to delete.")
                return EXIT_OK
            counts = await repo.purge_profile_and_dependents(profile_id)
            await session.commit()
        _emit_audit("purge-profile", profile_id, counts)
        print(f"purged profile {profile_id}:")
        for table, n in counts.items():
            print(f"  {table}: {n}")
        return EXIT_OK
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None, database_url: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fateweave.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    purge = sub.add_parser("purge-profile", help="delete a profile and its dependent data")
    purge.add_argument("--profile-id", required=True, type=uuid.UUID)
    purge.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    try:
        url = database_url or get_settings().database_url
        return asyncio.run(_purge(url, args.profile_id, args.confirm))
    except (SQLAlchemyError, OSError) as exc:
        print(f"storage error: {type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
