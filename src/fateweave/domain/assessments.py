"""Couple assessments (spec §7): the compat-score index and the common favorable years.

`build_couple_assessments(a, b, catalog, ...)` returns the `assessments` response block and the
evidence that claims cite for it:

- COMPAT_SCORE: the total interpretive index (0-100), its display grade, status and, when either
  chart has alternative pillar sets, the range over them.
- COMPAT_COMPONENT: one item per scoring area (일간 관계, 배우자궁, 오행 보완, 전체 명식 조화)
  with its score, weight and the applied rules (each citing the Fact evidence it scores).

The block's timing part only re-labels COUPLE_TIMING_OVERLAP / COUPLE_LIFE_TIMING (it adds no
new judgement): each candidate year cites its COUPLE_TIMING evidence. Pair operands stay order
independent, like the rest of the couple catalog. The index is not a probability.
"""

from __future__ import annotations

from typing import Any

from fateweave.domain import compatibility, timing
from fateweave.domain.compatibility import policies
from fateweave.domain.compatibility.models import CompatibilityAssessment, ComponentScore
from fateweave.domain.couple import PAIR_SUBJECT_KEY
from fateweave.domain.rules import BOUNDARY_ASSUMPTION, _rules_ref, canonical_json, evidence_id
from fateweave.models.facts import ChartSnapshot, Evidence

COMPONENT_KO = {
    "day_master": "일간 관계",
    "spouse_palace": "배우자궁",
    "element_balance": "오행 보완",
    "overall_structure": "전체 명식 조화",
}
_STATUS_KO = {"OK": "", "REDUCED_SCOPE": ", 범위 축소", "UNAVAILABLE": ", 계산 불가"}
# Contributions whose points are a level (0-100), not a delta.
_ABSOLUTE = ("D.relation.", "E.a_to_b", "E.b_to_a")
SCORE_ASSUMPTION = (
    "compat-score interpretive index: Fateweave design hypothesis (rule table and weights), "
    "not calibrated against relationship outcomes; not a probability"
)
REDUCED_ASSUMPTION = (
    "hour pillar unknown: element balance uses six characters and overall structure skips "
    "hour pairs (REDUCED_SCOPE), never scored as 0"
)


def scoring_versions(mode: str) -> dict[str, str]:
    """Policy versions of the scores in a prepared analysis (recorded with the snapshot)."""
    versions = {"timing_score": timing.TIMING_VERSION}
    if mode == "couple":
        versions["compat_score"] = policies.DEFAULT_VERSION
    return versions


def _points(rule: str, points: float) -> str:
    return f"{points:g}" if rule.startswith(_ABSOLUTE) else f"{points:+g}"


def _component_operands(version: str, weight: float, comp: ComponentScore) -> dict[str, Any]:
    applied = [
        {"rule": c.rule, "points": c.points, "evidence_id": c.evidence_id}
        for c in comp.contributions
        if c.applied and c.rule not in ("E.a_to_b", "E.b_to_a")
    ]
    operands: dict[str, Any] = {
        "scoring_version": version,
        "component": comp.key,
        "score": comp.score,
        "status": comp.status,
        "weight": weight,
        "applied": sorted(applied, key=canonical_json),
    }
    if comp.key == "element_balance":
        # The two directions swap with the argument order; keep them sorted (A/B in text only).
        operands["directions"] = sorted([comp.details["a_to_b"], comp.details["b_to_a"]])
    return operands


def _component_text(weight: float, comp: ComponentScore) -> str:
    head = (
        f"{COMPONENT_KO[comp.key]} {comp.score}점 (가중치 {round(weight * 100)}%"
        f"{_STATUS_KO[comp.status]})"
    )
    parts = [f"{c.basis} [{_points(c.rule, c.points)}]" for c in comp.contributions if c.applied]
    return f"{head}: {'; '.join(parts) if parts else '해당 관계 없음(기준점)'}"


