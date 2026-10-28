"""Couple myeongri evidence — policy rules-v2.

`build_couple_evidence(a, b, ...)` returns `build_individual_evidence(a, "A")` +
`build_individual_evidence(b, "B")` + pair evidence (subject key "AB"). Pair evidence reads only
the two snapshots and is order independent: its operands hold the pair as a sorted list of
subject-agnostic entries, so swapping a and b yields identical pair IDs and operands (only the
"A"/"B" labels in text_ko swap). Rules, in fixed order:

- COUPLE_DAY_STEM: 天干合 / 天干沖 between the day stems (天干沖 limited to the four same-axis
  pairs 甲庚·乙辛·丙壬·丁癸, stated in the item's assumptions).
- COUPLE_DAY_BRANCH: day-branch (spouse palace) 合/沖/刑/破/害/怨嗔/鬼門 via the pair table.
- COUPLE_CROSS_PILLARS: the same stem and branch tables across every other pillar pair (the
  year-branch pair is the 띠 궁합).
- COUPLE_DAY_STEM_ELEMENT: 相生 / 相剋 / 比和 between the two day-stem elements.
- COUPLE_SPOUSE_STAR_MATCH: for each person, the ten god of the partner's day stem and day
  branch (本氣) and whether it is that person's spouse star.
- COUPLE_ELEMENT_COMPLEMENT: for each person, the surface elements they lack that the partner
  has, and how many of the partner's surface characters carry their 억부/조후 candidate elements.
- COUPLE_TIMING: every window year with both people's marriage-timing cues (timing.py) and a
  joint rank (years where both carry core cues first). It never picks a marriage year.
- COUPLE_LUCK_OVERLAP: a record only — for every window year, the year pillar and each
  person's daewoon pillar(s) active during it.

Unknown hour on either side: no pair evidence references an hour pillar. PARTIAL charts: pair
items that depend on a pillar differing among that person's alternatives carry
BOUNDARY_ASSUMPTION. No score, verdict or probability field exists.
"""

from __future__ import annotations

from itertools import product
from typing import Any

from fateweave.domain import depth, timing
from fateweave.domain import tables as t
from fateweave.domain.glossary import ELEMENT_KO, hangul
from fateweave.domain.rules import (
    _POS_KO,
    BOUNDARY_ASSUMPTION,
    DAEWOON_PRIMARY_ONLY,
    DAEWOON_START_APPROXIMATE,
    POSITIONS,
    _differing_positions,
    _Draft,
    _pillars,
    _rules_ref,
    build_individual_evidence,
    canonical_json,
    evidence_id,
    sort_key,
)
from fateweave.models.facts import ChartSnapshot, Evidence

COUPLE_RULE_ORDER: tuple[str, ...] = (
    "COUPLE_DAY_STEM",
    "COUPLE_DAY_BRANCH",
    "COUPLE_CROSS_PILLARS",
    "COUPLE_DAY_STEM_ELEMENT",
    "COUPLE_SPOUSE_STAR_MATCH",
    "COUPLE_ELEMENT_COMPLEMENT",
    "COUPLE_TIMING",
    "COUPLE_LUCK_OVERLAP",
)
PAIR_SUBJECT_KEY = "AB"
MAX_WINDOW_YEARS = 30
TIMING_ASSUMPTION = timing.TIMING_ASSUMPTION
JOINT_RANK_ASSUMPTION = (
    "joint rank orders years by: both have core cues, then total core cues, then all cues, "
    "then year; not a likelihood"
)
TRANSITION_ASSUMPTION = "daewoon transition year; boundary depends on start age convention"
DAEWOON_UNAVAILABLE = timing.DAEWOON_UNAVAILABLE
_daewoon_timeline = timing.daewoon_timeline
_SEXAGENARY_BASE_YEAR = timing.SEXAGENARY_BASE_YEAR
_GENDER_KO = {"male": "남", "female": "여"}

Labelled = tuple[str, ChartSnapshot]  # (subject label, chart)


def _ko(text: str) -> str:
    return hangul(text)


def _validate_window(start_year: Any, years: Any) -> None:
    if type(start_year) is not int:
        raise ValueError(f"start_year must be an int; got {start_year!r}")
    if type(years) is not int or not 1 <= years <= MAX_WINDOW_YEARS:
        raise ValueError(f"years must be an int in 1..{MAX_WINDOW_YEARS}; got {years!r}")


