from datetime import date, time
from typing import Literal

from pydantic import BaseModel, ConfigDict


class BirthProfileInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    alias: str | None = None
    birth_date: date
    calendar: Literal["solar", "lunar"]
    leap_month: bool = False
    birth_time: time | None = None
    gender_for_daewoon: Literal["male", "female"]
    # Plain str so normalize_birth can reject others with UNSUPPORTED_TIMEZONE.
    timezone: str = "Asia/Seoul"
    longitude: float | None = None


class NormalizedBirth(BaseModel):
    model_config = ConfigDict(frozen=True)

    solar_date: date  # Gregorian
    original: BirthProfileInput
    calendar: Literal["solar", "lunar"]
    leap_month: bool
    birth_time: time | None
    timezone: str
    longitude: float | None
    gender_for_daewoon: Literal["male", "female"]
    alias: str | None
    assumptions: list[str]
