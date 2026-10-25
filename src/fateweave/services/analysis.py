"""Application service: normalize input, compute chart + evidence, persist a PREPARED snapshot."""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fateweave.config import Settings
from fateweave.domain.calendar import BirthInputError, normalize_birth
from fateweave.domain.couple import build_couple_evidence
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import build_individual_evidence
from fateweave.models.facts import ChartSnapshot, Evidence, PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.storage.repository import AnalysisRepository

log = logging.getLogger(__name__)

MIN_HORIZON, MAX_HORIZON = 1, 30
_EXPECTED_PROFILES = {"individual": 1, "couple": 2}


class AnalysisError(Exception):
    """Service failure with a stable `code`; `message` never contains birth data."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def seoul_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _missing_data(facts: dict[str, ChartSnapshot]) -> list[str]:
    """Human-readable limitations from chart state; fixed phrases only (no birth data)."""
    notes: list[str] = []
    for key, chart in facts.items():
        who = "the subject" if key == "self" else f"subject {key}"
        if chart.hour_pillar is None:
            notes.append(f"Birth time unknown for {who}: the hour pillar was not computed.")
        if chart.certainty == "PARTIAL":
            notes.append(
                f"Pillar boundary review needed for {who}: alternative pillar sets are possible, "
                "so pillar-dependent statements are not definitive."
            )
        codes = chart.warning_codes
        if "LONGITUDE_ASSUMED_SEOUL" in codes:
            notes.append(f"Birth longitude unknown for {who}: Seoul longitude was assumed.")
        if "SOLAR_TERMS_COMPUTED" in codes:
            notes.append(f"Solar term times for {who} are computed, not from the KASI table.")
        if "CIVIL_TIME_OFFSET_UNVERIFIED" in codes:
            notes.append(f"Civil time offset for {who}'s birth year is unverified.")
        if "NON_DEFAULT_YAJA_POLICY" in codes:
            notes.append(f"A non-default late-night (yaja-si) policy was used for {who}.")
        if "DAEWOON_START_APPROXIMATE" in codes:
            notes.append(f"Daewoon start age for {who} is approximate.")
    return notes


class AnalysisService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Callable[[], date] = seoul_today,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock

    async def prepare_analysis(
        self,
        mode: Literal["individual", "couple"],
        profiles: list[BirthProfileInput],
        horizon_years: int = 10,
    ) -> PreparedAnalysis:
        expected = _EXPECTED_PROFILES.get(mode)
        if expected is None:
            raise AnalysisError("INVALID_INPUT", f"unknown mode: {mode!r}")
        if len(profiles) != expected:
            raise AnalysisError(
                "INVALID_INPUT", f"{mode} analysis needs exactly {expected} profile(s)"
            )
        if not MIN_HORIZON <= horizon_years <= MAX_HORIZON:
            raise AnalysisError(
                "INVALID_INPUT", f"horizon_years must be {MIN_HORIZON}..{MAX_HORIZON}"
            )

        start_year = self._clock().year
        keys = ["self"] if mode == "individual" else ["A", "B"]
        try:
            normalized = [normalize_birth(p) for p in profiles]
            charts = [
                compute_chart(n, sewoon_start_year=start_year, sewoon_years=horizon_years)
                for n in normalized
            ]
        except BirthInputError as exc:
            raise AnalysisError("INVALID_INPUT", f"{exc.code}: birth input rejected") from exc
        except Exception as exc:  # engine failure: no chart at all
            log.error("chart calculation failed: %s", type(exc).__name__)
            raise AnalysisError(
                "CALCULATION_UNCERTAIN", "the chart could not be calculated"
            ) from exc

        facts = dict(zip(keys, charts, strict=True))
        if mode == "individual":
            catalog: list[Evidence] = build_individual_evidence(charts[0], "self")
        else:
            catalog = build_couple_evidence(charts[0], charts[1], start_year, years=horizon_years)

        analysis_id = uuid.uuid4()
        prepared = PreparedAnalysis(
            analysis_id=analysis_id,
            mode=mode,
            facts=facts,
            evidence_catalog=catalog,
            missing_data=_missing_data(facts),
            policy_version=Settings.MANSE_POLICY_VERSION,
            rule_version=Settings.RULE_VERSION,
            horizon_years=horizon_years,
            start_year=start_year,
        )
        snapshot = prepared.model_dump(mode="json", exclude={"analysis_id", "status"})

        try:
            async with self._sessionmaker() as session, session.begin():
                repo = AnalysisRepository(session)
                participant_ids = [
                    await repo.add_profile(
                        birth_input=p.model_dump(mode="json"),
                        has_birth_time=p.birth_time is not None,
                        timezone=p.timezone,
                        alias=p.alias,
                    )
                    for p in profiles
                ]
                await repo.create_run(
                    id=analysis_id,
                    mode=mode,
                    participant_ids=participant_ids,
                    snapshot=snapshot,
                    snapshot_hash=snapshot_hash(snapshot),
                    policy_version=prepared.policy_version,
                    rule_version=prepared.rule_version,
                    status="PREPARED",
                )
        except (SQLAlchemyError, OSError) as exc:
            log.error("persisting analysis failed: %s", type(exc).__name__)
            raise AnalysisError("STORAGE_UNAVAILABLE", "the analysis could not be saved") from exc
        return prepared

    async def get_prepared(self, analysis_id: uuid.UUID) -> PreparedAnalysis | None:
        try:
            async with self._sessionmaker() as session:
                run = await AnalysisRepository(session).get_run(analysis_id)
        except (SQLAlchemyError, OSError) as exc:
            log.error("loading analysis failed: %s", type(exc).__name__)
            raise AnalysisError("STORAGE_UNAVAILABLE", "the analysis could not be loaded") from exc
        if run is None:
            return None
        if snapshot_hash(run.snapshot) != run.snapshot_hash:
            raise AnalysisError(
                "SNAPSHOT_INTEGRITY", "stored snapshot does not match its recorded hash"
            )
        return PreparedAnalysis(analysis_id=run.id, status=run.status, **run.snapshot)