def _entries(*items: dict[str, Any]) -> list[dict[str, Any]]:
    """Subject-agnostic, order-independent representation of the pair."""
    return sorted(items, key=canonical_json)


_PARTS = {
    "stem": (0, "간", t.STEM_RELATIONS),
    "branch": (1, "지", t.PAIR_RELATIONS),
}
Drafts = list[tuple[_Draft, dict[str, frozenset[str]]]]  # draft, positions it depends on


def _relations(
    table: tuple[tuple[str, str, str], ...], x: str, y: str
) -> list[tuple[str, str, str]]:
    return [(rel, label, m) for rel, label, m in table if sorted(x + y) == sorted(m)]


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
                where = (
                    f"{la} {_POS_KO[pos_a]}{part_ko} {_ko(va)} · "
                    f"{lb} {_POS_KO[pos_b]}{part_ko} {_ko(vb)}"
                )
                school = part == "stem" and relation == "沖"
                assumptions = (t.STEM_CHUNG_ASSUMPTION,) if school else ()
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
                    text_ko=f"{where}: {label}({_ko(name)}) 관계",
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


def _day_stem_element_rule(a: Labelled, b: Labelled) -> Drafts:
    (la, ca), (lb, cb) = a, b
    sa, sb = ca.day_pillar[0], cb.day_pillar[0]
    ea, eb = t.STEM_ELEMENT[sa], t.STEM_ELEMENT[sb]
    if ea == eb:
        relation, src, dst = "比和", ea, eb
        text = f"두 사람 모두 {ELEMENT_KO[ea]} 일간 — 같은 기운(비화)"
    else:
        for x, y, lx, ly in ((ea, eb, la, lb), (eb, ea, lb, la)):
            if t.generates(x, y):
                relation, src, dst = "相生", x, y
                text = f"{ELEMENT_KO[x]}생{ELEMENT_KO[y]} — {lx}가 {ly}를 생해 주는 관계(상생)"
                break
            if t.controls(x, y):
                relation, src, dst = "相剋", x, y
                text = f"{ELEMENT_KO[x]}극{ELEMENT_KO[y]} — {lx}가 {ly}를 극하는 관계(상극)"
                break
    draft = _Draft(
        kind="rule_derived",
        operands={
            "relation": relation,
            "from": src,
            "to": dst,
            "entries": _entries({"day_stem": sa, "element": ea}, {"day_stem": sb, "element": eb}),
        },
        text_ko=f"{la} 일간 {_ko(sa)}({ELEMENT_KO[ea]}) · {lb} 일간 {_ko(sb)}({ELEMENT_KO[eb]}): "
        f"{text}",
        source_ref=_rules_ref("COUPLE_DAY_STEM_ELEMENT"),
    )
    return [(draft, {la: frozenset({"day"}), lb: frozenset({"day"})})]


def _star_entry(me: ChartSnapshot, partner: ChartSnapshot) -> dict[str, Any]:
    day_stem = me.day_pillar[0]
    stars = t.SPOUSE_STARS[me.gender_for_daewoon]
    stem_god = t.ten_god(day_stem, partner.day_pillar[0])
    branch_god = t.branch_ten_god(day_stem, partner.day_pillar[1])
    return {
        "day_stem": day_stem,
        "gender_for_daewoon": me.gender_for_daewoon,
        "partner_day_pillar": partner.day_pillar,
        "partner_stem_ten_god": stem_god,
        "partner_branch_ten_god": branch_god,
        "stem_is_spouse_star": stem_god in stars,
        "branch_is_spouse_star": branch_god in stars,
    }


def _star_text(label: str, other: str, e: dict[str, Any]) -> str:
    def mark(flag: bool) -> str:
        return "(배우자성)" if flag else ""

    return (
        f"{label}({_GENDER_KO[e['gender_for_daewoon']]}) 기준 {other}의 일간은 "
        f"{_ko(e['partner_stem_ten_god'])}{mark(e['stem_is_spouse_star'])}, 일지는 "
        f"{_ko(e['partner_branch_ten_god'])}{mark(e['branch_is_spouse_star'])}"
    )


