"""General (종합 사주) evidence catalog — rules-v6.

`build_general_evidence(chart)` = the individual rules minus the marriage-timing ones
(DAEWOON_FLOW, YEAR_TIMING, MONTH_TIMING, LIFE_TIMING), plus rules for temperament, career and
family, and a fortune flow without marriage cues or scores:

- TEN_GOD_DISTRIBUTION: per ten-god group, surface characters and weighted hidden stems, with a
  level (none / weak / normal / strong; unconfirmed when the unknown hour could hold it).
- PALACES: the family meaning of each pillar (궁위) and the ten gods sitting there.
- KINSHIP: where each relative's star (육친) appears, by gender.
- APTITUDE_CUES: the traditional work-type reading from the 외격, the 격국 and the dominant group.
- LUCK_FLOW / YEAR_FLOW: each daewoon and each window year as ten gods, relations with the natal
  chart and whether it carries the 억부 candidate elements.

Text is written in plain Korean (plain.PLAIN_TERMS) with no hanja; operands keep hanja.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fateweave.domain import tables as t
from fateweave.domain.glossary import hangul
from fateweave.domain.plain import PLAIN_TERMS
from fateweave.domain.rules import (
    RULE_ORDER,
    RULES,
    _Draft,
    _pillars,
    _rules_ref,
    build_evidence,
)
from fateweave.models.facts import ChartSnapshot, Evidence

MARRIAGE_TIMING_RULES = ("DAEWOON_FLOW", "YEAR_TIMING", "MONTH_TIMING", "LIFE_TIMING")
GENERAL_NEW_RULES = (
    "TEN_GOD_DISTRIBUTION",
    "PALACES",
    "KINSHIP",
    "APTITUDE_CUES",
    "LUCK_FLOW",
    "YEAR_FLOW",
)
GROUP_ORDER = ("比劫", "食傷", "財星", "官星", "印星")
LEVEL_KO = {
    "none": "없음",
    "weak": "약",
    "normal": "보통",
    "strong": "강",
    "unconfirmed": "확인 불가",
}
FULL_SURFACE = 7  # year/month/hour stems + four branch 本氣 (the day stem is the self)
_HIDDEN_WEIGHT = {"中氣": 0.6, "餘氣": 0.3}
_THRESHOLDS = ((1.5, "weak"), (3.0, "normal"))  # for a full chart; below 0 weight is none
DISTRIBUTION_ASSUMPTION = (
    "Fateweave design hypothesis: weight = surface + 0.5 x hidden (中氣 0.6, 餘氣 0.3); none 0, "
    "weak < 1.5, normal < 3, strong >= 3, thresholds scaled by known surface characters / 7"
)


def _group_ko(group: str) -> str:
    return t.GROUP_KO[group]


def _plain_group(group: str) -> str:
    return PLAIN_TERMS[_group_ko(group)]


def _hour_known(chart: ChartSnapshot) -> bool:
    return chart.hour_pillar is not None


def _surface(chart: ChartSnapshot) -> list[tuple[str, str]]:
    """(position key, ten god) for every surface character except the day stem."""
    day_stem = chart.day_pillar[0]
    found = []
    for pos, pillar in _pillars(chart).items():
        if pos != "day":
            found.append((f"{pos}_stem", t.ten_god(day_stem, pillar[0])))
        found.append((f"{pos}_branch", t.branch_ten_god(day_stem, pillar[1])))
    return found


def _hidden(chart: ChartSnapshot) -> list[tuple[str, str, float]]:
    """(position key, ten god, weight) for the 中氣 and 餘氣 of every known branch."""
    day_stem = chart.day_pillar[0]
    return [
        (f"{pos}_hidden", t.ten_god(day_stem, stem), _HIDDEN_WEIGHT[role])
        for pos, pillar in _pillars(chart).items()
        for stem, role in t.hidden_stems(pillar[1])
        if role in _HIDDEN_WEIGHT
    ]


def _level(weight: float, scale: float, hour_known: bool) -> str:
    if weight == 0:
        return "none" if hour_known else "unconfirmed"
    for limit, name in _THRESHOLDS:
        if weight < limit * scale:
            return name
    return "strong"


def ten_god_distribution(chart: ChartSnapshot) -> dict[str, Any]:
    surface, hidden = _surface(chart), _hidden(chart)
    scale = len(surface) / FULL_SURFACE
    known = _hour_known(chart)
    groups: dict[str, dict[str, Any]] = {}
    for group in GROUP_ORDER:
        gods = [god for _, god in surface if t.TEN_GOD_GROUP[god] == group]
        weight_hidden = round(sum(w for _, god, w in hidden if t.TEN_GOD_GROUP[god] == group), 3)
        weight = round(len(gods) + 0.5 * weight_hidden, 3)
        groups[group] = {
            "surface": len(gods),
            "hidden": weight_hidden,
            "weight": weight,
            "level": _level(weight, scale, known),
            "ten_gods": {god: gods.count(god) for god in sorted(set(gods))},
        }
    strong = [g for g in GROUP_ORDER if groups[g]["level"] == "strong"]
    top = max(v["weight"] for v in groups.values())
    return {
        "known_positions": list(_pillars(chart)),
        "groups": groups,
        "dominant": strong or [g for g in GROUP_ORDER if groups[g]["weight"] == top],
        "missing": [g for g in GROUP_ORDER if groups[g]["level"] == "none"],
    }


def _distribution_rule(chart: ChartSnapshot) -> list[_Draft]:
    d = ten_god_distribution(chart)
    parts = [
        f"{_group_ko(g)}({_plain_group(g)}) {LEVEL_KO[v['level']]}" for g, v in d["groups"].items()
    ]
    dominant = "·".join(_group_ko(g) for g in d["dominant"])
    text = f"기운 분포: {'; '.join(parts)}. 가장 두드러진 기운: {dominant}"
    if not _hour_known(chart):
        text += ". 태어난 시각을 몰라 세 기둥만으로 셈(없어 보이는 기운은 확인 불가)"
    return [
        _Draft(
            kind="rule_derived",
            operands=d,
            text_ko=text,
            source_ref=_rules_ref("TEN_GOD_DISTRIBUTION"),
            depends=frozenset(_pillars(chart)),
            assumptions=(DISTRIBUTION_ASSUMPTION,),
        )
    ]


PALACE = {
    "year": "ancestry_youth",
    "month": "parents_siblings_society",
    "day": "self_spouse",
    "hour": "children_later_life",
}
PALACE_KO = {
    "ancestry_youth": "조상·어린 시절",
    "parents_siblings_society": "부모·형제·사회",
    "self_spouse": "나 자신·배우자",
    "children_later_life": "자녀·말년",
}
_POS_KO = {"year": "연", "month": "월", "day": "일", "hour": "시"}
PALACE_ASSUMPTION = (
    "traditional 궁위: year ancestry/youth, month parents/siblings/society, day self/spouse, "
    "hour children/later life"
)


def _palaces_rule(chart: ChartSnapshot) -> list[_Draft]:
    day_stem = chart.day_pillar[0]
    drafts = []
    for pos, pillar in _pillars(chart).items():
        index = tuple(PALACE).index(pos)
        stem_god = None if pos == "day" else t.ten_god(day_stem, pillar[0])
        branch_god = t.branch_ten_god(day_stem, pillar[1])
        stage = t.twelve_stage(day_stem, pillar[1])
        stem_text = "나 자신" if stem_god is None else PLAIN_TERMS[hangul(stem_god)]
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands={
                    "index": index,
                    "position": pos,
                    "palace": PALACE[pos],
                    "pillar": pillar,
                    "stem_ten_god": stem_god,
                    "branch_ten_god": branch_god,
                    "stage": stage,
                },
                text_ko=f"{_POS_KO[pos]}주({PALACE_KO[PALACE[pos]]} 자리) {hangul(pillar)}: 겉은 "
                f"{stem_text}, 속은 {PLAIN_TERMS[hangul(branch_god)]}, 기운의 단계는 "
                f"{t.TWELVE_STAGES_KO[stage]}",
                source_ref=_rules_ref("PALACES"),
                depends=frozenset({pos, "day"}),
                assumptions=(PALACE_ASSUMPTION,),
            )
        )
    if not _hour_known(chart):
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands={
                    "index": 3,
                    "position": "hour",
                    "palace": PALACE["hour"],
                    "status": "unknown",
                },
                text_ko="시주(자녀·말년 자리): 태어난 시각을 몰라 이 자리는 읽지 않음",
                source_ref=_rules_ref("PALACES"),
                assumptions=(PALACE_ASSUMPTION,),
            )
        )
    return drafts


KINSHIP_TABLE: dict[str, dict[str, tuple[str, ...]]] = {
    "male": {
        "mother": ("正印",),
        "father": ("偏財",),
        "siblings": ("比肩", "劫財"),
        "spouse": ("正財", "偏財"),
        "son": ("偏官",),
        "daughter": ("正官",),
    },
    "female": {
        "mother": ("正印",),
        "father": ("偏財",),
        "siblings": ("比肩", "劫財"),
        "spouse": ("正官", "偏官"),
        "son": ("傷官",),
        "daughter": ("食神",),
    },
}
RELATIVE_KO = {
    "mother": "어머니",
    "father": "아버지",
    "siblings": "형제자매",
    "spouse": "배우자",
    "son": "아들",
    "daughter": "딸",
}
KINSHIP_ASSUMPTION = (
    "school-dependent 육친 by gender_for_daewoon: mother 正印, father 偏財, siblings 比肩/劫財, "
    "spouse 正財(偏財) for male and 正官(偏官) for female, children 官星 for male and 食傷 for "
    "female; other schools read father as 正財 or mother as 偏印"
)


def kinship(chart: ChartSnapshot) -> list[dict[str, Any]]:
    surface, hidden = _surface(chart), _hidden(chart)
    entries = []
    for relative, gods in KINSHIP_TABLE[chart.gender_for_daewoon].items():
        found = [{"position": p, "ten_god": g} for p, g in surface if g in gods]
        count = len(found)
        found += [{"position": p, "ten_god": g} for p, g, _ in hidden if g in gods]
        if found:
            status = "found"
        else:
            status = "none" if _hour_known(chart) else "unconfirmed"
        entries.append(
            {
                "relative": relative,
                "ten_gods": list(gods),
                "found": found,
                "count": count,
                "status": status,
            }
        )
    return entries


def _kinship_rule(chart: ChartSnapshot) -> list[_Draft]:
    drafts = []
    for index, e in enumerate(kinship(chart)):
        star = "·".join(PLAIN_TERMS[hangul(g)] for g in e["ten_gods"])
        if e["status"] == "found":
            where = ", ".join(
                f"{_POS_KO[f['position'].split('_')[0]]}주"
                + ("(속)" if f["position"].endswith("_hidden") else "")
                for f in e["found"]
            )
            state = f"겉으로 {e['count']}번, 위치: {where}"
        elif e["status"] == "none":
            state = "명식에 보이지 않음"
        else:
            state = "아는 세 기둥에는 보이지 않음 — 시주 미상으로 확인 불가"
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands={"index": index, **e},
                text_ko=f"{RELATIVE_KO[e['relative']]}를 나타내는 기운({star}): {state}",
                source_ref=_rules_ref("KINSHIP"),
                depends=frozenset(_pillars(chart)),
                assumptions=(KINSHIP_ASSUMPTION,),
            )
        )
    return drafts


GENERAL_RULES: dict[str, Callable[[ChartSnapshot], list[_Draft]]] = {
    **{code: RULES[code] for code in RULE_ORDER if code not in MARRIAGE_TIMING_RULES},
    "TEN_GOD_DISTRIBUTION": _distribution_rule,
    "PALACES": _palaces_rule,
    "KINSHIP": _kinship_rule,
}
GENERAL_RULE_ORDER: tuple[str, ...] = tuple(GENERAL_RULES)


def build_general_evidence(chart: ChartSnapshot, subject_key: str = "self") -> list[Evidence]:
    return build_evidence(chart, subject_key, GENERAL_RULES, GENERAL_RULE_ORDER)
