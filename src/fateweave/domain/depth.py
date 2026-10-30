"""Chart-level analytics for rules-v3: strength, favorable elements, spouse star, sinsal.

Pure functions of a ChartSnapshot; the evidence builders (rules.py, timing.py, couple.py) wrap
the results into evidence. Every school-dependent choice is named in the `ASSUMPTION` strings
that the builders attach.

- Strength: korean-saju IlganStrengthAnalyzer (10-point scheme: month branch 3.5, day branch 1.5,
  year/hour branch 1.0, each stem 1.0, with 合化/沖/通根 adjustments). With the hour unknown the
  two hour slots (2.0) are missing, so the total is rescaled to 10 before grading. This
  method reads only each branch's surface element, so it ignores roots in hidden stems.
- Strength, rooted/seasonal (rules-v3, Fateweave's method): 月令 by 旺相休囚死 (30), roots
  (通根) of the day stem's 比劫/印星 in the hidden stems of the day branch (15) and the year
  and hour branches (10 each), and supporting stems (10 each, halved when unrooted); the total
  is a percentage of the points available (95, or 75 with the hour unknown).
- Consensus: both methods are reported; when their levels differ the chart is "divergent" and
  the rooted method is primary for 억부 candidates and timing cues.
- Special structures: korean-saju OegyeokAnalyzer over all 16 types (從格, 化氣格, 一行得氣,
  兩神成象); the accepted ones (眞格/假格) are listed, none means 정격.
- 억부 favorable groups: 身強 → 食傷·財星·官星, 身弱 → 印星·比劫, 中和 → none decisive.
- 조후 favorable element: summer month (巳午未) → 水, winter month (亥子丑) → 火, otherwise none
  urgent (a simplified 窮通寶鑑-style season rule).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from korean_saju import GanJi, IlganStrengthAnalyzer, Saju
from korean_saju.saju.oegyeok import OegyeokAnalyzer

from fateweave.domain import tables as t
from fateweave.models.facts import ChartSnapshot

POSITIONS = ("year", "month", "day", "hour")

STRENGTH_ASSUMPTION = (
    "method: korean-saju IlganStrengthAnalyzer 10-point scheme (month branch 3.5, day branch 1.5, "
    "other slots 1.0, 合化/沖/通根 adjustments); other schools weigh differently"
)
STRENGTH_RESCALED = (
    "hour unknown: total over the 8 known points rescaled to 10 (instead of the library's flat "
    "+1.0)"
)
ROOTED_STRENGTH_ASSUMPTION = (
    "method: Fateweave rooted_seasonal_v1 — 月令 旺1.0/相0.8/休0.3/囚0.1/死0 x30, roots in hidden "
    "stems 本氣1.0/中氣0.6/餘氣0.3 (印星 roots x0.8) x15 day branch, x10 year/hour branch, "
    "比劫·印星 stems x10 each (x0.5 unrooted); levels at 75/55/45/25 percent"
)
STRENGTH_DIVERGENT = (
    "the two strength methods disagree; 억부 candidates and timing cues follow rooted_seasonal_v1"
)
SPECIAL_STRUCTURE_ASSUMPTION = (
    "school-dependent: korean-saju 0.3.0 OegyeokAnalyzer criteria for 從格·化氣格·一行得氣·"
    "兩神成象; 眞格 and 假格 count as accepted"
)
EOKBU_ASSUMPTION = (
    "억부 candidates only: 身強 → 食傷·財星·官星, 身弱 → 印星·比劫; 격국·조후·통관·병약 schools "
    "may choose differently"
)
JOHU_ASSUMPTION = (
    "simplified 조후 season rule: 巳午未 month → 水, 亥子丑 month → 火, 寅卯辰·申酉戌 → not urgent"
)
_LEVELS = (  # (minimum total, hanja, hangul) — korean-saju thresholds
    (8.5, "極身強", "극신강"),
    (5.5, "身強", "신강"),
    (4.0, "中和", "중화"),
    (2.0, "身弱", "신약"),
    (float("-inf"), "極身弱", "극신약"),
)
_ROOTED_LEVELS = (  # (minimum percent, hanja)
    (75.0, "極身強"),
    (55.0, "身強"),
    (45.0, "中和"),
    (25.0, "身弱"),
    (float("-inf"), "極身弱"),
)
# 旺相休囚死 of the day element against the month branch element.
_SEASON_STATE = {"旺": 1.0, "相": 0.8, "休": 0.3, "囚": 0.1, "死": 0.0}
_ROOT_ROLE = {"本氣": 1.0, "中氣": 0.6, "餘氣": 0.3}
_INSEONG_ROOT = 0.8
_W_SEASON, _W_DAY_BRANCH, _W_OTHER_BRANCH, _W_STEM = 30.0, 15.0, 10.0, 10.0
_EOKBU_GROUPS = {
    "極身強": ("食傷", "財星", "官星"),
    "身強": ("食傷", "財星", "官星"),
    "中和": (),
    "身弱": ("印星", "比劫"),
    "極身弱": ("印星", "比劫"),
}


def pillars(chart: ChartSnapshot) -> dict[str, str]:
    """Known pillars in position order (hour omitted when unknown)."""
    values = (chart.year_pillar, chart.month_pillar, chart.day_pillar, chart.hour_pillar)
    return {p: v for p, v in zip(POSITIONS, values, strict=True) if v is not None}


def _ganji(hanja: str) -> GanJi:
    ganji = GanJi.from_hanja(hanja)
    if ganji is None:
        raise ValueError(f"invalid pillar in snapshot: {hanja!r}")
    return ganji


def library_saju(chart: ChartSnapshot) -> Saju:
    return Saju(
        year_pillar=_ganji(chart.year_pillar),
        month_pillar=_ganji(chart.month_pillar),
        day_pillar=_ganji(chart.day_pillar),
        hour_pillar=_ganji(chart.hour_pillar) if chart.hour_pillar else None,
        # Required by the dataclass; the analyzers read only the pillars.
        kst_moment=datetime.fromisoformat(chart.solar_date),
        longitude=chart.longitude,
    )


def strength(chart: ChartSnapshot) -> dict[str, Any]:
    b = IlganStrengthAnalyzer.analyze(library_saju(chart))
    if chart.hour_pillar is None:
        # The library adds a flat +1.0 for the missing hour; rescale the known 8 points instead.
        known = b.month_branch_score + b.day_branch_score + b.deuk_sae + b.adjustment
        total = round(max(0.0, min(10.0, known * 10 / 8)), 2)
    else:
        total = round(b.total, 2)
    level = next(hanja for floor, hanja, _ in _LEVELS if total >= floor)
    return {
        "method": "ilgan_strength_10pt",
        "total": total,
        "level": level,
        "deukryeong": round(b.month_branch_score, 2),  # 得令: month branch
        "deukji": round(b.day_branch_score, 2),  # 得地: day branch
        "deukse": round(b.deuk_sae, 2),  # 得勢: the other slots
        "adjustment": round(b.adjustment, 2),
        "birth_time_known": chart.hour_pillar is not None,
    }


def season_state(day_element: str, month_element: str) -> str:
    if day_element == month_element:
        return "旺"
    if t.generates(month_element, day_element):
        return "相"
    if t.generates(day_element, month_element):
        return "休"
    if t.controls(day_element, month_element):
        return "囚"
    return "死"


def strength_rooted(chart: ChartSnapshot) -> dict[str, Any]:
    """Fateweave's rooted/seasonal strength (rooted_seasonal_v1); see ROOTED_STRENGTH_ASSUMPTION."""
    day_stem = chart.day_pillar[0]
    me = t.STEM_ELEMENT[day_stem]
    mother = next(e for e in t.ELEMENT_ORDER if t.generates(e, me))
    ps = pillars(chart)
    state = season_state(me, t.BRANCH_ELEMENT[chart.month_pillar[1]])

    def root(branch: str) -> float:
        best = 0.0
        for stem, role in t.hidden_stems(branch):
            element = t.STEM_ELEMENT[stem]
            if element == me:
                best = max(best, _ROOT_ROLE[role])
            elif element == mother:
                best = max(best, _ROOT_ROLE[role] * _INSEONG_ROOT)
        return best

    branch_elements = {t.STEM_ELEMENT[s] for p in ps.values() for s, _ in t.hidden_stems(p[1])}
    components: dict[str, float] = {
        "season": round(_W_SEASON * _SEASON_STATE[state], 2),
        "day_branch": round(_W_DAY_BRANCH * root(ps["day"][1]), 2),
        "year_branch": round(_W_OTHER_BRANCH * root(ps["year"][1]), 2),
    }
    if "hour" in ps:  # with the hour unknown nothing may reference the hour pillar
        components["hour_branch"] = round(_W_OTHER_BRANCH * root(ps["hour"][1]), 2)
    stems = 0.0
    for pos, pillar in ps.items():
        if pos == "day":
            continue
        element = t.STEM_ELEMENT[pillar[0]]
        if element in (me, mother):
            stems += _W_STEM * (1.0 if element in branch_elements else 0.5)
    components["stems"] = round(stems, 2)
    max_points = _W_SEASON + _W_DAY_BRANCH + _W_OTHER_BRANCH + _W_STEM * 2
    if "hour" in ps:
        max_points += _W_OTHER_BRANCH + _W_STEM
    total = sum(components.values())
    percent = round(total / max_points * 100, 1)
    level = next(hanja for floor, hanja in _ROOTED_LEVELS if percent >= floor)
    return {
        "method": "rooted_seasonal_v1",
        "season_state": state,
        "components": components,
        "total": round(total, 2),
        "max_points": max_points,
        "percent": percent,
        "level": level,
    }


