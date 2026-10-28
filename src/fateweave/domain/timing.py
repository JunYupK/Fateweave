"""Marriage-timing cues for rules-v2: daewoon flow, year-by-year and month-by-month signals.

Traditional timing methods (widely taught in Korean myeongri) look for years and months when the
spouse star appears, when the spouse palace (day branch) is combined, when the day stem is
combined, when 桃花/紅艶 is touched, and when the running daewoon supports these. This module
evaluates those conditions mechanically and lists them as named cues. It never predicts a
marriage: a cue is a traditional reading trigger, and the ranking only orders years by how many
core cues they carry.

Cue codes (per person, for a year or month pillar):
- SPOUSE_STAR_STEM / SPOUSE_STAR_BRANCH: the stem / branch 本氣 is the spouse star.
- DAY_STEM_HAP: the stem forms 天干合 with the day stem.
- SPOUSE_PALACE_HAP: the branch forms 六合 with the day branch.
- SPOUSE_PALACE_SAMHAP: the branch shares the day branch's 三合 group (半合 or more).
- SPOUSE_PALACE_SAME_TEN_GOD: the branch 本氣 has the day branch's ten god.
- DOHWA: the branch is 桃花 of the year or day branch. HONGYEOM: the branch is the 紅艶 branch.
- DAEWOON_SPOUSE_STAR / DAEWOON_PALACE_HAP: the daewoon running that year carries the spouse
  star / combines (六合 or same 三合 group) with the day branch (years only).
- EOKBU_FAVORABLE: the stem or branch element is an 억부 candidate element (years only).
Caution codes: PALACE_CHUNG, PALACE_HYEONG, PALACE_WONJIN (the branch clashes, punishes or
resents the day branch) and RIVAL_STAR (male: 比劫 stem, a rival for the 財星; female: 傷官
stem, 傷官見官).
"""

from __future__ import annotations

from typing import Any

from korean_saju import GanJi

from fateweave.domain import depth
from fateweave.domain import tables as t
from fateweave.models.facts import ChartSnapshot

SEXAGENARY_BASE_YEAR = 1984  # 甲子
DAEWOON_UNAVAILABLE = "unavailable"
TIMING_ASSUMPTION = "traditional timing cue; not a prediction of marriage"
YEAR_PILLAR_ASSUMPTION = "year pillar applies from 立春 of that year, not from January 1"
MONTH_ASSUMPTION = (
    "month pillars by 五虎遁; month starts are typical 節入 dates and can differ by 1-2 days"
)
RANK_ASSUMPTION = "rank orders years by core cue count, then all cues, then year; not a likelihood"

CORE_CUES = (
    "SPOUSE_STAR_STEM",
    "SPOUSE_STAR_BRANCH",
    "DAY_STEM_HAP",
    "SPOUSE_PALACE_HAP",
    "SPOUSE_PALACE_SAMHAP",
)
CUE_KO = {
    "SPOUSE_STAR_STEM": "배우자성 천간",
    "SPOUSE_STAR_BRANCH": "배우자성 지지",
    "DAY_STEM_HAP": "일간 합",
    "SPOUSE_PALACE_HAP": "배우자궁 육합",
    "SPOUSE_PALACE_SAMHAP": "배우자궁 삼합",
    "SPOUSE_PALACE_SAME_TEN_GOD": "배우자궁과 같은 십성",
    "DOHWA": "도화",
    "HONGYEOM": "홍염",
    "DAEWOON_SPOUSE_STAR": "대운 배우자성",
    "DAEWOON_PALACE_HAP": "대운-배우자궁 합",
    "EOKBU_FAVORABLE": "억부 희용 오행",
    "PALACE_CHUNG": "배우자궁 충",
    "PALACE_HYEONG": "배우자궁 형",
    "PALACE_WONJIN": "배우자궁 원진",
    "RIVAL_STAR": "경쟁·견제 십성",
}
# 寅月 … 丑月 with typical 節入 (month-day) dates; 丑月 falls in January of the next year.
_MONTHS = tuple(
    zip(
        "寅卯辰巳午未申酉戌亥子丑",
        (
            "02-04",
            "03-06",
            "04-05",
            "05-06",
            "06-06",
            "07-07",
            "08-08",
            "09-08",
            "10-08",
            "11-07",
            "12-07",
            "01-06",
        ),
        strict=True,
    )
)
_TIGER_MONTH_STEM = {
    "甲": "丙",
    "己": "丙",
    "乙": "戊",
    "庚": "戊",
    "丙": "庚",
    "辛": "庚",
    "丁": "壬",
    "壬": "壬",
    "戊": "甲",
    "癸": "甲",
}
_START_TOLERANCE_MONTHS = 1  # day-of-month and the library's month rounding
_APPROXIMATE_EXTRA_MONTHS = 2  # DAEWOON_START_APPROXIMATE: up to about +-2 months