def _score_text(result: CompatibilityAssessment, grade: str) -> str:
    text = f"궁합 지수 {result.score}/{result.scale} — {grade} (해석 지수이며 확률이 아님)"
    if result.score_range:
        low, high = result.score_range
        text += f"; 대안 명식까지 보면 {low}~{high}"
    reduced = [COMPONENT_KO[k] for k, c in result.components.items() if c.status != "OK"]
    if reduced:
        text += f"; 범위 축소 영역: {'·'.join(reduced)}"
    return text


def _evidence(rule: str, operands: dict[str, Any], text: str, assumptions: list[str]) -> Evidence:
    return Evidence(
        id=evidence_id(PAIR_SUBJECT_KEY, rule, operands),
        kind="rule_derived",
        rule_code=rule,
        operands=operands,
        text_ko=text,
        source_ref=f"{_rules_ref(rule)} ({operands['scoring_version']})",
        assumptions=assumptions,
    )


def _by_rule(catalog: list[Evidence], rule: str) -> list[Evidence]:
    return [e for e in catalog if e.rule_code == rule]


def _timing_block(
    result: dict[str, Any], year_ids: dict[int, str], source: Evidence | None
) -> dict[str, Any]:
    return {
        "timing_version": timing.TIMING_VERSION,
        "from_year": result["from_year"],
        "to_year": result["to_year"],
        "candidates": [
            {
                "year": c["year"],
                "pillar": c["pillar"],
                "a_signal": c["a_signal"],
                "b_signal": c["b_signal"],
                "evidence_ids": [year_ids[c["year"]]] if c["year"] in year_ids else [],
            }
            for c in result["candidates"]
        ],
        "no_candidate_reason": result["no_candidate_reason"],
        "evidence_id": source.id if source else None,
    }


def build_couple_assessments(
    a: ChartSnapshot,
    b: ChartSnapshot,
    catalog: list[Evidence],
    start_year: int,
    years: int,
) -> tuple[dict[str, Any], list[Evidence]]:
    """The `assessments` block and its COMPAT_SCORE / COMPAT_COMPONENT evidence."""
    result = compatibility.assess(a, b, catalog)
    policy = policies.get(result.scoring_version)
    grade = policies.grade(policy, result.score)

    common = [SCORE_ASSUMPTION]
    if a.hour_pillar is None or b.hour_pillar is None:
        common.append(REDUCED_ASSUMPTION)
    if a.alternatives or b.alternatives:
        common.append(BOUNDARY_ASSUMPTION)

    score_ev = _evidence(
        "COMPAT_SCORE",
        {
            "scoring_version": result.scoring_version,
            "score_type": result.score_type,
            "status": result.status,
            "score": result.score,
            "score_range": result.score_range,
            "scale": result.scale,
            "grade": grade,
        },
        _score_text(result, grade),
        common,
    )
    component_evs = {
        key: _evidence(
            "COMPAT_COMPONENT",
            _component_operands(result.scoring_version, result.weights[key], comp),
            _component_text(result.weights[key], comp),
            common,
        )
        for key, comp in result.components.items()
    }

    rows_a = timing.year_rows(a, start_year, years)
    rows_b = timing.year_rows(b, start_year, years)
    window = timing.overlap(rows_a, rows_b)
    window |= {"from_year": start_year, "to_year": start_year + years - 1}
    year_ids = {e.operands["year"]: e.id for e in _by_rule(catalog, "COUPLE_TIMING")}
    overlap_ev = next(iter(_by_rule(catalog, "COUPLE_TIMING_OVERLAP")), None)
    life_ev = next(iter(_by_rule(catalog, "COUPLE_LIFE_TIMING")), None)
    life = timing.life_overlap(a, b)

    block = {
        "compatibility": {
            **result.model_dump(mode="json"),
            "grade": grade,
            "evidence_id": score_ev.id,
            "component_evidence_ids": {k: e.id for k, e in component_evs.items()},
        },
        "timing_overlap": _timing_block(window, year_ids, overlap_ev),
        "life_overlap": {
            **_timing_block(life, {}, life_ev),
            "ages": list(timing.LIFE_AGES),
        },
    }
    return block, [score_ev, *component_evs.values()]