def strength_consensus(chart: ChartSnapshot) -> dict[str, Any]:
    library, rooted = strength(chart), strength_rooted(chart)
    return {
        "method": "consensus",
        "levels": {library["method"]: library["level"], rooted["method"]: rooted["level"]},
        "divergent": library["level"] != rooted["level"],
        "primary": rooted["method"],
        "level": rooted["level"],
    }


def special_structures(chart: ChartSnapshot) -> dict[str, Any]:
    results = OegyeokAnalyzer.analyze_all(library_saju(chart))
    accepted = [
        {
            "type": r.type.hanja,
            "name_ko": r.type.hangul,
            "verdict": r.verdict.name,
            "score": r.score,
        }
        for r in results
        if r.is_accepted
    ]
    return {"checked": len(results), "accepted": accepted}


SEASON_STATE_KO = {"旺": "왕", "相": "상", "休": "휴", "囚": "수", "死": "사"}
VERDICT_KO = {"GENUINE": "진격", "FAKE": "가격"}


def level_ko(level: str) -> str:
    return next(ko for _, hanja, ko in _LEVELS if hanja == level)


def eokbu(chart: ChartSnapshot) -> dict[str, Any]:
    level = strength_consensus(chart)["level"]
    groups = _EOKBU_GROUPS[level]
    day_stem = chart.day_pillar[0]
    return {
        "method": "eokbu",
        "strength_level": level,
        "groups": list(groups),
        "elements": [t.group_element(day_stem, g) for g in groups],
    }