def _spouse_star_match_rule(a: Labelled, b: Labelled) -> Drafts:
    (la, ca), (lb, cb) = a, b
    ea, eb = _star_entry(ca, cb), _star_entry(cb, ca)
    draft = _Draft(
        kind="rule_derived",
        operands={"entries": _entries(ea, eb)},
        text_ko=f"{_star_text(la, lb, ea)}; {_star_text(lb, la, eb)}",
        source_ref=_rules_ref("COUPLE_SPOUSE_STAR_MATCH"),
        assumptions=(t.SPOUSE_STAR_ASSUMPTION,),
    )
    return [(draft, {la: frozenset({"day"}), lb: frozenset({"day"})})]


def _surface(chart: ChartSnapshot) -> dict[str, int]:
    counts = dict.fromkeys(t.ELEMENT_ORDER, 0)
    for pillar in _pillars(chart).values():
        counts[t.STEM_ELEMENT[pillar[0]]] += 1
        counts[t.BRANCH_ELEMENT[pillar[1]]] += 1
    return counts


def _complement_entry(me: ChartSnapshot, partner: ChartSnapshot) -> dict[str, Any]:
    mine, theirs = _surface(me), _surface(partner)
    lacking = [e for e, n in mine.items() if n == 0]
    favorable = sorted(
        set(depth.favorable_elements(me)) | set(depth.johu(me)["elements"]),
        key=t.ELEMENT_ORDER.index,
    )
    return {
        "day_stem": me.day_pillar[0],
        "lacking": lacking,
        "partner_has": [e for e in lacking if theirs[e] > 0],
        "favorable": favorable,
        "partner_favorable_count": sum(theirs[e] for e in favorable),
    }


def _complement_text(label: str, other: str, e: dict[str, Any]) -> str:
    def names(items: list[str]) -> str:
        return "·".join(ELEMENT_KO[x] for x in items) or "없음"

    if e["lacking"]:
        lack = (
            f"{label}에게 없는 오행({names(e['lacking'])}) 중 {other}가 채워 주는 것: "
            f"{names(e['partner_has'])}"
        )
    else:
        lack = f"{label}는 표면에 다섯 오행이 모두 있음"
    if e["favorable"]:
        fav = (
            f"{label}의 희용 후보 오행({names(e['favorable'])})은 {other} 원국 표면에 "
            f"{e['partner_favorable_count']}글자"
        )
    else:
        fav = f"{label}는 억부·조후로 뚜렷한 희용 후보 오행이 없음"
    return f"{lack}; {fav}"


def _element_complement_rule(a: Labelled, b: Labelled) -> Drafts:
    (la, ca), (lb, cb) = a, b
    ea, eb = _complement_entry(ca, cb), _complement_entry(cb, ca)
    draft = _Draft(
        kind="rule_derived",
        operands={"entries": _entries(ea, eb)},
        text_ko=f"{_complement_text(la, lb, ea)}. {_complement_text(lb, la, eb)}",
        source_ref=_rules_ref("COUPLE_ELEMENT_COMPLEMENT"),
        assumptions=(depth.EOKBU_ASSUMPTION, depth.JOHU_ASSUMPTION),
    )
    everything = frozenset(POSITIONS)
    return [(draft, {la: everything, lb: everything})]


def _timing_rule(a: Labelled, b: Labelled, start_year: int, years: int) -> Drafts:
    (la, ca), (lb, cb) = a, b
    rows_a = timing.year_rows(ca, start_year, years)
    rows_b = timing.year_rows(cb, start_year, years)
    joint = []
    for ra, rb in zip(rows_a, rows_b, strict=True):
        both = ra["core_count"] > 0 and rb["core_count"] > 0
        joint.append((ra, rb, both))
    order = sorted(
        joint,
        key=lambda x: (
            not x[2],
            -(x[0]["core_count"] + x[1]["core_count"]),
            -(x[0]["cue_count"] + x[1]["cue_count"]),
            x[0]["year"],
        ),
    )
    ranks = {x[0]["year"]: i for i, x in enumerate(order, start=1)}
    drafts: Drafts = []
    for ra, rb, both in joint:

        def entry(row: dict[str, Any], chart: ChartSnapshot) -> dict[str, Any]:
            return {
                "day_pillar": chart.day_pillar,
                "cues": row["cues"],
                "cautions": row["cautions"],
                "core_count": row["core_count"],
            }

        def part(label: str, row: dict[str, Any]) -> str:
            caution = f" / 주의 {timing.cues_ko(row['cautions'])}" if row["cautions"] else ""
            return f"{label} 단서 {timing.cues_ko(row['cues'])}{caution}"

        year = ra["year"]
        draft = _Draft(
            kind="rule_derived",
            operands={
                "year": year,
                "year_pillar": ra["pillar"],
                "both_core": both,
                "joint_rank": ranks[year],
                "entries": _entries(entry(ra, ca), entry(rb, cb)),
            },
            text_ko=f"{year}년 {_ko(ra['pillar'])} (공동 순위 {ranks[year]}"
            f"{', 두 사람 모두 핵심 단서' if both else ''}): {part(la, ra)}; {part(lb, rb)}",
            source_ref=f"{_rules_ref('COUPLE_TIMING')} (year pillar by 60-cycle, "
            f"{_SEXAGENARY_BASE_YEAR}=甲子)",
            assumptions=(
                TIMING_ASSUMPTION,
                JOINT_RANK_ASSUMPTION,
                timing.YEAR_PILLAR_ASSUMPTION,
                t.SPOUSE_STAR_ASSUMPTION,
            ),
        )
        everything = frozenset(POSITIONS)
        drafts.append((draft, {la: everything, lb: everything}))
    return drafts


