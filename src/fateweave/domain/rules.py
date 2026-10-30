"""Individual myeongri evidence catalog — policy rules-v3.

`build_individual_evidence` reads only the ChartSnapshot, so stored snapshots always rebuild
the same catalog (same IDs, same digest). `operands` keep hanja (machine-checked values);
`text_ko` is written in hangul (see glossary.py). Rules, in fixed order:

- PILLARS / TEN_GODS / DAEWOON / SEWOON: copied from the snapshot (manse-v2, korean-saju).
- HIDDEN_STEMS (지장간) and TWELVE_STAGES (12운성 of the day stem): fixed tables per branch.
- SPOUSE_PALACE (日支) and SPOUSE_STAR (財星 for male, 官星 for female, by gender_for_daewoon).
- ELEMENTS: surface 五行 count, and a second count including every hidden stem.
- STRENGTH: three items — korean-saju 10-point scheme, Fateweave rooted_seasonal_v1 (roots in
  hidden stems and 旺相休囚死), and the consensus (divergent or not; the rooted method is
  primary). YONGSIN (억부 candidates from the primary level) and JOHU (season and the
  simplified 조후 element): school-dependent results under a named method, stated in the
  assumptions.
- SPECIAL_STRUCTURE: korean-saju's 16 外格 checks; none accepted means 정격.
- BRANCH_RELATIONS (六合, 三合, 沖, 刑, 破, 害, 怨嗔, 鬼門) and STEM_RELATIONS (天干合/沖).
- SINSAL (桃花, 驛馬, 華蓋, 紅艶, 天乙貴人, 羊刃, 孤辰, 寡宿, 白虎, 魁罡, 孤鸞, 陰陽差錯) and
  GONGMANG (旬空 by the day pillar). 半合 is not listed as a relation.
- GYEOKGUK: korean-saju's GyeokgukCalculator, only when the hour is known.
- DAEWOON_FLOW, YEAR_TIMING, MONTH_TIMING: marriage-timing cues (timing.py) for every daewoon,
  every sewoon year in the snapshot, and the months of the three top-ranked years.

Unknown hour: nothing references the hour pillar. PARTIAL charts: items whose operands depend
on a pillar that differs in an alternative carry BOUNDARY_ASSUMPTION.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Literal

from korean_saju import GyeokgukCalculator

from fateweave.config import Settings
from fateweave.domain import depth, timing
from fateweave.domain import tables as t
from fateweave.domain.glossary import ELEMENT_KO, hangul
from fateweave.models.facts import ChartSnapshot, Evidence

RULE_ORDER: tuple[str, ...] = (
    "PILLARS",
    "TEN_GODS",
    "HIDDEN_STEMS",
    "TWELVE_STAGES",
    "SPOUSE_PALACE",
    "SPOUSE_STAR",
    "ELEMENTS",
    "STRENGTH",
    "YONGSIN",
    "JOHU",
    "BRANCH_RELATIONS",
    "STEM_RELATIONS",
    "SINSAL",
    "GONGMANG",
    "GYEOKGUK",
    "SPECIAL_STRUCTURE",
    "DAEWOON",
    "DAEWOON_FLOW",
    "SEWOON",
    "YEAR_TIMING",
    "MONTH_TIMING",
)
BOUNDARY_ASSUMPTION = "depends on primary pillar set; alternatives exist (BOUNDARY_REVIEW_REQUIRED)"
DAEWOON_PRIMARY_ONLY = "computed for primary pillar set only"
DAEWOON_START_APPROXIMATE = "start age approximate: birth time unknown (DAEWOON_START_APPROXIMATE)"
_SUBJECT_KEY = re.compile(r"[A-Za-z0-9]+")

POSITIONS = depth.POSITIONS
_POS_KO = {"year": "연", "month": "월", "day": "일", "hour": "시"}
_SEASON_KO = {"春": "봄", "夏": "여름", "秋": "가을", "冬": "겨울"}
_PAIR_RELATIONS = t.PAIR_RELATIONS  # kept for importers

Kind = Literal["computed", "rule_derived", "interpretation_cue"]


@dataclass(frozen=True)
class _Draft:
    kind: Kind
    operands: dict[str, Any]
    text_ko: str
    source_ref: str
    depends: frozenset[str] = frozenset()  # pillar positions the operands depend on
    assumptions: tuple[str, ...] = ()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def evidence_id(subject_key: str, rule_code: str, operands: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(operands).encode("utf-8")).hexdigest()[:8]
    return f"E-{subject_key}-{rule_code}-{digest}"


def evidence_digest(evidence: list[Evidence]) -> str:
    """sha256 over the canonical JSON of the catalog sorted by id (order independent)."""
    items = sorted((e.model_dump(mode="json") for e in evidence), key=lambda d: d["id"])
    return hashlib.sha256(canonical_json(items).encode("utf-8")).hexdigest()


_pillars = depth.pillars


def _library(chart: ChartSnapshot) -> str:
    return f"korean-saju=={chart.library_version}"


def _rules_ref(code: str) -> str:
    return f"{Settings.RULE_VERSION}#{code}"


def _pos_ko(position: str) -> str:
    """'day_branch' → '일지', 'year_stem' → '연간', 'hour_pillar' → '시주'."""
    pos, _, part = position.partition("_")
    return _POS_KO[pos] + {"stem": "간", "branch": "지", "pillar": "주", "": ""}[part]


def _ko(text: str) -> str:
    return hangul(text)


def _pillar_rule(chart: ChartSnapshot) -> list[_Draft]:
    return [
        _Draft(
            kind="computed",
            operands={"position": pos, "pillar": pillar},
            text_ko=f"{_POS_KO[pos]}주 {_ko(pillar)}",
            source_ref=f"{chart.policy_version}#PILLARS",
            depends=frozenset({pos}),
        )
        for pos, pillar in _pillars(chart).items()
    ]


def _ten_gods_rule(chart: ChartSnapshot) -> list[_Draft]:
    pillars = _pillars(chart)
    day_stem = chart.day_pillar[0]
    drafts = []
    for key, god in chart.ten_gods.items():
        pos, part = key.split("_")
        if pos not in pillars:  # never cite an hour-dependent ten god without an hour pillar
            continue
        target = pillars[pos][0 if part == "stem" else 1]
        basis = "" if part == "stem" else " (지지 본기 기준)"
        drafts.append(
            _Draft(
                kind="computed",
                operands={"position": key, "target": target, "day_stem": day_stem, "ten_god": god},
                text_ko=f"{_pos_ko(key)} {_ko(target)}: 일간 {_ko(day_stem)} 기준 "
                f"{_ko(god)}{basis}",
                source_ref=f"{_library(chart)}#ShipsinCalculator",
                depends=frozenset({pos, "day"}),
            )
        )
    return drafts


def _hidden_stems_rule(chart: ChartSnapshot) -> list[_Draft]:
    day_stem = chart.day_pillar[0]
    drafts = []
    for pos, pillar in _pillars(chart).items():
        stems = [
            {"stem": s, "role": role, "ten_god": t.ten_god(day_stem, s)}
            for s, role in t.hidden_stems(pillar[1])
        ]
        listed = ", ".join(
            f"{t.ROLE_KO[x['role']]} {_ko(x['stem'])}({_ko(x['ten_god'])})" for x in stems
        )
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands={"position": f"{pos}_branch", "branch": pillar[1], "hidden": stems},
                text_ko=f"{_POS_KO[pos]}지 {_ko(pillar[1])}의 지장간: {listed}",
                source_ref=f"{_library(chart)}#JiJangGan",
                depends=frozenset({pos, "day"}),
            )
        )
    return drafts


def _twelve_stages_rule(chart: ChartSnapshot) -> list[_Draft]:
    day_stem = chart.day_pillar[0]
    drafts = []
    for pos, pillar in _pillars(chart).items():
        stage = t.twelve_stage(day_stem, pillar[1])
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands={
                    "position": f"{pos}_branch",
                    "branch": pillar[1],
                    "day_stem": day_stem,
                    "stage": stage,
                },
                text_ko=f"{_POS_KO[pos]}지 {_ko(pillar[1])}: 일간 {_ko(day_stem)}의 12운성 "
                f"{t.TWELVE_STAGES_KO[stage]}",
                source_ref=_rules_ref("TWELVE_STAGES"),
                depends=frozenset({pos, "day"}),
                assumptions=(t.TWELVE_STAGES_ASSUMPTION,),
            )
        )
    return drafts


def _spouse_palace_rule(chart: ChartSnapshot) -> list[_Draft]:
    branch = chart.day_pillar[1]
    god = chart.ten_gods["day_branch"]
    return [
        _Draft(
            kind="rule_derived",
            operands={"position": "day_branch", "branch": branch, "ten_god": god},
            text_ko=f"배우자궁(일지) {_ko(branch)}: 일간 {_ko(chart.day_pillar[0])} 기준 "
            f"{_ko(god)} (본기 기준)",
            source_ref=_rules_ref("SPOUSE_PALACE"),
            depends=frozenset({"day"}),
        )
    ]


def _spouse_star_rule(chart: ChartSnapshot) -> list[_Draft]:
    star = depth.spouse_star(chart)
    gender = "남" if star["gender_for_daewoon"] == "male" else "여"
    stars = "·".join(_ko(s) for s in star["stars"])

    def where(items: list[dict[str, str]]) -> str:
        return (
            ", ".join(
                f"{_pos_ko(x['position'])} {_ko(x['value'])}({_ko(x['ten_god'])})" for x in items
            )
            or "없음"
        )

    mixed = " — 정·편 혼재" if star["mixed"] else ""
    return [
        _Draft(
            kind="rule_derived",
            operands=star,
            text_ko=f"{gender}명 배우자성 {stars}({ELEMENT_KO[star['element']]}): 드러난 자리 "
            f"{where(star['visible'])}, 지장간 속 {where(star['hidden'])}{mixed}",
            source_ref=_rules_ref("SPOUSE_STAR"),
            depends=frozenset(_pillars(chart)),
            assumptions=(t.SPOUSE_STAR_ASSUMPTION,),
        )
    ]


def _elements_rule(chart: ChartSnapshot) -> list[_Draft]:
    pillars = _pillars(chart)
    surface = dict.fromkeys(t.ELEMENT_ORDER, 0)
    with_hidden = dict.fromkeys(t.ELEMENT_ORDER, 0)
    for pillar in pillars.values():
        surface[t.STEM_ELEMENT[pillar[0]]] += 1
        surface[t.BRANCH_ELEMENT[pillar[1]]] += 1
        with_hidden[t.STEM_ELEMENT[pillar[0]]] += 1
        for stem, _ in t.hidden_stems(pillar[1]):
            with_hidden[t.STEM_ELEMENT[stem]] += 1
    scope = "·".join(_POS_KO[p] for p in pillars) + "주"
    assumptions = () if chart.hour_pillar else ("hour pillar unknown: year/month/day only",)

    def summary(counts: dict[str, int]) -> str:
        return " ".join(f"{ELEMENT_KO[e]}{n}" for e, n in counts.items())

    missing = [ELEMENT_KO[e] for e, n in surface.items() if n == 0]
    lack = f", 표면에 없는 오행: {'·'.join(missing)}" if missing else ""
    return [
        _Draft(
            kind="rule_derived",
            operands={
                "basis": "surface_stems_and_branches",
                "positions": list(pillars),
                "counts": surface,
            },
            text_ko=f"{scope} {2 * len(pillars)}글자 표면 오행(지장간 미포함): "
            f"{summary(surface)}{lack}",
            source_ref=_rules_ref("ELEMENTS"),
            depends=frozenset(pillars),
            assumptions=assumptions,
        ),
        _Draft(
            kind="rule_derived",
            operands={
                "basis": "stems_and_all_hidden_stems",
                "positions": list(pillars),
                "counts": with_hidden,
            },
            text_ko=f"{scope} 천간 + 지장간 전체 오행 개수: {summary(with_hidden)}",
            source_ref=_rules_ref("ELEMENTS"),
            depends=frozenset(pillars),
            assumptions=(*assumptions, "each hidden stem counted once regardless of role"),
        ),
    ]


def _strength_rule(chart: ChartSnapshot) -> list[_Draft]:
    s = depth.strength(chart)
    r = depth.strength_rooted(chart)
    c = depth.strength_consensus(chart)
    everything = frozenset(_pillars(chart))
    library_assumptions = [depth.STRENGTH_ASSUMPTION]
    if not s["birth_time_known"]:
        library_assumptions.append(depth.STRENGTH_RESCALED)
    parts = r["components"]
    hour = f", 시지 뿌리 {parts['hour_branch']}" if "hour_branch" in parts else ""
    if c["divergent"]:
        consensus = (
            f"두 관법 판정이 다름 — 라이브러리 10점제 {depth.level_ko(s['level'])}, 통근·월령 반영 "
            f"{depth.level_ko(r['level'])}. 억부 용신 후보와 결혼 시기 단서는 통근·월령 반영 "
            f"판정({depth.level_ko(c['level'])})을 따름"
        )
    else:
        consensus = f"두 관법 모두 {depth.level_ko(c['level'])}"
    return [
        _Draft(
            kind="rule_derived",
            operands=s,
            text_ko=f"일간 강약(라이브러리 10점제): {depth.level_ko(s['level'])} "
            f"({s['total']}/10점 — 월지 득령 {s['deukryeong']}, 일지 득지 {s['deukji']}, "
            f"나머지 득세 {s['deukse']}, 보정 {s['adjustment']}; 지지의 겉 오행만 봄)",
            source_ref=f"{_library(chart)}#IlganStrengthAnalyzer",
            depends=everything,
            assumptions=tuple(library_assumptions),
        ),
        _Draft(
            kind="rule_derived",
            operands=r,
            text_ko=f"일간 강약(통근·월령 반영): {depth.level_ko(r['level'])} ({r['percent']}% — "
            f"월령 {depth.SEASON_STATE_KO[r['season_state']]} {parts['season']}, 일지 뿌리 "
            f"{parts['day_branch']}, 연지 뿌리 {parts['year_branch']}{hour}, 천간 "
            f"{parts['stems']} / {r['max_points']})",
            source_ref=_rules_ref("STRENGTH"),
            depends=everything,
            assumptions=(depth.ROOTED_STRENGTH_ASSUMPTION,),
        ),
        _Draft(
            kind="rule_derived",
            operands=c,
            text_ko=f"일간 강약 종합: {consensus}",
            source_ref=_rules_ref("STRENGTH"),
            depends=everything,
            assumptions=(depth.STRENGTH_DIVERGENT,) if c["divergent"] else (),
        ),
    ]


def _yongsin_rule(chart: ChartSnapshot) -> list[_Draft]:
    e = depth.eokbu(chart)
    if e["groups"]:
        groups = "·".join(t.GROUP_KO[g] for g in e["groups"])
        elements = "·".join(ELEMENT_KO[x] for x in e["elements"])
        text = (
            f"억부 기준 용신 후보: {depth.level_ko(e['strength_level'])}이므로 {groups} "
            f"({elements}) 쪽이 도움이 되는 기운으로 읽힘"
        )
    else:
        text = "억부 기준: 중화에 가까워 억부로 뚜렷한 용신 후보를 정하지 않음"
    return [
        _Draft(
            kind="rule_derived",
            operands=e,
            text_ko=text,
            source_ref=_rules_ref("YONGSIN"),
            depends=frozenset(_pillars(chart)),
            assumptions=(depth.ROOTED_STRENGTH_ASSUMPTION, depth.EOKBU_ASSUMPTION),
        )
    ]


def _johu_rule(chart: ChartSnapshot) -> list[_Draft]:
    j = depth.johu(chart)
    season = _SEASON_KO[j["season"]]
    need = (
        f"조후상 {'·'.join(ELEMENT_KO[x] for x in j['elements'])} 기운이 우선 필요"
        if j["elements"]
        else "조후가 급하지 않은 계절"
    )
    return [
        _Draft(
            kind="rule_derived",
            operands=j,
            text_ko=f"월지 {_ko(j['month_branch'])}: {season}에 태어남, {need}",
            source_ref=_rules_ref("JOHU"),
            depends=frozenset({"month"}),
            assumptions=(depth.JOHU_ASSUMPTION,),
        )
    ]


def _branch_relations_rule(chart: ChartSnapshot) -> list[_Draft]:
    branches = [(pos, pillar[1]) for pos, pillar in _pillars(chart).items()]
    drafts = []
    for size, table in ((2, t.PAIR_RELATIONS), (3, t.TRIPLE_RELATIONS)):
        for combo in combinations(branches, size):
            found = sorted(b for _, b in combo)
            for relation, label, members in table:
                if found != sorted(members):
                    continue
                name = f"{members}{relation}"
                where = " · ".join(f"{_POS_KO[p]}지 {_ko(b)}" for p, b in combo)
                drafts.append(
                    _Draft(
                        kind="rule_derived",
                        operands={
                            "relation": relation,
                            "name": name,
                            "positions": [f"{p}_branch" for p, _ in combo],
                            "branches": [b for _, b in combo],
                        },
                        text_ko=f"{where}: {label}({_ko(name)}) 관계",
                        source_ref=_rules_ref("BRANCH_RELATIONS"),
                        depends=frozenset(p for p, _ in combo),
                    )
                )
    return drafts


def _stem_relations_rule(chart: ChartSnapshot) -> list[_Draft]:
    stems = [(pos, pillar[0]) for pos, pillar in _pillars(chart).items()]
    drafts = []
    for (pa, a), (pb, b) in combinations(stems, 2):
        for relation, label, members in t.stem_relations(a, b):
            drafts.append(
                _Draft(
                    kind="rule_derived",
                    operands={
                        "relation": relation,
                        "name": f"{members}{relation}",
                        "positions": [f"{pa}_stem", f"{pb}_stem"],
                        "stems": [a, b],
                    },
                    text_ko=f"{_POS_KO[pa]}간 {_ko(a)} · {_POS_KO[pb]}간 {_ko(b)}: "
                    f"{label}({_ko(members + relation)}) 관계",
                    source_ref=_rules_ref("STEM_RELATIONS"),
                    depends=frozenset({pa, pb}),
                    assumptions=(t.STEM_CHUNG_ASSUMPTION,) if relation == "沖" else (),
                )
            )
    return drafts


def _sinsal_rule(chart: ChartSnapshot) -> list[_Draft]:
    drafts = []
    for s in depth.sinsal(chart):
        name = s["sinsal"]
        basis = {
            "day_stem": f"일간 {_ko(chart.day_pillar[0])} 기준",
            "year_branch": f"연지 {_ko(chart.year_pillar[1])} 기준",
            "day_branch": f"일지 {_ko(chart.day_pillar[1])} 기준",
            "pillar": "기둥 자체",
            "day_pillar": f"일주 {_ko(chart.day_pillar)}",
        }[s["basis"]]
        where = ", ".join(_pos_ko(p) for p in s["found"])
        positions = {p.split("_")[0] for p in s["found"]}
        positions |= {s["basis"].split("_")[0]} if s["basis"] != "pillar" else set()
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands=s,
                text_ko=f"{depth.SINSAL_KO[name]}({basis}) — 위치: {where}. "
                f"전통 의미: {depth.SINSAL_MEANING_KO[name]}",
                source_ref=_rules_ref("SINSAL"),
                depends=frozenset(positions & set(POSITIONS)),
                assumptions=(
                    (depth.SINSAL_ASSUMPTIONS[name],) if name in depth.SINSAL_ASSUMPTIONS else ()
                ),
            )
        )
    return drafts


def _gongmang_rule(chart: ChartSnapshot) -> list[_Draft]:
    empty = t.gongmang(chart.day_pillar)
    found = [
        f"{pos}_branch"
        for pos, pillar in _pillars(chart).items()
        if pos != "day" and pillar[1] in empty
    ]
    where = ", ".join(_pos_ko(p) for p in found) or "원국에 해당 지지 없음"
    return [
        _Draft(
            kind="rule_derived",
            operands={"day_pillar": chart.day_pillar, "branches": list(empty), "found": found},
            text_ko=f"공망(일주 {_ko(chart.day_pillar)} 기준): {_ko(''.join(empty))} — {where}",
            source_ref=_rules_ref("GONGMANG"),
            depends=frozenset({"day", *(p.split("_")[0] for p in found)}),
        )
    ]


def _gyeokguk_rule(chart: ChartSnapshot) -> list[_Draft]:
    if chart.hour_pillar is None:
        return [
            _Draft(
                kind="interpretation_cue",
                operands={"status": "not_determined", "missing": "birth_time"},
                text_ko="출생 시각 미상: 시간(시주 천간) 투간 여부를 알 수 없어 "
                "격국을 판정하지 않음",
                source_ref=_rules_ref("GYEOKGUK"),
            )
        ]
    result = GyeokgukCalculator.determine(depth.library_saju(chart))
    g = result.gyeokguk
    return [
        _Draft(
            kind="rule_derived",
            operands={
                "gyeokguk": g.hanja,
                "basis_stem": result.basis_stem.hanja,
                "basis": result.basis,
                "seonggyeok": result.is_seonggyeok,
            },
            text_ko=f"격국(korean-saju 판정 규칙): {g.hangul}, 근거 {_ko(result.basis)}",
            source_ref=f"{_library(chart)}#GyeokgukCalculator",
            depends=frozenset(POSITIONS),
            assumptions=(
                "school-dependent criterion: korean-saju 0.3.0 rule (建祿·羊刃 first, month "
                "branch 本氣→中氣→餘氣 透干 order, no 羊刃 for yin day stems, 地支合化格 included)",
            ),
        )
    ]


def _special_structure_rule(chart: ChartSnapshot) -> list[_Draft]:
    s = depth.special_structures(chart)
    if s["accepted"]:
        listed = ", ".join(
            f"{x['name_ko']}({depth.VERDICT_KO[x['verdict']]}, {x['score']}점)"
            for x in s["accepted"]
        )
        text = (
            f"외격 판정({s['checked']}종 검사): {listed} 성립 — 외격으로 읽으면 억부 용신 후보와 "
            "반대 방향이 될 수 있음"
        )
    else:
        text = (
            f"외격 판정({s['checked']}종 검사): 성립하는 외격 없음 — 정격으로 해석하고 종격·화기격 "
            "해석을 하지 않음"
        )
    return [
        _Draft(
            kind="rule_derived",
            operands=s,
            text_ko=text,
            source_ref=f"{_library(chart)}#OegyeokAnalyzer",
            depends=frozenset(_pillars(chart)),
            assumptions=(depth.SPECIAL_STRUCTURE_ASSUMPTION,),
        )
    ]


def _daewoon_assumptions(chart: ChartSnapshot) -> list[str]:
    assumptions: list[str] = []
    if chart.certainty == "PARTIAL":
        assumptions.append(DAEWOON_PRIMARY_ONLY)
    if "DAEWOON_START_APPROXIMATE" in chart.warning_codes:
        assumptions.append(DAEWOON_START_APPROXIMATE)
    return assumptions


def _daewoon_rule(chart: ChartSnapshot) -> list[_Draft]:
    dw = chart.daewoon
    direction = "forward" if dw.forward else "backward"
    return [
        _Draft(
            kind="computed",
            operands={
                "index": i,
                "start_age": entry.start_age,
                "pillar": entry.pillar,
                "direction": direction,
            },
            text_ko=f"대운 {i + 1}: {entry.start_age}세 시작 {_ko(entry.pillar)} "
            f"({'순행' if dw.forward else '역행'})",
            source_ref=f"{_library(chart)}#Daewoon",
            depends=frozenset({"year", "month"}),
            assumptions=tuple(_daewoon_assumptions(chart)),
        )
        for i, entry in enumerate(dw.entries)
    ]


def _relations_ko(relations: list[dict[str, Any]]) -> str:
    return ", ".join(f"{_pos_ko(r['with'].split('+')[0])} {_ko(r['name'])}" for r in relations)


def _daewoon_flow_rule(chart: ChartSnapshot) -> list[_Draft]:
    favorable = depth.favorable_elements(chart)
    drafts = []
    for i, entry in enumerate(chart.daewoon.entries):
        sig = timing.signals(chart, entry.pillar, favorable=favorable)
        relations = timing.natal_relations(chart, entry.pillar)
        rel = _relations_ko(relations) or "원국과 뚜렷한 합충 없음"
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands={
                    "index": i,
                    "start_age": entry.start_age,
                    "pillar": entry.pillar,
                    "stem_ten_god": sig["stem_ten_god"],
                    "branch_ten_god": sig["branch_ten_god"],
                    "relations": relations,
                    "cues": sig["cues"],
                    "cautions": sig["cautions"],
                },
                text_ko=f"대운 {i + 1} ({entry.start_age}~{entry.start_age + 9}세) "
                f"{_ko(entry.pillar)}: 천간 {_ko(sig['stem_ten_god'])}, 지지 "
                f"{_ko(sig['branch_ten_god'])}. 원국 관계: {rel}. "
                f"결혼 단서: {timing.cues_ko(sig['cues'])}. "
                f"주의: {timing.cues_ko(sig['cautions'])}",
                source_ref=_rules_ref("DAEWOON_FLOW"),
                depends=frozenset(_pillars(chart)),
                assumptions=(
                    *_daewoon_assumptions(chart),
                    timing.TIMING_ASSUMPTION,
                    t.SPOUSE_STAR_ASSUMPTION,
                ),
            )
        )
    return drafts


def _sewoon_rule(chart: ChartSnapshot) -> list[_Draft]:
    return [
        _Draft(
            kind="computed",
            operands={"year": entry.year, "pillar": entry.pillar, "age": entry.age},
            text_ko=f"{entry.year}년 세운 {_ko(entry.pillar)}",
            source_ref=f"{_library(chart)}#Sewoon",
        )
        for entry in chart.sewoon
    ]


def _timing_window(chart: ChartSnapshot) -> tuple[int, int] | None:
    if not chart.sewoon:
        return None
    return chart.sewoon[0].year, len(chart.sewoon)


def _daewoon_ko(timeline: list[str]) -> str:
    names = ["자료 없음" if p == timing.DAEWOON_UNAVAILABLE else _ko(p) for p in timeline]
    return " → ".join(names) + (" (전환기)" if len(names) > 1 else "")


def _year_timing_rule(chart: ChartSnapshot) -> list[_Draft]:
    window = _timing_window(chart)
    if window is None:
        return []
    drafts = []
    for row in timing.year_rows(chart, *window):
        rel = _relations_ko(row["relations"]) or "원국과 뚜렷한 합충 없음"
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands=row,
                text_ko=f"{row['year']}년 {_ko(row['pillar'])} (순위 {row['rank']}, 핵심 단서 "
                f"{row['core_count']}개 / 전체 {row['cue_count']}개): 천간 "
                f"{_ko(row['stem_ten_god'])}, 지지 {_ko(row['branch_ten_god'])}, 대운 "
                f"{_daewoon_ko(row['daewoon'])}. 원국 관계: {rel}. 결혼 단서: "
                f"{timing.cues_ko(row['cues'])}. 주의: {timing.cues_ko(row['cautions'])}",
                source_ref=_rules_ref("YEAR_TIMING"),
                depends=frozenset(_pillars(chart)),
                assumptions=(
                    timing.TIMING_ASSUMPTION,
                    timing.RANK_ASSUMPTION,
                    timing.YEAR_PILLAR_ASSUMPTION,
                    t.SPOUSE_STAR_ASSUMPTION,
                    *_daewoon_assumptions(chart),
                ),
            )
        )
    return drafts


def _month_timing_rule(chart: ChartSnapshot) -> list[_Draft]:
    window = _timing_window(chart)
    if window is None:
        return []
    drafts = []
    for row in timing.top_years(timing.year_rows(chart, *window)):
        months = timing.month_rows(chart, row["pillar"])
        marked = [
            f"{'이듬해 ' if m['month_branch'] == '丑' else ''}"
            f"{int(m['starts'][:2])}월 {int(m['starts'][3:])}일경~ {_ko(m['pillar'])}"
            f"({timing.cues_ko(m['cues'])}"
            + (f" / 주의: {timing.cues_ko(m['cautions'])})" if m["cautions"] else ")")
            for m in months
            if m["cues"] or m["cautions"]
        ]
        drafts.append(
            _Draft(
                kind="rule_derived",
                operands={"year": row["year"], "year_pillar": row["pillar"], "months": months},
                text_ko=f"{row['year']}년({_ko(row['pillar'])}) 월별 단서: "
                + ("; ".join(marked) if marked else "두드러진 월 없음"),
                source_ref=_rules_ref("MONTH_TIMING"),
                depends=frozenset(_pillars(chart)),
                assumptions=(
                    timing.TIMING_ASSUMPTION,
                    timing.MONTH_ASSUMPTION,
                    t.SPOUSE_STAR_ASSUMPTION,
                ),
            )
        )
    return drafts


RULES: dict[str, Callable[[ChartSnapshot], list[_Draft]]] = {
    "PILLARS": _pillar_rule,
    "TEN_GODS": _ten_gods_rule,
    "HIDDEN_STEMS": _hidden_stems_rule,
    "TWELVE_STAGES": _twelve_stages_rule,
    "SPOUSE_PALACE": _spouse_palace_rule,
    "SPOUSE_STAR": _spouse_star_rule,
    "ELEMENTS": _elements_rule,
    "STRENGTH": _strength_rule,
    "YONGSIN": _yongsin_rule,
    "JOHU": _johu_rule,
    "BRANCH_RELATIONS": _branch_relations_rule,
    "STEM_RELATIONS": _stem_relations_rule,
    "SINSAL": _sinsal_rule,
    "GONGMANG": _gongmang_rule,
    "GYEOKGUK": _gyeokguk_rule,
    "SPECIAL_STRUCTURE": _special_structure_rule,
    "DAEWOON": _daewoon_rule,
    "DAEWOON_FLOW": _daewoon_flow_rule,
    "SEWOON": _sewoon_rule,
    "YEAR_TIMING": _year_timing_rule,
    "MONTH_TIMING": _month_timing_rule,
}
assert tuple(RULES) == RULE_ORDER


def _differing_positions(chart: ChartSnapshot) -> set[str]:
    primary = (chart.year_pillar, chart.month_pillar, chart.day_pillar, chart.hour_pillar)
    differing: set[str] = set()
    for alt in chart.alternatives:
        other = (alt.year_pillar, alt.month_pillar, alt.day_pillar, alt.hour_pillar)
        differing |= {p for p, a, b in zip(POSITIONS, primary, other, strict=True) if a != b}
    return differing


def sort_key(order: tuple[str, ...]) -> Callable[[Evidence], tuple[Any, ...]]:
    """Rule order, then the natural sequence (daewoon index, year), then id."""

    def key(e: Evidence) -> tuple[Any, ...]:
        ops = e.operands
        seq = ops.get("index", ops.get("year", -1))
        return (order.index(e.rule_code), seq if isinstance(seq, int) else -1, e.id)

    return key


def build_individual_evidence(chart: ChartSnapshot, subject_key: str) -> list[Evidence]:
    """Deterministic evidence catalog for one chart, sorted by rule order then sequence/id."""
    if not _SUBJECT_KEY.fullmatch(subject_key):
        raise ValueError(f"subject_key must match ^[A-Za-z0-9]+$; got {subject_key!r}")
    differing = _differing_positions(chart)
    evidence: list[Evidence] = []
    for code, rule in RULES.items():
        for draft in rule(chart):
            assumptions = list(draft.assumptions)
            if draft.depends & differing:
                assumptions.append(BOUNDARY_ASSUMPTION)
            evidence.append(
                Evidence(
                    id=evidence_id(subject_key, code, draft.operands),
                    kind=draft.kind,
                    rule_code=code,
                    operands=draft.operands,
                    text_ko=draft.text_ko,
                    source_ref=draft.source_ref,
                    assumptions=assumptions,
                )
            )
    ids = [e.id for e in evidence]
    if len(ids) != len(set(ids)):
        raise RuntimeError("evidence id collision: operands must distinguish items")
    return sorted(evidence, key=sort_key(RULE_ORDER))
