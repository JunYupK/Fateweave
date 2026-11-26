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
from dataclasses import replace
from typing import Any

from korean_saju import GyeokgukCalculator

from fateweave.domain import depth, timing
from fateweave.domain import tables as t
from fateweave.domain.glossary import ELEMENT_KO, hangul
from fateweave.domain.plain import PLAIN_TERMS
from fateweave.domain.rules import (
    RULE_ORDER,
    RULES,
    _daewoon_assumptions,
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


def _eul(word: str) -> str:
    """을/를 by the last syllable's final consonant."""
    code = ord(word[-1]) - 0xAC00
    return "을" if 0 <= code <= 11171 and code % 28 else "를"


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
        f"{_group_ko(g)} {LEVEL_KO[v['level']]} — {_plain_group(g)}" for g, v in d["groups"].items()
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
        star = " / ".join(PLAIN_TERMS[hangul(g)] for g in e["ten_gods"])
        if e["status"] == "found":
            where = ", ".join(
                f"{_POS_KO[f['position'].split('_')[0]]}주"
                + ("(속)" if f["position"].endswith("_hidden") else "")
                for f in e["found"]
            )
            seen = f"겉으로 {e['count']}번" if e["count"] else "겉에는 없고 속에만 있음"
            state = f"{seen}, 위치: {where}"
        elif e["status"] == "none":
            state = "명식에 보이지 않음"
        else:
            state = "아는 세 기둥에는 보이지 않음 — 시주 미상으로 확인 불가"
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands={"index": index, **e},
                text_ko=f"{RELATIVE_KO[e['relative']]}{_eul(RELATIVE_KO[e['relative']])} "
                f"나타내는 기운({star}): {state}",
                source_ref=_rules_ref("KINSHIP"),
                depends=frozenset(_pillars(chart)),
                assumptions=(KINSHIP_ASSUMPTION,),
            )
        )
    return drafts


CATEGORY = {
    "比劫": "independent_competitive",
    "食傷": "expressive_technical",
    "財星": "business_management",
    "官星": "organization_public",
    "印星": "scholarly_educational",
}
CATEGORY_KO = {
    "independent_competitive": "독립·경쟁형",
    "expressive_technical": "표현·전문기술형",
    "business_management": "사업·관리형",
    "organization_public": "조직·공직형",
    "scholarly_educational": "학문·교육형",
}
SPECIAL_GROUP = {
    **dict.fromkeys(("從旺格", "從強格", "曲直格", "炎上格", "稼穡格", "從革格", "潤下格"), "比劫"),
    "從財格": "財星",
    "從官殺格": "官星",
    "從兒格": "食傷",
}
GYEOKGUK_GROUP = {
    "食神格": "食傷",
    "傷官格": "食傷",
    "偏財格": "財星",
    "正財格": "財星",
    "偏官格": "官星",
    "正官格": "官星",
    "偏印格": "印星",
    "正印格": "印星",
    "建祿格": "比劫",
    "羊刃格": "比劫",
}
WORK_SINSAL = ("驛馬", "華蓋", "天乙貴人", "魁罡", "羊刃")
APTITUDE_ASSUMPTION = (
    "school-dependent traditional work types by ten-god group (比劫 independent/competitive, 食傷 "
    "expressive/technical, 財星 business/management, 官星 organization/public, 印星 "
    "scholarly/educational): an accepted 外格 decides first, then the 格局 group plus the "
    "dominant group, else the dominant group"
)


def _gyeokguk(chart: ChartSnapshot) -> str | None:
    if not _hour_known(chart):
        return None
    return GyeokgukCalculator.determine(depth.library_saju(chart)).gyeokguk.hanja


def _reading(basis: str, groups: list[str]) -> dict[str, Any]:
    return {"basis": basis, "groups": groups, "categories": [CATEGORY[g] for g in groups]}


