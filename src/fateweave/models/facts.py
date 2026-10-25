"""Computed facts: models only (no computation beyond the canonical facts hash)."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, computed_field


class ChartWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    detail: str


class PillarAlternative(BaseModel):
    """A pillar set the chart could take instead of the primary one.

    `reasons` are codes (DAY_BOUNDARY, SOLAR_TERM, SOLAR_TERM_COMPUTED, LONGITUDE_UNKNOWN,
    CIVIL_TIME_OFFSET). `local_windows` are the local wall-clock minute ranges of the birth
    date that yield this set, when that is known (unknown-birth-time scans).
    """

    model_config = ConfigDict(frozen=True)

    year_pillar: str
    month_pillar: str
    day_pillar: str
    hour_pillar: str | None
    reasons: list[str]
    local_windows: list[str]


class DaewoonEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_age: int
    pillar: str


class DaewoonFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    forward: bool
    start_age: int
    start_months_offset: int
    entries: list[DaewoonEntry]


class SewoonEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    age: int  # library value: year - birth year
    pillar: str


class ChartSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_version: str
    library_version: str
    solar_date: str  # ISO date (Gregorian)
    birth_time: str | None  # as given; never filled when unknown
    timezone: str
    longitude: float  # longitude actually used for the solar-time correction
    gender_for_daewoon: Literal["male", "female"]
    yaja_si_separated: bool
    solar_term_source: Literal["kasi", "computed"]

    year_pillar: str
    month_pillar: str
    day_pillar: str
    hour_pillar: str | None
    ten_gods: dict[str, str]
    daewoon: DaewoonFacts
    sewoon: list[SewoonEntry]

    assumptions: list[str]
    warnings: list[ChartWarning]
    alternatives: list[PillarAlternative]
    certainty: Literal["CONFIRMED", "PARTIAL"]

    @property
    def warning_codes(self) -> list[str]:
        return [w.code for w in self.warnings]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def facts_hash(self) -> str:
        """sha256 of canonical JSON over every other field (sorted keys, compact, UTF-8)."""
        payload = self.model_dump(mode="json", exclude={"facts_hash"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Evidence(BaseModel):
    """One verifiable fact derived from a ChartSnapshot (built in domain/rules.py).

    `id` is `E-{subject_key}-{rule_code}-{sha256(canonical operands)[:8]}`; `operands` are the
    values a citation is checked against. `interpretation_cue` items only name a
    school-dependent premise and never assert a computed result.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    kind: Literal["computed", "rule_derived", "interpretation_cue"]
    rule_code: str
    operands: dict[str, Any]
    text_ko: str
    source_ref: str | None
    assumptions: list[str]