def _timeline_ko(timeline: list[str]) -> str:
    names = ["자료 없음" if p == DAEWOON_UNAVAILABLE else _ko(p) for p in timeline]
    return " → ".join(names) + (" (전환 연도)" if len(names) > 1 else "")


def _luck_overlap_rule(a: Labelled, b: Labelled, start_year: int, years: int) -> Drafts:
    (la, ca), (lb, cb) = a, b
    common: list[str] = []
    if "PARTIAL" in (ca.certainty, cb.certainty):
        common.append(DAEWOON_PRIMARY_ONLY)
    if "DAEWOON_START_APPROXIMATE" in ca.warning_codes + cb.warning_codes:
        common.append(DAEWOON_START_APPROXIMATE)
    drafts: Drafts = []
    for year in range(start_year, start_year + years):
        pillar = timing.year_pillar(year, (ca, cb))
        ta, tb = _daewoon_timeline(ca, year), _daewoon_timeline(cb, year)
        transition = (TRANSITION_ASSUMPTION,) if len(ta) > 1 or len(tb) > 1 else ()
        draft = _Draft(
            kind="computed",
            operands={
                "year": year,
                "year_pillar": pillar,
                "entries": _entries({"daewoon": ta}, {"daewoon": tb}),
            },
            text_ko=f"{year}년 {_ko(pillar)}: {la} 대운 {_timeline_ko(ta)}, "
            f"{lb} 대운 {_timeline_ko(tb)}",
            source_ref=f"{_rules_ref('COUPLE_LUCK_OVERLAP')} (snapshot daewoon start ages; "
            f"year pillar by 60-cycle, {_SEXAGENARY_BASE_YEAR}=甲子)",
            assumptions=(*transition, *common),
        )
        drafts.append((draft, {la: frozenset({"year", "month"}), lb: frozenset({"year", "month"})}))
    return drafts


def build_couple_evidence(
    a: ChartSnapshot, b: ChartSnapshot, start_year: int, years: int = 10
) -> list[Evidence]:
    """Individual catalogs for A and B, then pair evidence sorted by rule order then sequence/id."""
    _validate_window(start_year, years)
    la, lb = ("A", a), ("B", b)
    differing = {"A": _differing_positions(a), "B": _differing_positions(b)}
    rules = {
        "COUPLE_DAY_STEM": _day_stem_rule(la, lb),
        "COUPLE_DAY_BRANCH": _day_branch_rule(la, lb),
        "COUPLE_CROSS_PILLARS": _cross_pillars_rule(la, lb),
        "COUPLE_DAY_STEM_ELEMENT": _day_stem_element_rule(la, lb),
        "COUPLE_SPOUSE_STAR_MATCH": _spouse_star_match_rule(la, lb),
        "COUPLE_ELEMENT_COMPLEMENT": _element_complement_rule(la, lb),
        "COUPLE_TIMING": _timing_rule(la, lb, start_year, years),
        "COUPLE_LUCK_OVERLAP": _luck_overlap_rule(la, lb, start_year, years),
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
    ordered = sorted(pair, key=sort_key(COUPLE_RULE_ORDER))
    evidence = individual + ordered
    ids = [e.id for e in evidence]
    if len(ids) != len(set(ids)):
        raise RuntimeError("evidence id collision: operands must distinguish items")
    return evidence
