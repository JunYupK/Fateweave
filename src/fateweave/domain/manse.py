"""Deterministic manse (만세력) chart adapter over korean-saju 0.3.0 — policy manse-v1.

manse-v1 conventions (fixed; change them only with a new policy version):
- Civil time: the birth wall clock is read as fixed UTC+9 (KST), which is what the library
  assumes. Historical Korean offsets (LMT +8:27:52 to 1908-04-01, UTC+8:30 to 1911 and in
  1954-1961, DST in 1948-1960 and 1987-1988) are not applied; those years get
  CIVIL_TIME_OFFSET_UNVERIFIED and shifted alternatives.
- Year pillar: 立春 instant. Month pillar: 節 instants. Both on absolute time; solar terms come
  from the bundled KASI table (2000-2027) or the library's Meeus computation outside it.
- Day and hour pillars: local mean solar time, KST + (longitude - 135) * 4 min (no equation
  of time). Default longitude 126.9784 (Seoul), recorded as LONGITUDE_ASSUMED_SEOUL.
- Yaja-si separated (library default): AST 23:00-24:00 keeps the calendar day.
- Unknown birth time: noon is only the internal reference instant (year/month/day pillars and
  daewoon start); hour_pillar stays None and birth_time is never filled. Every minute of the
  birth date is evaluated and any differing pillar set is returned as an alternative.
- Uncertain boundaries -> certainty PARTIAL + BOUNDARY_REVIEW_REQUIRED + alternatives:
  pillar changes within the date (unknown time), computed 節 within +-24h of the birth
  (or of the birth date), a KASI 節 in the same minute as the birth, unknown longitude
  across Korea (124.6E-131.9E), and the historical civil-time shifts above.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from importlib import resources

import korean_saju
from korean_saju import (
    Daewoon,
    Gender,
    KasiSolarTerms,
    Saju,
    SajuAnalysis,
    SajuPosition,
    Sewoon,
    SolarTerm,
    SolarTermSource,
    SolarTermType,
    SolarTimeCorrection,
)

from fateweave.config import Settings
from fateweave.domain.calendar import BirthInputError
from fateweave.models.facts import (
    ChartSnapshot,
    ChartWarning,
    DaewoonEntry,
    DaewoonFacts,
    PillarAlternative,
    SewoonEntry,
)
from fateweave.models.inputs import NormalizedBirth

DEFAULT_LONGITUDE = 126.9784
# South Korea's longitude extremes (Baengnyeongdo ~124.6E, Dokdo ~131.9E).
KOREA_LONGITUDE_RANGE = (124.6, 131.9)
MIN_SUPPORTED_YEAR = 1900  # library ΔT / solar-term computation range starts at 1900
COMPUTED_TERM_TOLERANCE = timedelta(hours=24)
KASI_TERM_TOLERANCE = timedelta(minutes=1)
DAEWOON_COUNT = 10
_KST_OFFSET = timedelta(hours=9)
_NOON = time(12, 0)
_MINUTES_PER_DAY = 1440

# (first year, last year, wall-clock -> UTC+9 shifts in minutes) where Korean civil time was not
# UTC+9 for at least part of the year. Whole years are flagged; exact transitions are not used.
_CIVIL_OFFSET_ERAS: tuple[tuple[int, int, tuple[int, ...]], ...] = (
    (1900, 1911, (30, 32)),  # LMT +8:27:52 until 1908-04-01, then UTC+8:30
    (1948, 1961, (-60, -30, 30)),
    (1987, 1988, (-60,)),
)

assert SolarTimeCorrection.SEOUL_LONGITUDE == DEFAULT_LONGITUDE


class _CachedSolarTerms(SolarTermSource):
    """SolarTermSource with per-year memoisation (same values; the scans call it ~10^4 times)."""

    __slots__ = ("_by_year",)

    def __init__(self, kasi: KasiSolarTerms) -> None:
        super().__init__(kasi)
        self._by_year: dict[int, tuple[SolarTerm, ...]] = {}

    def terms_for_year(self, year: int) -> list[SolarTerm]:
        if year not in self._by_year:
            self._by_year[year] = tuple(super().terms_for_year(year))
        return list(self._by_year[year])

    def get(self, year: int, name: str) -> SolarTerm | None:
        return next((t for t in self.terms_for_year(year) if t.name == name), None)


def _load_source() -> _CachedSolarTerms:
    path = resources.files("korean_saju") / "data" / "kasi_solar_terms_2000_2027.json"
    return _CachedSolarTerms(KasiSolarTerms.from_json(path.read_text(encoding="utf-8")))


_SOURCE = _load_source()

Key = tuple[str, str, str, str | None]  # year, month, day, hour pillars


@dataclass
class _Alt:
    reasons: set[str] = field(default_factory=set)
    windows: list[str] = field(default_factory=list)


def _saju(moment: datetime, longitude: float, hour_known: bool, yaja: bool) -> Saju:
    return Saju.from_birth(
        kst_moment=moment,
        solar_terms=_SOURCE,
        longitude=longitude,
        hour_known=hour_known,
        yaja_si_separated=yaja,
    )


def _key(saju: Saju) -> Key:
    hour = saju.hour_pillar.hanja if saju.hour_pillar is not None else None
    return (saju.year_pillar.hanja, saju.month_pillar.hanja, saju.day_pillar.hanja, hour)


def _diff_reasons(key: Key, primary: Key) -> set[str]:
    reasons: set[str] = set()
    if key[:2] != primary[:2]:
        reasons.add("SOLAR_TERM")
    if key[2] != primary[2]:
        reasons.add("DAY_BOUNDARY")
    if key[3] != primary[3]:
        reasons.add("HOUR_BOUNDARY")
    return reasons


def _civil_shifts(year: int) -> tuple[int, ...]:
    for first, last, shifts in _CIVIL_OFFSET_ERAS:
        if first <= year <= last:
            return shifts
    return ()


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _runs(minutes: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for m in minutes:
        if runs and runs[-1][1] == m - 1:
            runs[-1] = (runs[-1][0], m)
        else:
            runs.append((m, m))
    return runs


def _nearby_jeols(start_utc: datetime, end_utc: datetime, *, unknown_time: bool):
    """節 whose instant lies within the accuracy tolerance of [start_utc, end_utc]."""
    for year in range(start_utc.year - 1, end_utc.year + 2):
        for term in _SOURCE.terms_for_year(year):
            if term.type is not SolarTermType.JEOL:
                continue
            computed = _SOURCE.accuracy_for(term.year) == "computed"
            if unknown_time and not computed:
                continue  # KASI terms inside the date are already caught by the minute scan
            tol = COMPUTED_TERM_TOLERANCE if computed else KASI_TERM_TOLERANCE
            if start_utc - tol < term.datetime < end_utc + tol:
                yield term, computed


def compute_chart(
    birth: NormalizedBirth,
    *,
    yaja_si_separated: bool = True,
    sewoon_start_year: int | None = None,
    sewoon_years: int = 10,
) -> ChartSnapshot:
    """Compute a manse-v1 chart snapshot.

    sewoon: `sewoon_years` consecutive years from `sewoon_start_year`; empty when no start year
    is passed (the snapshot never depends on the wall clock).
    """
    year = birth.solar_date.year
    if year < MIN_SUPPORTED_YEAR:
        raise BirthInputError(
            "UNSUPPORTED_DATE",
            f"manse-v1 supports births from {MIN_SUPPORTED_YEAR}; got {birth.solar_date}",
        )
    if sewoon_years < 1:
        raise ValueError("sewoon_years must be >= 1")

    assumptions = list(birth.assumptions)
    warnings: list[ChartWarning] = []

    if birth.longitude is None:
        longitude = DEFAULT_LONGITUDE
        lon_variants = list(KOREA_LONGITUDE_RANGE)
        warnings.append(
            ChartWarning(
                code="LONGITUDE_ASSUMED_SEOUL",
                detail=f"birth longitude unknown; Seoul {DEFAULT_LONGITUDE}E assumed for "
                "the solar-time correction",
            )
        )
    else:
        longitude = birth.longitude
        lon_variants = []
    if not yaja_si_separated:
        warnings.append(
            ChartWarning(
                code="NON_DEFAULT_YAJA_POLICY",
                detail="yaja-si unified (single 子時) instead of manse-v1's separated rule",
            )
        )
    shifts = _civil_shifts(year)
    if shifts:
        warnings.append(
            ChartWarning(
                code="CIVIL_TIME_OFFSET_UNVERIFIED",
                detail=f"Korean civil time in {year} may not have been UTC+9; the wall clock "
                f"is read as UTC+9 and shifts {list(shifts)} min are checked as alternatives",
            )
        )

    hour_known = birth.birth_time is not None
    ref = datetime.combine(birth.solar_date, birth.birth_time or _NOON)
    if not hour_known:
        assumptions.append(
            "birth time unknown: noon (12:00) is used only as the internal reference instant "
            "for the year/month/day pillars and daewoon start; it is not the birth time"
        )
    saju = _saju(ref, longitude, hour_known, yaja_si_separated)
    primary = _key(saju)
    ref_utc = (ref - _KST_OFFSET).replace(tzinfo=UTC)

    deciding = _SOURCE.term_at_or_before(ref_utc, type=SolarTermType.JEOL)
    term_source = _SOURCE.accuracy_for(deciding.year) if deciding else "computed"
    if term_source == "computed":
        warnings.append(
            ChartWarning(
                code="SOLAR_TERMS_COMPUTED",
                detail="solar term instants outside the bundled KASI 2000-2027 table are "
                "computed by the library (Meeus; library-stated accuracy +-15 min)",
            )
        )

    alts: dict[Key, _Alt] = {}
    combos = [(longitude, 0)] + [(lon, 0) for lon in lon_variants]
    combos += [(lon, s) for lon in [longitude, *lon_variants] for s in shifts]

    def add(key: Key, reasons: set[str], window: str | None = None) -> None:
        alt = alts.setdefault(key, _Alt())
        alt.reasons |= reasons
        if window is not None:
            alt.windows.append(window)

    for lon, shift in combos:
        cause: set[str] = set()
        if lon != longitude:
            cause.add("LONGITUDE_UNKNOWN")
        if shift:
            cause.add("CIVIL_TIME_OFFSET")
        suffix = (f" @lon={lon}" if lon != longitude else "") + (
            f" @offset={shift:+d}m" if shift else ""
        )
        if hour_known:
            if not cause:
                continue
            key = _key(_saju(ref + timedelta(minutes=shift), lon, True, yaja_si_separated))
            if key != primary:
                add(key, _diff_reasons(key, primary) | cause)
            continue
        day_start = datetime.combine(birth.solar_date, time(0, 0))
        by_key: dict[Key, list[int]] = {}
        for minute in range(_MINUTES_PER_DAY):
            moment = day_start + timedelta(minutes=minute + shift)
            key = _key(_saju(moment, lon, False, yaja_si_separated))
            if key != primary:
                by_key.setdefault(key, []).append(minute)
        for key, minutes in by_key.items():
            # A variant only "causes" an alternative the primary combination doesn't produce.
            reasons = _diff_reasons(key, primary) | (cause if key not in alts else set())
            for a, b in _runs(minutes):
                add(key, reasons, f"{_hhmm(a)}-{_hhmm(b)}{suffix}")

    if hour_known:
        span = (ref_utc, ref_utc)
    else:
        day_start_utc = datetime.combine(birth.solar_date, time(0, 0)) - _KST_OFFSET
        day_start_utc = day_start_utc.replace(tzinfo=UTC)
        span = (day_start_utc, day_start_utc + timedelta(minutes=_MINUTES_PER_DAY - 1))
    for term, computed in _nearby_jeols(*span, unknown_time=not hour_known):
        term_kst = (term.datetime + _KST_OFFSET).replace(tzinfo=None)
        for side in (timedelta(minutes=-1), timedelta(minutes=1)):
            other = _key(_saju(term_kst + side, longitude, False, yaja_si_separated))
            if other[:2] != primary[:2]:
                reasons = {"SOLAR_TERM", "SOLAR_TERM_COMPUTED"} if computed else {"SOLAR_TERM"}
                add((other[0], other[1], primary[2], primary[3]), reasons)

    daewoon = _daewoon(saju, birth, hour_known, warnings)
    alternatives = [
        PillarAlternative(
            year_pillar=k[0],
            month_pillar=k[1],
            day_pillar=k[2],
            hour_pillar=k[3],
            reasons=sorted(a.reasons),
            local_windows=a.windows,
        )
        for k, a in sorted(alts.items(), key=lambda kv: (kv[0][:3], kv[0][3] or ""))
    ]
    if alternatives:
        warnings.append(
            ChartWarning(
                code="BOUNDARY_REVIEW_REQUIRED",
                detail=f"{len(alternatives)} alternative pillar set(s) possible; pillars that "
                "differ from an alternative must not be stated definitively",
            )
        )

    return ChartSnapshot(
        policy_version=Settings.MANSE_POLICY_VERSION,
        library_version=korean_saju.__version__,
        solar_date=birth.solar_date.isoformat(),
        birth_time=birth.birth_time.isoformat() if birth.birth_time else None,
        timezone=birth.timezone,
        longitude=longitude,
        gender_for_daewoon=birth.gender_for_daewoon,
        yaja_si_separated=yaja_si_separated,
        solar_term_source=term_source,
        year_pillar=primary[0],
        month_pillar=primary[1],
        day_pillar=primary[2],
        hour_pillar=primary[3],
        ten_gods=_ten_gods(saju),
        daewoon=daewoon,
        sewoon=_sewoon(saju, sewoon_start_year, sewoon_years),
        assumptions=assumptions,
        warnings=warnings,
        alternatives=alternatives,
        certainty="PARTIAL" if alternatives else "CONFIRMED",
    )


_POSITION_NAMES = {
    SajuPosition.YEAR: "year",
    SajuPosition.MONTH: "month",
    SajuPosition.DAY: "day",
    SajuPosition.HOUR: "hour",
}


def _ten_gods(saju: Saju) -> dict[str, str]:
    """Library ten gods vs the day stem: stems (day stem itself excluded) and branch 本氣."""
    analysis = SajuAnalysis(saju)
    gods = {f"{_POSITION_NAMES[p]}_stem": s.hanja for p, s in analysis.cheon_gan_shipsin.items()}
    gods |= {f"{_POSITION_NAMES[p]}_branch": s.hanja for p, s in analysis.ji_ji_shipsin.items()}
    return gods


def _daewoon(
    saju: Saju, birth: NormalizedBirth, hour_known: bool, warnings: list[ChartWarning]
) -> DaewoonFacts:
    gender = Gender.MALE if birth.gender_for_daewoon == "male" else Gender.FEMALE
    dw = Daewoon.compute(saju=saju, gender=gender, solar_terms=_SOURCE, count=DAEWOON_COUNT)
    if not hour_known:
        warnings.append(
            ChartWarning(
                code="DAEWOON_START_APPROXIMATE",
                detail="daewoon start age is measured from the 12:00 reference instant "
                "(birth time unknown; up to about +-2 months)",
            )
        )
    first = dw.entries[0]
    return DaewoonFacts(
        forward=dw.forward,
        start_age=first.start_age,
        start_months_offset=first.start_months_offset,
        entries=[DaewoonEntry(start_age=e.start_age, pillar=e.gan_ji.hanja) for e in dw.entries],
    )


def _sewoon(saju: Saju, start_year: int | None, years: int) -> list[SewoonEntry]:
    if start_year is None:
        return []
    entries = Sewoon.compute(
        saju=saju,
        solar_terms=_SOURCE,
        center_year=start_year,
        years_back=0,
        years_forward=years - 1,
    )
    return [SewoonEntry(year=e.year, age=e.age, pillar=e.gan_ji.hanja) for e in entries]
