from datetime import date

from korean_lunar_calendar import KoreanLunarCalendar

from fateweave.models.inputs import BirthProfileInput, NormalizedBirth

SUPPORTED_TIMEZONE = "Asia/Seoul"

# Library-supported ranges (KoreanLunarCalendar.KOREAN_*_MIN/MAX_VALUE, as YYYYMMDD).
_LUNAR_MIN = (1000, 1, 1)
_LUNAR_MAX = (2050, 11, 18)
_SOLAR_MIN = date(1000, 2, 13)
_SOLAR_MAX = date(2050, 12, 31)


class BirthInputError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _lunar_to_solar(text: str, leap: bool) -> date:
    year, month, day = (int(part) for part in text.split("-"))
    if not (_LUNAR_MIN <= (year, month, day) <= _LUNAR_MAX):
        raise BirthInputError(
            "UNSUPPORTED_DATE",
            "lunar date is outside the supported 1000-2050 range",
        )
    cal = KoreanLunarCalendar()
    if not cal.setLunarDate(year, month, day, leap):
        kind = "leap " if leap else ""
        raise BirthInputError("INVALID_LUNAR_DATE", f"no such {kind}lunar date")
    return date(cal.solarYear, cal.solarMonth, cal.solarDay)


def normalize_birth(profile: BirthProfileInput) -> NormalizedBirth:
    if profile.timezone != SUPPORTED_TIMEZONE:
        raise BirthInputError(
            "UNSUPPORTED_TIMEZONE",
            f"only {SUPPORTED_TIMEZONE} is supported, got {profile.timezone}",
        )
    if profile.calendar == "solar":
        if profile.leap_month:
            raise BirthInputError("INVALID_INPUT", "leap_month is only valid with a lunar calendar")
        try:
            solar = date.fromisoformat(profile.birth_date)
        except ValueError as exc:
            raise BirthInputError("INVALID_INPUT", "not a valid Gregorian date") from exc
        if not (_SOLAR_MIN <= solar <= _SOLAR_MAX):
            raise BirthInputError(
                "UNSUPPORTED_DATE",
                "solar date is outside the supported "
                f"{_SOLAR_MIN.isoformat()} to {_SOLAR_MAX.isoformat()} range",
            )
    else:
        solar = _lunar_to_solar(profile.birth_date, profile.leap_month)

    assumptions: list[str] = []
    if profile.birth_time is None:
        assumptions.append("birth time unknown; hour pillar not computed")

    return NormalizedBirth(
        solar_date=solar,
        original=profile,
        calendar=profile.calendar,
        leap_month=profile.leap_month,
        birth_time=profile.birth_time,
        timezone=profile.timezone,
        longitude=profile.longitude,
        gender_for_daewoon=profile.gender_for_daewoon,
        alias=profile.alias,
        assumptions=assumptions,
    )
