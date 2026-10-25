"""Couple myeongri evidence — policy rules-v1.

`build_couple_evidence(a, b, ...)` returns `build_individual_evidence(a, "A")` +
`build_individual_evidence(b, "B")` + pair evidence (subject key "AB"). Pair evidence reads only
the two snapshots and is order independent: its operands hold the pair as a sorted list of
subject-agnostic {position, value} entries, so swapping a and b yields identical pair IDs and
operands (only the "A"/"B" labels in text_ko swap). Rules, in fixed order:

- COUPLE_DAY_STEM: 天干合 (甲己·乙庚·丙辛·丁壬·戊癸) between the day stems, and 天干沖.
  天干沖 is school-dependent; rules-v1 emits only the four same-axis pairs 甲庚·乙辛·丙壬·丁癸
  (no 戊己 沖) and says so in the item's assumptions.
- COUPLE_DAY_BRANCH: day-branch (spouse palace) 合/沖/刑/破/害 via the rules-v1 pair table.
- COUPLE_CROSS_PILLARS: the same stem and branch tables across every other pillar pair.
- COUPLE_YEAR_WINDOW: years in [start_year, start_year + years) where one mechanical condition
  holds for both people (see YEAR_CONDITIONS). It lists traditional timing cues only; it never
  picks a marriage year and never scores or predicts.

Unknown hour on either side: no pair evidence references an hour pillar. PARTIAL charts: pair
items that depend on a pillar differing among that person's alternatives carry
BOUNDARY_ASSUMPTION. No score, verdict or probability field exists.
"""

from __future__ import annotations

from itertools import product
from typing import Any

from korean_saju import CheonGan, GanJi, ShipsinCalculator

from fateweave.domain.rules import (
    _PAIR_RELATIONS,
    _POS_KO,
    BOUNDARY_ASSUMPTION,
    POSITIONS,
    _differing_positions,
    _Draft,
    _pillars,
    _rules_ref,
    build_individual_evidence,
    canonical_json,
    evidence_id,
)
from fateweave.models.facts import ChartSnapshot, Evidence

COUPLE_RULE_ORDER: tuple[str, ...] = (
    "COUPLE_DAY_STEM",
    "COUPLE_DAY_BRANCH",
    "COUPLE_CROSS_PILLARS",
    "COUPLE_YEAR_WINDOW",
)
PAIR_SUBJECT_KEY = "AB"
MAX_WINDOW_YEARS = 30
TIMING_ASSUMPTION = "traditional timing cue; not a prediction of marriage"
_STEM_CHUNG_ASSUMPTION = (
    "school-dependent: 天干沖 limited to 甲庚·乙辛·丙壬·丁癸 (戊己 沖 not used)"
)
_SPOUSE_STAR_ASSUMPTION = (
    "school-dependent: spouse star by gender_for_daewoon — male 正財/偏財, female 正官/偏官"
)
_YEAR_PILLAR_ASSUMPTION = "year pillar applies from 立春 of that year, not from January 1"

# (relation, Korean label, member stems) — rules-v1 traditional stem tables.
_STEM_RELATIONS: tuple[tuple[str, str, str], ...] = (
    *(("合", "천간합", m) for m in ("甲己", "乙庚", "丙辛", "丁壬", "戊癸")),
    *(("沖", "천간충", m) for m in ("甲庚", "乙辛", "丙壬", "丁癸")),
)
_SPOUSE_STARS = {"male": ("正財", "偏財"), "female": ("正官", "偏官")}
_GENDER_KO = {"male": "남", "female": "여"}
_SEXAGENARY_BASE_YEAR = 1984  # 甲子

# YEAR_WINDOW conditions, each evaluated per person against that year's pillar:
# - SEWOON_STEM_SPOUSE_STAR: the year stem is the person's spouse star (ten god vs day stem).
# - SEWOON_BRANCH_HAP_SPOUSE_PALACE: the year branch forms 六合 with the person's day branch.
YEAR_CONDITIONS: tuple[str, ...] = (
    "SEWOON_STEM_SPOUSE_STAR",
    "SEWOON_BRANCH_HAP_SPOUSE_PALACE",
)

Labelled = tuple[str, ChartSnapshot]  # (subject label, chart)


def _validate_window(start_year: Any, years: Any) -> None:
    if type(start_year) is not int:
        raise ValueError(f"start_year must be an int; got {start_year!r}")
    if type(years) is not int or not 1 <= years <= MAX_WINDOW_YEARS:
        raise ValueError(f"years must be an int in 1..{MAX_WINDOW_YEARS}; got {years!r}")