def johu(chart: ChartSnapshot) -> dict[str, Any]:
    branch = chart.month_pillar[1]
    season = t.SEASON[branch]
    need = {"夏": ["水"], "冬": ["火"]}.get(season, [])
    return {"method": "johu_season", "month_branch": branch, "season": season, "elements": need}


def favorable_elements(chart: ChartSnapshot) -> list[str]:
    """억부 candidate elements (empty for 中和); timing cues read only these."""
    return eokbu(chart)["elements"]


def spouse_star(chart: ChartSnapshot) -> dict[str, Any]:
    """Where the spouse star (by gender_for_daewoon) sits: stems, branch 本氣, hidden stems."""
    day_stem = chart.day_pillar[0]
    stars = t.SPOUSE_STARS[chart.gender_for_daewoon]
    visible: list[dict[str, str]] = []
    hidden: list[dict[str, str]] = []
    for pos, pillar in pillars(chart).items():
        stem, branch = pillar
        if pos != "day" and (god := t.ten_god(day_stem, stem)) in stars:
            visible.append({"position": f"{pos}_stem", "value": stem, "ten_god": god})
        for h_stem, role in t.hidden_stems(branch):
            god = t.ten_god(day_stem, h_stem)
            if god not in stars:
                continue
            entry = {"position": f"{pos}_branch", "value": h_stem, "ten_god": god, "role": role}
            (visible if role == "本氣" else hidden).append(entry)
    gods = {e["ten_god"] for e in visible}
    return {
        "gender_for_daewoon": chart.gender_for_daewoon,
        "stars": list(stars),
        "element": t.group_element(
            day_stem, "財星" if chart.gender_for_daewoon == "male" else "官星"
        ),
        "visible": visible,
        "hidden": hidden,
        "visible_count": len(visible),
        "mixed": len(gods) == 2,  # 正·偏 both visible (財星/官星 混雜)
    }


def _found(chart: ChartSnapshot, targets: str, *, skip: str | None = None) -> list[str]:
    return [
        f"{pos}_branch"
        for pos, pillar in pillars(chart).items()
        if pillar[1] in targets and pos != skip
    ]


