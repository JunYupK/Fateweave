import uuid
from typing import Any

from sqlalchemy import delete, func, select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from fateweave.storage.tables import (
    AlternativeInterpretation,
    AnalysisRun,
    BirthProfile,
    ReportVersion,
)

RunRow = AnalysisRun
ReportRow = ReportVersion


class AnalysisRepository:
    """Persistence for profiles, runs and immutable report versions.

    The repository flushes but never commits; callers own the transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_profile(
        self,
        *,
        birth_input: dict[str, Any],
        has_birth_time: bool,
        timezone: str,
        alias: str | None = None,
        id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        row = BirthProfile(
            id=id or uuid.uuid4(),
            alias=alias,
            birth_input=birth_input,
            has_birth_time=has_birth_time,
            timezone=timezone,
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def create_run(
        self,
        *,
        mode: str,
        participant_ids: list[uuid.UUID],
        snapshot: dict[str, Any],
        snapshot_hash: str,
        policy_version: str,
        rule_version: str,
        status: str = "PREPARED",
        id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        row = AnalysisRun(
            id=id or uuid.uuid4(),
            mode=mode,
            participant_ids=participant_ids,
            snapshot=snapshot,
            snapshot_hash=snapshot_hash,
            policy_version=policy_version,
            rule_version=rule_version,
            status=status,
            attempt_count=0,
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def get_run(self, id: uuid.UUID) -> RunRow | None:
        return await self.session.get(AnalysisRun, id)

    async def lock_run(self, id: uuid.UUID) -> RunRow | None:
        """Load a run with ``SELECT ... FOR UPDATE`` (held until the caller's transaction ends)."""
        result = await self.session.execute(
            select(AnalysisRun)
            .where(AnalysisRun.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_report_by_idempotency_key(
        self, analysis_id: uuid.UUID, idempotency_key: str
    ) -> ReportRow | None:
        result = await self.session.execute(
            select(ReportVersion).where(
                ReportVersion.analysis_id == analysis_id,
                ReportVersion.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def update_run_status(
        self,
        id: uuid.UUID,
        status: str,
        last_validation_errors: Any | None = None,
        increment_attempt: bool = False,
    ) -> None:
        values: dict[str, Any] = {
            "status": status,
            "last_validation_errors": last_validation_errors,
        }
        if increment_attempt:
            values["attempt_count"] = AnalysisRun.attempt_count + 1
        await self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == id)
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )

    async def add_report_version(
        self,
        *,
        report_id: uuid.UUID,
        version: int,
        analysis_id: uuid.UUID,
        payload_hash: str,
        report_type: str,
        body: Any,
        markdown: str,
        generated_by: str,
        prompt_version: str,
        validation: Any,
        idempotency_key: str | None = None,
        correction_reason: str | None = None,
    ) -> ReportRow:
        row = ReportVersion(
            report_id=report_id,
            version=version,
            analysis_id=analysis_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            report_type=report_type,
            body=body,
            markdown=markdown,
            generated_by=generated_by,
            prompt_version=prompt_version,
            validation=validation,
            correction_reason=correction_reason,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_report(self, id: uuid.UUID, version: int) -> ReportRow | None:
        result = await self.session.execute(
            select(ReportVersion).where(
                ReportVersion.report_id == id, ReportVersion.version == version
            )
        )
        return result.scalar_one_or_none()

    async def list_reports(self, limit: int = 20, mode: str | None = None) -> list[ReportRow]:
        """Latest version of each report, newest first; ``mode`` filters ``report_type``."""
        ranked = select(
            ReportVersion.id,
            func.row_number()
            .over(partition_by=ReportVersion.report_id, order_by=ReportVersion.version.desc())
            .label("rn"),
        )
        if mode is not None:
            ranked = ranked.where(ReportVersion.report_type == mode)
        sub = ranked.subquery()
        stmt = (
            select(ReportVersion)
            .join(sub, sub.c.id == ReportVersion.id)
            .where(sub.c.rn == 1)
            .order_by(ReportVersion.created_at.desc(), ReportVersion.version.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_latest_report(self, id: uuid.UUID) -> ReportRow | None:
        result = await self.session.execute(
            select(ReportVersion)
            .where(ReportVersion.report_id == id)
            .order_by(ReportVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_report_versions(self, id: uuid.UUID) -> list[ReportRow]:
        result = await self.session.execute(
            select(ReportVersion)
            .where(ReportVersion.report_id == id)
            .order_by(ReportVersion.version)
        )
        return list(result.scalars())

    async def list_alternatives(self, report_id: uuid.UUID) -> list[AlternativeInterpretation]:
        result = await self.session.execute(
            select(AlternativeInterpretation)
            .where(AlternativeInterpretation.report_id == report_id)
            .order_by(AlternativeInterpretation.created_at, AlternativeInterpretation.id)
        )
        return list(result.scalars())

    async def participant_aliases(
        self, runs: dict[uuid.UUID, list[uuid.UUID]]
    ) -> dict[uuid.UUID, list[str | None]]:
        """Aliases per run id (in participant order) for ``{run_id: participant_ids}``."""
        wanted = {pid for ids in runs.values() for pid in ids}
        alias: dict[uuid.UUID, str | None] = {}
        if wanted:
            rows = await self.session.execute(
                select(BirthProfile.id, BirthProfile.alias).where(BirthProfile.id.in_(wanted))
            )
            alias = {pid: a for pid, a in rows}
        return {rid: [alias.get(pid) for pid in ids] for rid, ids in runs.items()}

    async def profile_exists(self, profile_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(BirthProfile.id).where(BirthProfile.id == profile_id)
        )
        return result.scalar_one_or_none() is not None

    async def purge_impact(self, profile_id: uuid.UUID) -> dict[str, int]:
        """Dry-run counts of what ``purge_profile_and_dependents`` would delete."""
        s = self.session
        run_ids = select(AnalysisRun.id).where(AnalysisRun.participant_ids.contains([profile_id]))
        versions = select(ReportVersion.report_id, ReportVersion.version).where(
            ReportVersion.analysis_id.in_(run_ids)
        )
        alt = await s.scalar(
            select(func.count())
            .select_from(AlternativeInterpretation)
            .where(
                tuple_(
                    AlternativeInterpretation.report_id, AlternativeInterpretation.report_version
                ).in_(versions)
            )
        )
        rep = await s.scalar(
            select(func.count())
            .select_from(ReportVersion)
            .where(ReportVersion.analysis_id.in_(run_ids))
        )
        runs = await s.scalar(select(func.count()).select_from(run_ids.subquery()))
        prof = await s.scalar(
            select(func.count()).select_from(BirthProfile).where(BirthProfile.id == profile_id)
        )
        return {
            "alternative_interpretations": alt or 0,
            "report_versions": rep or 0,
            "analysis_runs": runs or 0,
            "birth_profiles": prof or 0,
        }

    async def add_alternative(
        self,
        *,
        report_id: uuid.UUID,
        report_version: int,
        school: str,
        content: str,
        evidence_refs: Any,
    ) -> uuid.UUID:
        row = AlternativeInterpretation(
            report_id=report_id,
            report_version=report_version,
            school=school,
            content=content,
            evidence_refs=evidence_refs,
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def purge_profile_and_dependents(self, profile_id: uuid.UUID) -> dict[str, int]:
        """Delete a profile, every run naming it (couples included) and those runs' reports.

        Other participants' profiles are kept. Immutability triggers are lifted with
        ``SET LOCAL`` semantics, so they re-engage when the caller's transaction ends.
        """
        s = self.session
        await s.execute(text("SELECT set_config('fateweave.maintenance', 'on', true)"))
        try:
            run_ids = select(AnalysisRun.id).where(
                AnalysisRun.participant_ids.contains([profile_id])
            )
            versions = select(ReportVersion.report_id, ReportVersion.version).where(
                ReportVersion.analysis_id.in_(run_ids)
            )
            alt = await s.execute(
                delete(AlternativeInterpretation).where(
                    tuple_(
                        AlternativeInterpretation.report_id,
                        AlternativeInterpretation.report_version,
                    ).in_(versions)
                )
            )
            rep = await s.execute(
                delete(ReportVersion).where(ReportVersion.analysis_id.in_(run_ids))
            )
            runs = await s.execute(
                delete(AnalysisRun).where(AnalysisRun.participant_ids.contains([profile_id]))
            )
            prof = await s.execute(delete(BirthProfile).where(BirthProfile.id == profile_id))
        finally:
            await s.execute(text("SELECT set_config('fateweave.maintenance', 'off', true)"))
        return {
            "alternative_interpretations": alt.rowcount,
            "report_versions": rep.rowcount,
            "analysis_runs": runs.rowcount,
            "birth_profiles": prof.rowcount,
        }