def aptitude(chart: ChartSnapshot) -> dict[str, Any]:
    dominant = ten_god_distribution(chart)["dominant"]
    gyeokguk = _gyeokguk(chart)
    if gyeokguk in GYEOKGUK_GROUP:
        regular = _reading(
            "gyeokguk", list(dict.fromkeys([GYEOKGUK_GROUP[gyeokguk], *dominant]))[:2]
        )
    else:
        regular = _reading("dominant", dominant[:2])
    special = next(
        (
            s
            for s in sorted(depth.special_structures(chart)["accepted"], key=lambda s: -s["score"])
            if s["type"] in SPECIAL_GROUP
        ),
        None,
    )
    present = {s["sinsal"] for s in depth.sinsal(chart)}
    common = {
        "gyeokguk": gyeokguk,
        "special_structure": special["type"] if special else None,
        "sinsal": [n for n in WORK_SINSAL if n in present],
    }
    if special:
        return {
            **_reading("special_structure", [SPECIAL_GROUP[special["type"]]]),
            **common,
            "alternative": regular,
        }
    return {**regular, **common, "alternative": None}


def _aptitude_rule(chart: ChartSnapshot) -> list[_Draft]:
    a = aptitude(chart)

    def kinds(reading: dict[str, Any]) -> str:
        return "과 ".join(CATEGORY_KO[c] for c in reading["categories"])

    basis = {
        "special_structure": "한쪽 기운으로 크게 쏠린 특별한 틀을 따라",
        "gyeokguk": "명식의 큰 틀과 가장 두드러진 기운을 함께 보아",
        "dominant": "가장 두드러진 기운을 보아",
    }[a["basis"]]
    text = f"일의 적성(전통 분류): {basis} {kinds(a)}으로 본다"
    if a["alternative"]:
        text += f". 일반적인 틀로 읽으면 {kinds(a['alternative'])}"
    if a["sinsal"]:
        text += ". 일과 관련된 기운: " + ", ".join(
            PLAIN_TERMS[depth.SINSAL_KO[n]] for n in a["sinsal"]
        )
    return [
        _Draft(
            kind="rule_derived",
            operands=a,
            text_ko=text,
            source_ref=_rules_ref("APTITUDE_CUES"),
            depends=frozenset(_pillars(chart)),
            assumptions=(APTITUDE_ASSUMPTION,),
        )
    ]


FLOW_ASSUMPTION = (
    "fortune flow without scores: ten gods of the incoming pillar, its relations with the natal "
    "chart, and whether it carries the 억부 candidate elements (consensus strength)"
)
_RELATION_KO = {
    "六合": "손잡는 끌림",
    "三合": "한 방향으로 모이는 결속",
    "沖": "부딪침",
    "刑": "긴장",
    "破": "깨짐",
    "害": "어긋남",
    "怨嗔": "서로 거슬림",
    "鬼門": "예민함",
    "合": "손잡는 끌림",
}


def _incoming(chart: ChartSnapshot, pillar: str) -> dict[str, Any]:
    """Ten gods, groups, natal relations and favorable elements of an incoming pillar."""
    day_stem = chart.day_pillar[0]
    stem_god = t.ten_god(day_stem, pillar[0])
    branch_god = t.branch_ten_god(day_stem, pillar[1])
    elements = {t.STEM_ELEMENT[pillar[0]], t.BRANCH_ELEMENT[pillar[1]]}
    return {
        "stem_ten_god": stem_god,
        "branch_ten_god": branch_god,
        "groups": [t.TEN_GOD_GROUP[stem_god], t.TEN_GOD_GROUP[branch_god]],
        "relations": timing.natal_relations(chart, pillar),
        "favorable_match": sorted(elements & set(depth.favorable_elements(chart))),
    }


def _incoming_text(row: dict[str, Any]) -> str:
    stem = PLAIN_TERMS[hangul(row["stem_ten_god"])]
    branch = PLAIN_TERMS[hangul(row["branch_ten_god"])]
    rels = [
        f"{_POS_KO[r['with'].split('_')[0]]}주와 {_RELATION_KO.get(r['relation'], '관계')}"
        for r in row["relations"]
        if "+" not in r["with"]
    ]
    rel = ", ".join(dict.fromkeys(rels)) or "타고난 기둥과 뚜렷한 부딪침·끌림 없음"
    good = (
        "도움이 되는 기운(" + "·".join(ELEMENT_KO[e] for e in row["favorable_match"]) + ")이 들어옴"
        if row["favorable_match"]
        else "도움이 되는 기운과는 겹치지 않음"
    )
    return f"겉으로 {stem}, 속으로 {branch}이 부각됨. {rel}. {good}"