def sinsal(chart: ChartSnapshot) -> list[dict[str, Any]]:
    """Detected sinsal (only those present). Each item: name, basis, target(s), found positions."""
    ps = pillars(chart)
    day_stem, day_branch = chart.day_pillar
    year_branch = chart.year_pillar[1]
    found: list[dict[str, Any]] = []

    def add(name: str, basis: str, target: str, positions: list[str]) -> None:
        if positions:
            found.append({"sinsal": name, "basis": basis, "target": target, "found": positions})

    for basis_pos, ref in (("year_branch", year_branch), ("day_branch", day_branch)):
        skip = basis_pos.split("_")[0]
        add("桃花", basis_pos, t.dohwa(ref), _found(chart, t.dohwa(ref), skip=skip))
        add("驛馬", basis_pos, t.yeokma(ref), _found(chart, t.yeokma(ref), skip=skip))
        add("華蓋", basis_pos, t.hwagae(ref), _found(chart, t.hwagae(ref), skip=skip))
    add("紅艶", "day_stem", t.HONGYEOM[day_stem], _found(chart, t.HONGYEOM[day_stem]))
    add("天乙貴人", "day_stem", t.CHEONEUL[day_stem], _found(chart, t.CHEONEUL[day_stem]))
    if day_stem in t.YANGIN:
        add("羊刃", "day_stem", t.YANGIN[day_stem], _found(chart, t.YANGIN[day_stem]))
    gosin, gwasuk = t.gosin_gwasuk(year_branch)
    add("孤辰", "year_branch", gosin, _found(chart, gosin, skip="year"))
    add("寡宿", "year_branch", gwasuk, _found(chart, gwasuk, skip="year"))
    baekho = [f"{p}_pillar" for p, v in ps.items() if v in t.BAEKHO_PILLARS]
    add("白虎", "pillar", "甲辰乙未丙戌丁丑戊辰壬戌癸丑", baekho)
    day_only = (
        ("魁罡", t.GOEGANG_PILLARS),
        ("孤鸞", t.GORAN_PILLARS),
        ("陰陽差錯", t.EUMYANG_CHACHAK_PILLARS),
    )
    for name, table in day_only:
        add(
            name,
            "day_pillar",
            chart.day_pillar,
            ["day_pillar"] if chart.day_pillar in table else [],
        )
    return found


SINSAL_KO = {
    "桃花": "도화살",
    "驛馬": "역마살",
    "華蓋": "화개살",
    "紅艶": "홍염살",
    "天乙貴人": "천을귀인",
    "羊刃": "양인살",
    "孤辰": "고신살",
    "寡宿": "과숙살",
    "白虎": "백호살",
    "魁罡": "괴강살",
    "孤鸞": "고란살",
    "陰陽差錯": "음양차착살",
}
SINSAL_MEANING_KO = {
    "桃花": "이성의 눈길을 끄는 매력·인기 (연애운의 대표 신살)",
    "驛馬": "이동·변화·활동성 (원거리 인연, 바쁜 생활)",
    "華蓋": "예술성·종교성·고독을 즐기는 기질",
    "紅艶": "도화보다 짙은 개인적 매력·관능미",
    "天乙貴人": "어려울 때 돕는 사람이 나타나는 길신",
    "羊刃": "강한 추진력과 고집, 극단으로 치닫기 쉬움",
    "孤辰": "배우자 인연이 늦거나 혼자 있는 시간이 많은 기운 (전통적으로 남성에게 강조)",
    "寡宿": "배우자 인연이 늦거나 혼자 있는 시간이 많은 기운 (전통적으로 여성에게 강조)",
    "白虎": "강렬한 기운·급격한 사건, 해당 기둥 육친과의 강한 인연",
    "魁罡": "강한 주관과 결단력, 배우자와 주도권 다툼이 생기기 쉬움",
    "孤鸞": "배우자 인연이 외로울 수 있다는 일주 신살 (전통적으로 여성에게 강조)",
    "陰陽差錯": "처가·시가와의 관계가 엇갈리기 쉽다는 일주 신살",
}
SINSAL_ASSUMPTIONS = {
    "紅艶": t.HONGYEOM_VARIANT,
    "魁罡": t.GOEGANG_VARIANT,
    "桃花": "桃花/驛馬/華蓋 by 三合 group of the basis branch (12신살 年煞·驛馬·華蓋)",
    "驛馬": "桃花/驛馬/華蓋 by 三合 group of the basis branch (12신살 年煞·驛馬·華蓋)",
    "華蓋": "桃花/驛馬/華蓋 by 三合 group of the basis branch (12신살 年煞·驛馬·華蓋)",
    "孤辰": "孤辰/寡宿 by the 方合 group of the year branch",
    "寡宿": "孤辰/寡宿 by the 方合 group of the year branch",
}
