"""Local admin CLI (server-internal only; no MCP tool).

    python -m fateweave.admin list-profiles [--limit N]
    python -m fateweave.admin purge-profile --profile-id UUID [--confirm] [--include-orphans]
    python -m fateweave.admin purge-report --report-id UUID [--confirm] [--include-orphans]

Without ``--confirm`` the purge commands are dry runs. Output and audit events carry ids, aliases
(listing only) and counts, never birth data; audit events never carry aliases.
"""

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from fateweave.config import get_settings
from fateweave.storage.db import make_engine, make_sessionmaker
from fateweave.storage.repository import AnalysisRepository

audit = logging.getLogger("fateweave.audit")

EXIT_OK, EXIT_ERROR, EXIT_NOT_FOUND = 0, 1, 2


def _emit_audit(action: str, counts: dict[str, int], **ids: Any) -> None:
    audit.info(
        json.dumps(
            {**ids, "action": action, "counts": counts, "timestamp": datetime.now(UTC).isoformat()},
            sort_keys=True,
        )
    )


def _print_counts(counts: dict[str, int]) -> None:
    for table, n in counts.items():
        print(f"  {table}: {n}")


def _add_counts(total: dict[str, int], counts: dict[str, int]) -> None:
    for table, n in counts.items():
        total[table] = total.get(table, 0) + n


async def _list_profiles(repo: AnalysisRepository, limit: int) -> int:
    print("id  alias  created_at  runs")
    for pid, alias, created, runs in await repo.list_profiles(limit):
        print(f"{pid}  {alias or '-'}  {created.isoformat()}  runs={runs}")
    return EXIT_OK


async def _purge(
    repo: AnalysisRepository,
    profile_ids: list[uuid.UUID],
    *,
    confirm: bool,
    include_orphans: bool,
    target: str,
    audit_event: tuple[str, dict[str, Any]] | None,
) -> int:
    """Dry run, or purge ``profile_ids`` (plus orphans if asked) in the caller's transaction."""
    orphans = await repo.orphans_after(profile_ids)
    if not confirm:
        print(f"DRY RUN: purging {target} would delete:")
        _print_counts(await repo.purge_impact_many(profile_ids))
        for pid in orphans:
            verb = "would also be purged" if include_orphans else "would be left"
            print(f"orphaned profile {pid} {verb} (no remaining runs)")
        print("Re-run with --confirm to delete.")
        return EXIT_OK

    total: dict[str, int] = {}
    events: list[tuple[str, dict[str, int], dict[str, Any]]] = []
    for pid in profile_ids:
        counts = await repo.purge_profile_and_dependents(pid)
        _add_counts(total, counts)
        if audit_event is None:
            events.append(("purge-profile", counts, {"profile_id": str(pid)}))
    if audit_event is not None:
        action, ids = audit_event
        events.append((action, dict(total), ids))
    purged_orphans = []
    if include_orphans:
        for pid in orphans:
            counts = await repo.purge_profile_and_dependents(pid)
            events.append(("purge-orphan-profile", counts, {"profile_id": str(pid)}))
            purged_orphans.append(pid)
    await repo.session.commit()

    for action, counts, ids in events:
        _emit_audit(action, counts, **ids)
    print(f"purged {target}:")
    _print_counts(total)
    for pid in purged_orphans:
        print(f"purged orphaned profile {pid} (no remaining runs)")
    left = [pid for pid in orphans if pid not in purged_orphans]
    for pid in left:
        print(f"orphaned profile {pid} has no remaining runs (kept)")
    if left:
        print("Purge them with purge-profile --profile-id <id> --confirm or --include-orphans.")
    return EXIT_OK


async def _run(url: str, args: argparse.Namespace) -> int:
    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine)() as session:
            repo = AnalysisRepository(session)
            if args.command == "list-profiles":
                return await _list_profiles(repo, args.limit)
            if args.command == "purge-profile":
                pid = args.profile_id
                if not await repo.profile_exists(pid):
                    print(f"profile {pid} not found", file=sys.stderr)
                    return EXIT_NOT_FOUND
                return await _purge(
                    repo,
                    [pid],
                    confirm=args.confirm,
                    include_orphans=args.include_orphans,
                    target=f"profile {pid}",
                    audit_event=None,
                )
            rid = args.report_id
            participants = await repo.report_participants(rid)
            if participants is None:
                print(f"report {rid} not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"report {rid} participants: {', '.join(map(str, participants))}")
            return await _purge(
                repo,
                participants,
                confirm=args.confirm,
                include_orphans=args.include_orphans,
                target=f"report {rid} participants",
                audit_event=(
                    "purge-report",
                    {"report_id": str(rid), "profile_ids": [str(p) for p in participants]},
                ),
            )
    finally:
        await engine.dispose()


def _positive(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def main(argv: list[str] | None = None, database_url: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fateweave.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list-profiles", help="list profiles (id, alias, created_at, runs)")
    listing.add_argument("--limit", type=_positive, default=50)
    purge = sub.add_parser("purge-profile", help="delete a profile and its dependent data")
    purge.add_argument("--profile-id", required=True, type=uuid.UUID)
    report = sub.add_parser("purge-report", help="delete every participant of a report's run")
    report.add_argument("--report-id", required=True, type=uuid.UUID)
    for p in (purge, report):
        p.add_argument("--confirm", action="store_true")
        p.add_argument(
            "--include-orphans",
            action="store_true",
            help="also purge co-participant profiles left with no remaining runs",
        )
    args = parser.parse_args(argv)
    try:
        url = database_url or get_settings().database_url
        return asyncio.run(_run(url, args))
    except (SQLAlchemyError, OSError) as exc:
        print(f"storage error: {type(exc).__name__}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
