"""Assemble a compat-score assessment from two charts (Fact -> Assessment -> Scoring).

`assess(a, b)` is deterministic and order independent (only the A/B labels and the two
directions of the element complement swap). When the couple evidence catalog is passed, each
contribution cites the Fact evidence it scores; the evidence IDs are recomputed from the same
operands couple.py uses, so no lookup by text is needed.

Incomplete data never scores 0 (spec §5): with an hour unknown the element balance uses six
characters and the overall structure skips hour pairs (REDUCED_SCOPE); when either chart has
alternative pillar sets the score is also computed for every combination and reported as a
range.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import product
from typing import Any

from fateweave.domain import depth
from fateweave.domain import tables as t
from fateweave.domain.compatibility import scoring
from fateweave.domain.compatibility.models import (
    CompatibilityAssessment,
    ComponentScore,
    Contribution,
)
from fateweave.domain.compatibility.policies import DEFAULT_VERSION, CompatPolicy, get
from fateweave.domain.couple import PAIR_SUBJECT_KEY, _entries
from fateweave.domain.glossary import hangul
from fateweave.domain.rules import evidence_id
from fateweave.models.facts import ChartSnapshot, Evidence

_POS_KO = {"year": "연", "month": "월", "day": "일", "hour": "시"}
_PART_KO = {"stem": "간", "branch": "지"}


class _Facts:
    """Fact evidence IDs of a couple catalog, addressed by their operands."""

    def __init__(self, evidence: Sequence[Evidence] | None) -> None:
        self._ids = {e.id for e in evidence or ()}
        self._by_rule: dict[str, list[Evidence]] = {}
        for e in evidence or ():
            self._by_rule.setdefault(e.rule_code, []).append(e)

    def relation(
        self, rule: str, rel: str, members: str, entries: list[dict[str, str]]
    ) -> str | None:
        operands = {"relation": rel, "name": f"{members}{rel}", "entries": _entries(*entries)}
        eid = evidence_id(PAIR_SUBJECT_KEY, rule, operands)
        return eid if eid in self._ids else None

    def single(self, rule: str) -> str | None:
        items = self._by_rule.get(rule, [])
        return items[0].id if len(items) == 1 else None


def _members(table: tuple[tuple[str, str, str], ...], rel: str, x: str, y: str) -> str | None:
    return next(
        (m for r, _, m in table if r == rel and sorted(x + y) == sorted(m)),
        None,
    )


def _surface(chart: ChartSnapshot) -> dict[str, int]:
    counts = dict.fromkeys(t.ELEMENT_ORDER, 0)
    for pillar in depth.pillars(chart).values():
        counts[t.STEM_ELEMENT[pillar[0]]] += 1
        counts[t.BRANCH_ELEMENT[pillar[1]]] += 1
    return counts


def _needs(chart: ChartSnapshot, policy: CompatPolicy) -> tuple[set[str], set[str], dict[str, int]]:
    counts = _surface(chart)
    need = {e for e, n in counts.items() if n == 0} | set(depth.johu(chart)["elements"])
    excess = {e for e, n in counts.items() if n >= policy.excess_threshold}
    return need, excess, counts


def _day_master(a: ChartSnapshot, b: ChartSnapshot, policy: CompatPolicy, facts: _Facts):
    sa, sb = a.day_pillar[0], b.day_pillar[0]
    kind = scoring.stem_relation(sa, sb)
    if kind in ("合", "沖"):
        members = _members(t.STEM_RELATIONS, kind, sa, sb) or ""
        relation_id = facts.relation(
            "COUPLE_DAY_STEM",
            kind,
            members,
            [{"position": "day_stem", "value": sa}, {"position": "day_stem", "value": sb}],
        )
    else:
        relation_id = facts.single("COUPLE_DAY_STEM_ELEMENT")
    return scoring.day_master(
        sa,
        a.day_pillar[1],
        a.gender_for_daewoon,
        sb,
        b.day_pillar[1],
        b.gender_for_daewoon,
        policy,
        relation_evidence_id=relation_id,
        star_evidence_id=facts.single("COUPLE_SPOUSE_STAR_MATCH"),
    )


def _spouse_palace(a: ChartSnapshot, b: ChartSnapshot, policy: CompatPolicy, facts: _Facts):
    ba, bb = a.day_pillar[1], b.day_pillar[1]
    ids: dict[str, str] = {}
    for rel in scoring.branch_relations(ba, bb):
        members = _members(t.PAIR_RELATIONS, rel, ba, bb)
        if members is None:  # 半合 is derived from the 三合 groups; no pair evidence exists
            continue
        eid = facts.relation(
            "COUPLE_DAY_BRANCH",
            rel,
            members,
            [{"position": "day_branch", "value": ba}, {"position": "day_branch", "value": bb}],
        )
        if eid:
            ids[rel] = eid
    return scoring.spouse_palace(ba, bb, policy, ids)


def _element_balance(a: ChartSnapshot, b: ChartSnapshot, policy: CompatPolicy) -> ComponentScore:
    need_a, excess_a, counts_a = _needs(a, policy)
    need_b, excess_b, counts_b = _needs(b, policy)
    b_to_a = scoring.element_direction(need_a, excess_a, counts_b, policy)
    a_to_b = scoring.element_direction(need_b, excess_b, counts_a, policy)
    score = (a_to_b + b_to_a) / 2
    contributions = [
        Contribution(
            rule="E.b_to_a",
            points=round(b_to_a, 1),
            basis=f"B가 A를 보완: A의 필요 오행 {scoring.elements_ko(need_a)}, "
            f"A의 과다 오행 {scoring.elements_ko(excess_a)}",
        ),
        Contribution(
            rule="E.a_to_b",
            points=round(a_to_b, 1),
            basis=f"A가 B를 보완: B의 필요 오행 {scoring.elements_ko(need_b)}, "
            f"B의 과다 오행 {scoring.elements_ko(excess_b)}",
        ),
    ]
    gap = abs(a_to_b - b_to_a)
    if gap >= policy.asymmetry_threshold:
        score -= policy.asymmetry_penalty
        contributions.append(
            Contribution(
                rule="E.asymmetry",
                points=-policy.asymmetry_penalty,
                basis=f"두 방향 보완도 차이 {round(gap, 1)}",
            )
        )
    reduced = a.hour_pillar is None or b.hour_pillar is None
    return ComponentScore(
        key="element_balance",
        score=round(scoring.clamp(score)),
        status="REDUCED_SCOPE" if reduced else "OK",
        contributions=contributions,
        details={
            "b_to_a": round(b_to_a, 1),
            "a_to_b": round(a_to_b, 1),
            "need": {"A": sorted(need_a), "B": sorted(need_b)},
            "excess": {"A": sorted(excess_a), "B": sorted(excess_b)},
        },
    )


def _overall_structure(
    a: ChartSnapshot, b: ChartSnapshot, policy: CompatPolicy, facts: _Facts
) -> ComponentScore:
    pa, pb = depth.pillars(a), depth.pillars(b)
    positive = negative = 0.0
    contributions: list[Contribution] = []
    seen: set[tuple[str, frozenset[tuple[str, str]]]] = set()
    for pos_a, pos_b in product(pa, pb):
        if (pos_a, pos_b) == ("day", "day"):
            continue  # scored by D (stems) and P (branches)
        for part, idx in (("stem", 0), ("branch", 1)):
            va, vb = pa[pos_a][idx], pb[pos_b][idx]
            if part == "stem":
                names = [rel for rel, _, _ in t.stem_relations(va, vb)]
                table = t.STEM_RELATIONS
            else:
                names = scoring.branch_relations(va, vb)
                table = t.PAIR_RELATIONS
            if not names:
                continue
            # A年·B月 and A月·B年 with the same values are one fact (as in the couple catalog):
            # count it once.
            fact_key = (part, frozenset({(f"{pos_a}_{part}", va), (f"{pos_b}_{part}", vb)}))
            if fact_key in seen:
                continue
            seen.add(fact_key)
            where = (
                f"A {_POS_KO[pos_a]}{_PART_KO[part]} {hangul(va)} · "
                f"B {_POS_KO[pos_b]}{_PART_KO[part]} {hangul(vb)}"
            )
            candidates = []
            for name in names:
                members = _members(table, name, va, vb)
                eid = (
                    facts.relation(
                        "COUPLE_CROSS_PILLARS",
                        name,
                        members,
                        [
                            {"position": f"{pos_a}_{part}", "value": va},
                            {"position": f"{pos_b}_{part}", "value": vb},
                        ],
                    )
                    if members
                    else None
                )
                points = float(policy.structure_deltas[name])
                candidates.append((name, points, f"{where}: {hangul(name)}", eid))
            _, items = scoring.pick_strongest(candidates, "W.")
            contributions += items
            for c in items:
                if c.applied and c.points > 0:
                    positive += c.points
                elif c.applied:
                    negative += c.points
    positive = min(positive, policy.structure_cap)
    negative = max(negative, -policy.structure_cap)
    reduced = a.hour_pillar is None or b.hour_pillar is None
    return ComponentScore(
        key="overall_structure",
        score=round(scoring.clamp(policy.structure_base + positive + negative)),
        status="REDUCED_SCOPE" if reduced else "OK",
        contributions=contributions,
        details={"positive": positive, "negative": negative, "cap": policy.structure_cap},
    )


def _components(
    a: ChartSnapshot, b: ChartSnapshot, policy: CompatPolicy, facts: _Facts
) -> dict[str, ComponentScore]:
    return {
        "day_master": _day_master(a, b, policy, facts),
        "spouse_palace": _spouse_palace(a, b, policy, facts),
        "element_balance": _element_balance(a, b, policy),
        "overall_structure": _overall_structure(a, b, policy, facts),
    }


def _total(components: dict[str, ComponentScore], policy: CompatPolicy) -> int:
    available = {k: c for k, c in components.items() if c.score is not None}
    weight = sum(policy.weights[k] for k in available)
    return round(sum(policy.weights[k] * c.score for k, c in available.items()) / weight)


def _variants(chart: ChartSnapshot) -> list[ChartSnapshot]:
    variants = [chart]
    for alt in chart.alternatives:
        update: dict[str, Any] = {
            "year_pillar": alt.year_pillar,
            "month_pillar": alt.month_pillar,
            "day_pillar": alt.day_pillar,
            "hour_pillar": alt.hour_pillar,
        }
        variants.append(chart.model_copy(update=update))
    return variants


def assess(
    a: ChartSnapshot,
    b: ChartSnapshot,
    evidence: Sequence[Evidence] | None = None,
    version: str = DEFAULT_VERSION,
) -> CompatibilityAssessment:
    policy = get(version)
    components = _components(a, b, policy, _Facts(evidence))
    score = _total(components, policy)

    excluded: list[str] = []
    for label, chart in (("A", a), ("B", b)):
        if chart.hour_pillar is None:
            excluded.append(
                f"{label}의 출생 시각 미상: 시주를 빼고 오행 보완(6글자)과 전체 명식 조화를 계산함"
            )
    score_range = None
    if a.alternatives or b.alternatives:
        totals = [
            _total(_components(va, vb, policy, _Facts(None)), policy)
            for va, vb in product(_variants(a), _variants(b))
        ]
        score_range = [min(totals), max(totals)]
        excluded.append(
            "명식 경계(시주·일주·절기)에 대안이 있어 대안 명식별 점수를 함께 계산함: "
            f"{score_range[0]}~{score_range[1]}"
        )
    partial = bool(score_range) or any(c.status != "OK" for c in components.values())
    return CompatibilityAssessment(
        scoring_version=policy.version,
        status="PARTIAL" if partial else "OK",
        score=score,
        score_range=score_range,
        weights=dict(policy.weights),
        components=components,
        excluded=excluded,
    )
