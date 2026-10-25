"""Individual myeongri evidence catalog — policy rules-v1.

`build_individual_evidence` reads only the ChartSnapshot, so stored snapshots always rebuild
the same catalog (same IDs, same digest). Rules:

- PILLARS / TEN_GODS / DAEWOON / SEWOON: copied from the snapshot (manse-v1, korean-saju).
- SPOUSE_PALACE (日支), ELEMENTS (surface 五行 count), BRANCH_RELATIONS (positional 六合, 三合,
  沖, 刑, 破, 害): traditional fixed tables below, applied to the snapshot pillars.
  半合 is not listed: which pairs count as 半合 differs between schools.
- GYEOKGUK: korean-saju's deterministic GyeokgukCalculator on the snapshot pillars, only when
  the hour is known (its 透干 check reads the hour stem); otherwise an interpretation cue.
- JOHU: the month-branch season only; the element 調候 calls for is not judged.
- YONGSIN: an interpretation cue only. korean-saju's YongsinDeriver is a library-specific
  composite of school-dependent heuristics, so no 用神 is asserted as a fact.

Unknown hour: nothing references the hour pillar. PARTIAL charts: items whose operands depend
on a pillar that differs in an alternative carry BOUNDARY_ASSUMPTION.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any, Literal

from korean_saju import GanJi, GyeokgukCalculator, Saju

from fateweave.config import Settings
from fateweave.models.facts import ChartSnapshot, Evidence

RULE_ORDER: tuple[str, ...] = (
    "PILLARS",
    "TEN_GODS",
    "SPOUSE_PALACE",
    "ELEMENTS",
    "BRANCH_RELATIONS",
    "GYEOKGUK",
    "YONGSIN",
    "JOHU",
    "DAEWOON",
    "SEWOON",
)
BOUNDARY_ASSUMPTION = "depends on primary pillar set; alternatives exist (BOUNDARY_REVIEW_REQUIRED)"
DAEWOON_PRIMARY_ONLY = "computed for primary pillar set only"
_SUBJECT_KEY = re.compile(r"[A-Za-z0-9]+")

POSITIONS = ("year", "month", "day", "hour")
_POS_KO = {"year": "연", "month": "월", "day": "일", "hour": "시"}

_STEM_ELEMENT = dict(zip("甲乙丙丁戊己庚辛壬癸", "木木火火土土金金水水", strict=True))
_BRANCH_ELEMENT = dict(zip("子丑寅卯辰巳午未申酉戌亥", "水土木木土火火土金金土水", strict=True))
_ELEMENT_ORDER = "木火土金水"
_SEASON = dict(zip("寅卯辰巳午未申酉戌亥子丑", "春春春夏夏夏秋秋秋冬冬冬", strict=True))
_SEASON_KO = {"春": "봄", "夏": "여름", "秋": "가을", "冬": "겨울"}

# (relation, Korean label, member branches) — rules-v1 traditional tables.
_PAIR_RELATIONS: tuple[tuple[str, str, str], ...] = (
    *(("合", "육합", m) for m in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")),
    *(("沖", "충", m) for m in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")),
    *(("刑", "형", m) for m in ("子卯", "辰辰", "午午", "酉酉", "亥亥")),  # 相刑 + 自刑
    *(("破", "파", m) for m in ("子酉", "卯午", "巳申", "寅亥", "丑辰", "未戌")),
    *(("害", "해", m) for m in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")),
)
_TRIPLE_RELATIONS: tuple[tuple[str, str, str], ...] = (
    *(("三合", "삼합", m) for m in ("申子辰", "寅午戌", "巳酉丑", "亥卯未")),
    *(("三刑", "삼형", m) for m in ("寅巳申", "丑戌未")),
)

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


def _pillars(chart: ChartSnapshot) -> dict[str, str]:
    """Known pillars in position order (hour omitted when unknown)."""
    values = (chart.year_pillar, chart.month_pillar, chart.day_pillar, chart.hour_pillar)
    return {p: v for p, v in zip(POSITIONS, values, strict=True) if v is not None}


def _library(chart: ChartSnapshot) -> str:
    return f"korean-saju=={chart.library_version}"


def _rules_ref(code: str) -> str:
    return f"{Settings.RULE_VERSION}#{code}"


def _pillar_rule(chart: ChartSnapshot) -> list[_Draft]:
    return [
        _Draft(
            kind="computed",
            operands={"position": pos, "pillar": pillar},
            text_ko=f"{_POS_KO[pos]}주 {pillar}",
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
        label = f"{_POS_KO[pos]}{'간' if part == 'stem' else '지'}"
        basis = "" if part == "stem" else " (지지 본기 기준)"
        drafts.append(
            _Draft(
                kind="computed",
                operands={"position": key, "target": target, "day_stem": day_stem, "ten_god": god},
                text_ko=f"{label} {target}: 일간 {day_stem} 기준 {god}{basis}",
                source_ref=f"{_library(chart)}#ShipsinCalculator",
                depends=frozenset({pos, "day"}),
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
            text_ko=f"배우자궁(일지) {branch}: 일간 {chart.day_pillar[0]} 기준 {god} (본기 기준)",
            source_ref=_rules_ref("SPOUSE_PALACE"),
            depends=frozenset({"day"}),
        )
    ]


def _elements_rule(chart: ChartSnapshot) -> list[_Draft]:
    pillars = _pillars(chart)
    counts = dict.fromkeys(_ELEMENT_ORDER, 0)
    for pillar in pillars.values():
        counts[_STEM_ELEMENT[pillar[0]]] += 1
        counts[_BRANCH_ELEMENT[pillar[1]]] += 1
    scope = "·".join(_POS_KO[p] for p in pillars) + "주"
    summary = " ".join(f"{e}{n}" for e, n in counts.items())
    assumptions = () if chart.hour_pillar else ("hour pillar unknown: year/month/day only",)
    return [
        _Draft(
            kind="rule_derived",
            operands={
                "basis": "surface_stems_and_branches",
                "positions": list(pillars),
                "counts": counts,
            },
            text_ko=f"{scope} {2 * len(pillars)}글자 표면 오행(지장간 미포함): {summary}",
            source_ref=_rules_ref("ELEMENTS"),
            depends=frozenset(pillars),
            assumptions=assumptions,
        )
    ]


def _branch_relations_rule(chart: ChartSnapshot) -> list[_Draft]:
    branches = [(pos, pillar[1]) for pos, pillar in _pillars(chart).items()]
    drafts = []
    for size, table in ((2, _PAIR_RELATIONS), (3, _TRIPLE_RELATIONS)):
        for combo in combinations(branches, size):
            found = sorted(b for _, b in combo)
            for relation, label, members in table:
                if found != sorted(members):
                    continue
                name = f"{members}{relation}"
                where = " · ".join(f"{_POS_KO[p]}지 {b}" for p, b in combo)
                drafts.append(
                    _Draft(
                        kind="rule_derived",
                        operands={
                            "relation": relation,
                            "name": name,
                            "positions": [f"{p}_branch" for p, _ in combo],
                            "branches": [b for _, b in combo],
                        },
                        text_ko=f"{where}: {label}({name}) 관계",
                        source_ref=_rules_ref("BRANCH_RELATIONS"),
                        depends=frozenset(p for p, _ in combo),
                    )
                )
    return drafts


def _gyeokguk_rule(chart: ChartSnapshot) -> list[_Draft]:
    if chart.hour_pillar is None:
        return [
            _Draft(
                kind="interpretation_cue",
                operands={"status": "not_determined", "missing": "birth_time"},
                text_ko="출생 시각 미상: 시간(時干) 투간 여부를 알 수 없어 격국을 판정하지 않음",
                source_ref=_rules_ref("GYEOKGUK"),
            )
        ]
    saju = Saju(
        year_pillar=_ganji(chart.year_pillar),
        month_pillar=_ganji(chart.month_pillar),
        day_pillar=_ganji(chart.day_pillar),
        hour_pillar=_ganji(chart.hour_pillar),
        # Required by the dataclass; GyeokgukCalculator reads only the pillars.
        kst_moment=datetime.fromisoformat(chart.solar_date),
        longitude=chart.longitude,
    )
    result = GyeokgukCalculator.determine(saju)
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
            text_ko=f"격국(korean-saju 판정 규칙): {g.hanja}({g.hangul}), 근거 {result.basis}",
            source_ref=f"{_library(chart)}#GyeokgukCalculator",
            depends=frozenset(POSITIONS),
            assumptions=(
                "school-dependent criterion: korean-saju 0.3.0 rule (建祿·羊刃 first, month "
                "branch 本氣→中氣→餘氣 透干 order, no 羊刃 for yin day stems, 地支合化格 included)",
            ),
        )
    ]


def _ganji(hanja: str) -> GanJi:
    ganji = GanJi.from_hanja(hanja)
    if ganji is None:
        raise ValueError(f"invalid pillar in snapshot: {hanja!r}")
    return ganji


def _yongsin_rule(chart: ChartSnapshot) -> list[_Draft]:
    return [
        _Draft(
            kind="interpretation_cue",
            operands={
                "status": "not_computed",
                "premise": "용신 선정은 억부·조후·격국·통관·병약 등 관법(학파)에 따라 달라짐",
            },
            text_ko="용신은 관법에 따라 달라지는 해석 전제이며, 확정 값을 산출하지 않음",
            source_ref=_rules_ref("YONGSIN"),
        )
    ]


def _johu_rule(chart: ChartSnapshot) -> list[_Draft]:
    branch = chart.month_pillar[1]
    season = _SEASON[branch]
    return [
        _Draft(
            kind="rule_derived",
            operands={"month_branch": branch, "season": season},
            text_ko=f"월지 {branch}: 계절상 {_SEASON_KO[season]}({season})",
            source_ref=_rules_ref("JOHU"),
            depends=frozenset({"month"}),
        ),
        _Draft(
            kind="interpretation_cue",
            operands={
                "status": "not_determined",
                "premise": "조후(한난조습)로 필요한 오행의 판단은 관법에 따라 달라짐",
            },
            text_ko="조후상 필요한 오행은 관법에 따라 달라지는 해석 전제이며, 판정하지 않음",
            source_ref=_rules_ref("JOHU"),
        ),
    ]


def _daewoon_rule(chart: ChartSnapshot) -> list[_Draft]:
    dw = chart.daewoon
    direction = "forward" if dw.forward else "backward"
    assumptions: list[str] = []
    if chart.certainty == "PARTIAL":
        assumptions.append(DAEWOON_PRIMARY_ONLY)
    if "DAEWOON_START_APPROXIMATE" in chart.warning_codes:
        assumptions.append("start age approximate: birth time unknown (DAEWOON_START_APPROXIMATE)")
    return [
        _Draft(
            kind="computed",
            operands={
                "index": i,
                "start_age": entry.start_age,
                "pillar": entry.pillar,
                "direction": direction,
            },
            text_ko=f"대운 {i + 1}: {entry.start_age}세 시작 {entry.pillar} "
            f"({'순행' if dw.forward else '역행'})",
            source_ref=f"{_library(chart)}#Daewoon",
            depends=frozenset({"year", "month"}),
            assumptions=tuple(assumptions),
        )
        for i, entry in enumerate(dw.entries)
    ]


def _sewoon_rule(chart: ChartSnapshot) -> list[_Draft]:
    return [
        _Draft(
            kind="computed",
            operands={"year": entry.year, "pillar": entry.pillar, "age": entry.age},
            text_ko=f"{entry.year}년 세운 {entry.pillar}",
            source_ref=f"{_library(chart)}#Sewoon",
        )
        for entry in chart.sewoon
    ]


RULES: dict[str, Callable[[ChartSnapshot], list[_Draft]]] = {
    "PILLARS": _pillar_rule,
    "TEN_GODS": _ten_gods_rule,
    "SPOUSE_PALACE": _spouse_palace_rule,
    "ELEMENTS": _elements_rule,
    "BRANCH_RELATIONS": _branch_relations_rule,
    "GYEOKGUK": _gyeokguk_rule,
    "YONGSIN": _yongsin_rule,
    "JOHU": _johu_rule,
    "DAEWOON": _daewoon_rule,
    "SEWOON": _sewoon_rule,
}
assert tuple(RULES) == RULE_ORDER


def _differing_positions(chart: ChartSnapshot) -> set[str]:
    primary = (chart.year_pillar, chart.month_pillar, chart.day_pillar, chart.hour_pillar)
    differing: set[str] = set()
    for alt in chart.alternatives:
        other = (alt.year_pillar, alt.month_pillar, alt.day_pillar, alt.hour_pillar)
        differing |= {p for p, a, b in zip(POSITIONS, primary, other, strict=True) if a != b}
    return differing


def build_individual_evidence(chart: ChartSnapshot, subject_key: str) -> list[Evidence]:
    """Deterministic evidence catalog for one chart, sorted by rule order then id."""
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
    return sorted(evidence, key=lambda e: (RULE_ORDER.index(e.rule_code), e.id))