def _entries(*items: dict[str, Any]) -> list[dict[str, Any]]:
    """Subject-agnostic, order-independent representation of the pair."""
    return sorted(items, key=canonical_json)


def _relations(
    table: tuple[tuple[str, str, str], ...], x: str, y: str
) -> list[tuple[str, str, str]]:
    return [(rel, label, m) for rel, label, m in table if sorted(x + y) == sorted(m)]


_PARTS = {
    "stem": (0, "간", _STEM_RELATIONS),
    "branch": (1, "지", _PAIR_RELATIONS),
}
Drafts = list[tuple[_Draft, dict[str, frozenset[str]]]]  # draft, positions it depends on


def _pair_drafts(
    a: Labelled,
    b: Labelled,
    positions: list[tuple[str, str]],
    parts: tuple[str, ...],
    source: str,
) -> Drafts:
    """Stem and/or branch relations for each (A position, B position) pair."""
    (la, ca), (lb, cb) = a, b
    pa, pb = _pillars(ca), _pillars(cb)
    drafts: Drafts = []
    for pos_a, pos_b in positions:
        for part in parts:
            idx, part_ko, table = _PARTS[part]
            va, vb = pa[pos_a][idx], pb[pos_b][idx]
            for relation, label, members in _relations(table, va, vb):
                name = f"{members}{relation}"
                where = f"{la} {_POS_KO[pos_a]}{part_ko} {va} · {lb} {_POS_KO[pos_b]}{part_ko} {vb}"
                school = part == "stem" and relation == "沖"
                assumptions = (_STEM_CHUNG_ASSUMPTION,) if school else ()
                draft = _Draft(
                    kind="rule_derived",
                    operands={
                        "relation": relation,
                        "name": name,
                        "entries": _entries(
                            {"position": f"{pos_a}_{part}", "value": va},
                            {"position": f"{pos_b}_{part}", "value": vb},
                        ),
                    },
                    text_ko=f"{where}: {label}({name}) 관계",
                    source_ref=source,
                    assumptions=assumptions,
                )
                drafts.append((draft, {la: frozenset({pos_a}), lb: frozenset({pos_b})}))
    return drafts


def _day_stem_rule(a: Labelled, b: Labelled) -> Drafts:
    return _pair_drafts(a, b, [("day", "day")], ("stem",), _rules_ref("COUPLE_DAY_STEM"))


def _day_branch_rule(a: Labelled, b: Labelled) -> Drafts:
    return _pair_drafts(a, b, [("day", "day")], ("branch",), _rules_ref("COUPLE_DAY_BRANCH"))


def _cross_pillars_rule(a: Labelled, b: Labelled) -> Drafts:
    # Hour pillars are left out entirely when either hour is unknown.
    hour_known = a[1].hour_pillar is not None and b[1].hour_pillar is not None
    positions = [p for p in POSITIONS if hour_known or p != "hour"]
    pairs = [(x, y) for x, y in product(positions, positions) if (x, y) != ("day", "day")]
    return _pair_drafts(a, b, pairs, ("stem", "branch"), _rules_ref("COUPLE_CROSS_PILLARS"))


def _year_pillar(year: int, charts: tuple[ChartSnapshot, ...]) -> str:
    pillar = GanJi.by_index((year - _SEXAGENARY_BASE_YEAR) % 60).hanja
    for chart in charts:  # cross-check against snapshot sewoon where it covers the year
        for entry in chart.sewoon:
            if entry.year == year and entry.pillar != pillar:
                raise RuntimeError(f"sewoon mismatch for {year}: {entry.pillar} != {pillar}")
    return pillar


def _ten_god(day_stem: str, target: str) -> str:
    day, other = CheonGan.from_hanja(day_stem), CheonGan.from_hanja(target)
    if day is None or other is None:
        raise ValueError(f"invalid stem: {day_stem!r} / {target!r}")
    return ShipsinCalculator.for_cheon_gan(day, other).hanja


def _year_check(condition: str, chart: ChartSnapshot, pillar: str) -> dict[str, Any] | None:
    day_stem, day_branch = chart.day_pillar
    if condition == "SEWOON_STEM_SPOUSE_STAR":
        god = _ten_god(day_stem, pillar[0])
        gender = chart.gender_for_daewoon
        if god not in _SPOUSE_STARS[gender]:
            return None
        return {"day_stem": day_stem, "gender_for_daewoon": gender, "ten_god": god}
    hap = [m for rel, _, m in _relations(_PAIR_RELATIONS, pillar[1], day_branch) if rel == "合"]
    return {"day_branch": day_branch, "name": f"{hap[0]}合"} if hap else None