def year_pillar(year: int, charts: tuple[ChartSnapshot, ...] = ()) -> str:
    pillar = GanJi.by_index((year - SEXAGENARY_BASE_YEAR) % 60).hanja
    for chart in charts:  # cross-check against snapshot sewoon where it covers the year
        for entry in chart.sewoon:
            if entry.year == year and entry.pillar != pillar:
                raise RuntimeError(f"sewoon mismatch for {year}: {entry.pillar} != {pillar}")
    return pillar


def month_pillars(year_pillar_hanja: str) -> list[tuple[str, str]]:
    """(pillar, approximate start MM-DD) for 寅月 … 丑月 of the given year pillar."""
    first = t.STEMS.index(_TIGER_MONTH_STEM[year_pillar_hanja[0]])
    return [
        (t.STEMS[(first + i) % 10] + branch, start) for i, (branch, start) in enumerate(_MONTHS)
    ]


def daewoon_timeline(chart: ChartSnapshot, year: int) -> list[str]:
    """Daewoon pillars possibly active during `year`, chronologically.

    Ages count from the birth month (start_age years after birth, as korean-saju derives them).
    Entry i starts between `start_age_i*12` months and `start_age_i*12 + start_months_offset`
    months after the birth month (the library applies the offset to the first entry only; the
    later entries are ambiguous between the two conventions), widened by a tolerance. A year
    touched by an uncertain start lists both pillars. Parts of the year before the first entry
    or after the last entry's ten years are DAEWOON_UNAVAILABLE.
    """
    dw = chart.daewoon
    birth_year, birth_month = int(chart.solar_date[:4]), int(chart.solar_date[5:7])
    base = birth_year * 12 + birth_month - 1
    tol = _START_TOLERANCE_MONTHS
    if "DAEWOON_START_APPROXIMATE" in chart.warning_codes:
        tol += _APPROXIMATE_EXTRA_MONTHS
    starts = [e.start_age for e in dw.entries]
    if starts:
        starts.append(starts[-1] + 10)  # end of the last entry
    windows = [
        (
            base + age * 12 + (dw.start_months_offset if i == 0 else 0) - tol,
            base + age * 12 + dw.start_months_offset + tol,
        )
        for i, age in enumerate(starts)
    ]
    first, last = year * 12, year * 12 + 11
    if not windows:
        return [DAEWOON_UNAVAILABLE]
    timeline = [DAEWOON_UNAVAILABLE] if first <= windows[0][1] else []
    for i, entry in enumerate(dw.entries):
        if windows[i][0] <= last and windows[i + 1][1] >= first:
            timeline.append(entry.pillar)
    if last >= windows[-1][0]:
        timeline.append(DAEWOON_UNAVAILABLE)
    return timeline


def natal_relations(chart: ChartSnapshot, pillar: str) -> list[dict[str, Any]]:
    """Relations of an incoming pillar (daewoon, year, month) with the natal chart."""
    ps = depth.pillars(chart)
    stem, branch = pillar
    found: list[dict[str, Any]] = []
    for pos, natal in ps.items():
        for rel, _, members in t.pair_relations(branch, natal[1]):
            found.append({"with": f"{pos}_branch", "relation": rel, "name": f"{members}{rel}"})
        for rel, _, members in t.stem_relations(stem, natal[0]):
            found.append({"with": f"{pos}_stem", "relation": rel, "name": f"{members}{rel}"})
    natal_branches = [(pos, p[1]) for pos, p in ps.items()]
    for rel, _, members in t.TRIPLE_RELATIONS:
        if branch not in members:
            continue
        rest = members.replace(branch, "", 1)
        hits = [next((pos for pos, b in natal_branches if b == r), None) for r in rest]
        if all(hits):
            found.append(
                {
                    "with": "+".join(f"{h}_branch" for h in hits),
                    "relation": rel,
                    "name": f"{members}{rel}",
                }
            )
    return found


def _is_spouse_star(chart: ChartSnapshot, pillar: str) -> bool:
    day_stem = chart.day_pillar[0]
    stars = t.SPOUSE_STARS[chart.gender_for_daewoon]
    return t.ten_god(day_stem, pillar[0]) in stars or t.branch_ten_god(day_stem, pillar[1]) in stars


def _palace_hap(day_branch: str, branch: str) -> bool:
    six = any(rel == "合" for rel, _, _ in t.pair_relations(branch, day_branch))
    return six or (branch != day_branch and t.samhap_group(branch) == t.samhap_group(day_branch))