def _luck_flow_rule(chart: ChartSnapshot) -> list[_Draft]:
    drafts = []
    for i, entry in enumerate(chart.daewoon.entries):
        row = {
            "index": i,
            "start_age": entry.start_age,
            "end_age": entry.start_age + 9,
            "pillar": entry.pillar,
            **_incoming(chart, entry.pillar),
        }
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands=row,
                text_ko=f"{i + 1}번째 10년 운 ({entry.start_age}~{entry.start_age + 9}세, "
                f"{hangul(entry.pillar)}): {_incoming_text(row)}",
                source_ref=_rules_ref("LUCK_FLOW"),
                depends=frozenset(_pillars(chart)),
                assumptions=(*_daewoon_assumptions(chart), FLOW_ASSUMPTION),
            )
        )
    return drafts


def _daewoon_relations(year_pillar: str, daewoon: list[str]) -> list[dict[str, str]]:
    found = []
    for p in daewoon:
        if p == timing.DAEWOON_UNAVAILABLE:
            continue
        for rel, _, members in t.pair_relations(year_pillar[1], p[1]):
            found.append({"daewoon": p, "relation": rel, "name": f"{members}{rel}"})
        for rel, _, members in t.stem_relations(year_pillar[0], p[0]):
            found.append({"daewoon": p, "relation": rel, "name": f"{members}{rel}"})
    return found


def _year_flow_rule(chart: ChartSnapshot) -> list[_Draft]:
    drafts = []
    for entry in chart.sewoon:
        daewoon = timing.daewoon_timeline(chart, entry.year)
        row = {
            "year": entry.year,
            "year_pillar": entry.pillar,
            **_incoming(chart, entry.pillar),
            "daewoon": daewoon,
            "daewoon_relations": _daewoon_relations(entry.pillar, daewoon),
        }
        with_luck = ", ".join(
            dict.fromkeys(_RELATION_KO.get(r["relation"], "관계") for r in row["daewoon_relations"])
        )
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands=row,
                text_ko=f"{entry.year}년({hangul(entry.pillar)}): {_incoming_text(row)}. "
                + (f"그때의 10년 운과 {with_luck}" if with_luck else "그때의 10년 운과 무난함"),
                source_ref=_rules_ref("YEAR_FLOW"),
                depends=frozenset(_pillars(chart)),
                assumptions=(
                    timing.YEAR_PILLAR_ASSUMPTION,
                    *_daewoon_assumptions(chart),
                    FLOW_ASSUMPTION,
                ),
            )
        )
    return drafts


def _spouse_star_rule(chart: ChartSnapshot) -> list[_Draft]:
    """SPOUSE_STAR, qualified when the unknown hour could hold the star (as KINSHIP says)."""
    drafts = RULES["SPOUSE_STAR"](chart)
    if _hour_known(chart):
        return drafts
    note = " (세 기둥 기준 — 태어난 시각을 몰라 시주의 배우자 기운은 확인 불가)"
    return [replace(d, text_ko=d.text_ko + note) for d in drafts]


GENERAL_RULES: dict[str, Callable[[ChartSnapshot], list[_Draft]]] = {
    **{code: RULES[code] for code in RULE_ORDER if code not in MARRIAGE_TIMING_RULES},
    "SPOUSE_STAR": _spouse_star_rule,
    "TEN_GOD_DISTRIBUTION": _distribution_rule,
    "PALACES": _palaces_rule,
    "KINSHIP": _kinship_rule,
    "APTITUDE_CUES": _aptitude_rule,
    "LUCK_FLOW": _luck_flow_rule,
    "YEAR_FLOW": _year_flow_rule,
}
GENERAL_RULE_ORDER: tuple[str, ...] = tuple(GENERAL_RULES)


def build_general_evidence(chart: ChartSnapshot, subject_key: str = "self") -> list[Evidence]:
    return build_evidence(chart, subject_key, GENERAL_RULES, GENERAL_RULE_ORDER)