def _year_text(condition: str, label: str, check: dict[str, Any], pillar: str) -> str:
    if condition == "SEWOON_STEM_SPOUSE_STAR":
        gender = _GENDER_KO[check["gender_for_daewoon"]]
        return (
            f"{label} 일간 {check['day_stem']} 기준 세운 천간 {pillar[0]} = {check['ten_god']}"
            f"({gender}명 배우자성)"
        )
    return f"{label} 일지 {check['day_branch']} · 세운 지지 {pillar[1]}: 육합({check['name']})"


def _year_window_rule(a: Labelled, b: Labelled, start_year: int, years: int) -> Drafts:
    (la, ca), (lb, cb) = a, b
    drafts: Drafts = []
    for year in range(start_year, start_year + years):
        pillar = _year_pillar(year, (ca, cb))
        for condition in YEAR_CONDITIONS:
            check_a = _year_check(condition, ca, pillar)
            check_b = _year_check(condition, cb, pillar)
            if check_a is None or check_b is None:
                continue
            extra = (
                (_SPOUSE_STAR_ASSUMPTION,) if condition == "SEWOON_STEM_SPOUSE_STAR" else ()
            )
            text_a = _year_text(condition, la, check_a, pillar)
            text_b = _year_text(condition, lb, check_b, pillar)
            draft = _Draft(
                kind="rule_derived",
                operands={
                    "condition": condition,
                    "year": year,
                    "year_pillar": pillar,
                    "entries": _entries(check_a, check_b),
                },
                text_ko=f"{year}년 세운 {pillar}: {text_a} · {text_b}",
                source_ref=f"{_rules_ref('COUPLE_YEAR_WINDOW')}:{condition}"
                f" (year pillar by 60-cycle, {_SEXAGENARY_BASE_YEAR}=甲子)",
                assumptions=(TIMING_ASSUMPTION, _YEAR_PILLAR_ASSUMPTION, *extra),
            )
            drafts.append((draft, {la: frozenset({"day"}), lb: frozenset({"day"})}))
    return drafts


def build_couple_evidence(
    a: ChartSnapshot, b: ChartSnapshot, start_year: int, years: int = 10
) -> list[Evidence]:
    """Individual catalogs for A and B, then pair evidence sorted by rule order then id."""
    _validate_window(start_year, years)
    la, lb = ("A", a), ("B", b)
    differing = {"A": _differing_positions(a), "B": _differing_positions(b)}
    rules = {
        "COUPLE_DAY_STEM": _day_stem_rule(la, lb),
        "COUPLE_DAY_BRANCH": _day_branch_rule(la, lb),
        "COUPLE_CROSS_PILLARS": _cross_pillars_rule(la, lb),
        "COUPLE_YEAR_WINDOW": _year_window_rule(la, lb, start_year, years),
    }
    assert tuple(rules) == COUPLE_RULE_ORDER

    # Equal operands are one fact (e.g. A年·B月 and A月·B年 holding the same values): keep the
    # first draft, and flag the boundary if any merged draft depends on one, so the result
    # does not depend on argument order.
    merged: dict[str, tuple[str, _Draft, bool]] = {}
    for code, drafts in rules.items():
        for draft, depends in drafts:
            item_id = evidence_id(PAIR_SUBJECT_KEY, code, draft.operands)
            flagged = any(depends[s] & differing[s] for s in depends)
            if item_id in merged:
                first_code, first, was_flagged = merged[item_id]
                merged[item_id] = (first_code, first, was_flagged or flagged)
            else:
                merged[item_id] = (code, draft, flagged)

    pair = [
        Evidence(
            id=item_id,
            kind=draft.kind,
            rule_code=code,
            operands=draft.operands,
            text_ko=draft.text_ko,
            source_ref=draft.source_ref,
            assumptions=[*draft.assumptions, *([BOUNDARY_ASSUMPTION] if flagged else [])],
        )
        for item_id, (code, draft, flagged) in merged.items()
    ]

    individual = build_individual_evidence(a, "A") + build_individual_evidence(b, "B")
    ordered = sorted(pair, key=lambda e: (COUPLE_RULE_ORDER.index(e.rule_code), e.id))
    evidence = individual + ordered
    ids = [e.id for e in evidence]
    if len(ids) != len(set(ids)):
        raise RuntimeError("evidence id collision: operands must distinguish items")
    return evidence