def signals(
    chart: ChartSnapshot,
    pillar: str,
    *,
    daewoon: list[str] | None = None,
    favorable: list[str] | None = None,
) -> dict[str, Any]:
    """Ten gods, cues and cautions of an incoming pillar for one person.

    `daewoon` (active daewoon pillars) and `favorable` (억부 elements) add the year-only cues.
    """
    day_stem, day_branch = chart.day_pillar
    stem, branch = pillar
    stars = t.SPOUSE_STARS[chart.gender_for_daewoon]
    stem_god = t.ten_god(day_stem, stem)
    branch_god = t.branch_ten_god(day_stem, branch)
    palace = [rel for rel, _, _ in t.pair_relations(branch, day_branch)]
    cues: list[str] = []
    if stem_god in stars:
        cues.append("SPOUSE_STAR_STEM")
    if branch_god in stars:
        cues.append("SPOUSE_STAR_BRANCH")
    if any(rel == "合" for rel, _, _ in t.stem_relations(stem, day_stem)):
        cues.append("DAY_STEM_HAP")
    if "合" in palace:
        cues.append("SPOUSE_PALACE_HAP")
    if branch != day_branch and t.samhap_group(branch) == t.samhap_group(day_branch):
        cues.append("SPOUSE_PALACE_SAMHAP")
    if branch_god == chart.ten_gods["day_branch"]:
        cues.append("SPOUSE_PALACE_SAME_TEN_GOD")
    if branch in {t.dohwa(chart.year_pillar[1]), t.dohwa(day_branch)}:
        cues.append("DOHWA")
    if branch == t.HONGYEOM[day_stem]:
        cues.append("HONGYEOM")
    running = [p for p in daewoon or [] if p != DAEWOON_UNAVAILABLE]
    if any(_is_spouse_star(chart, p) for p in running):
        cues.append("DAEWOON_SPOUSE_STAR")
    if any(_palace_hap(day_branch, p[1]) for p in running):
        cues.append("DAEWOON_PALACE_HAP")
    if favorable and (t.STEM_ELEMENT[stem] in favorable or t.BRANCH_ELEMENT[branch] in favorable):
        cues.append("EOKBU_FAVORABLE")

    cautions: list[str] = []
    if "沖" in palace:
        cautions.append("PALACE_CHUNG")
    triple_hyeong = any(
        r["relation"] == "三刑" and "day_branch" in r["with"]
        for r in natal_relations(chart, pillar)
    )
    if "刑" in palace or triple_hyeong:
        cautions.append("PALACE_HYEONG")
    if "怨嗔" in palace:
        cautions.append("PALACE_WONJIN")
    rival = ("比肩", "劫財") if chart.gender_for_daewoon == "male" else ("傷官",)
    if stem_god in rival:
        cautions.append("RIVAL_STAR")
    return {
        "stem_ten_god": stem_god,
        "branch_ten_god": branch_god,
        "cues": cues,
        "cautions": cautions,
        "core_count": sum(c in CORE_CUES for c in cues),
        "cue_count": len(cues),
    }


def cues_ko(codes: list[str]) -> str:
    return ", ".join(CUE_KO[c] for c in codes) if codes else "없음"


def year_rows(chart: ChartSnapshot, start_year: int, years: int) -> list[dict[str, Any]]:
    """One row per year with signals, the running daewoon and a rank (1 = most core cues)."""
    favorable = depth.favorable_elements(chart)
    rows = []
    for year in range(start_year, start_year + years):
        pillar = year_pillar(year, (chart,))
        timeline = daewoon_timeline(chart, year)
        sig = signals(chart, pillar, daewoon=timeline, favorable=favorable)
        rows.append(
            {
                "year": year,
                "pillar": pillar,
                "daewoon": timeline,
                "relations": natal_relations(chart, pillar),
                **sig,
            }
        )
    order = sorted(rows, key=lambda r: (-r["core_count"], -r["cue_count"], r["year"]))
    for rank, row in enumerate(order, start=1):
        row["rank"] = rank
    return rows


def top_years(rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda r: r["rank"])
    return [r for r in ranked if r["core_count"] > 0][:limit]


def month_rows(chart: ChartSnapshot, year_pillar_hanja: str) -> list[dict[str, Any]]:
    rows = []
    for pillar, start in month_pillars(year_pillar_hanja):
        sig = signals(chart, pillar)
        rows.append(
            {
                "month_branch": pillar[1],
                "pillar": pillar,
                "starts": start,
                "cues": sig["cues"],
                "cautions": sig["cautions"],
            }
        )
    return rows
