"""Common favorable years for a couple (timing-score-v1).

A year is a candidate only when it is favorable for BOTH people: each has at least one core
cue and neither has a spouse-palace clash. Candidates are ordered by the smaller of the two
signals (then their sum, then the year), never by the mean, so a year that is strong for one
person and weak for the other does not rise to the top. When no year qualifies, the result
says so instead of picking one.
"""

from __future__ import annotations

from typing import Any

from fateweave.domain.timing.individual import LIFE_AGES, birth_year, year_rows
from fateweave.models.facts import ChartSnapshot

BLOCKING_CAUTIONS = ("PALACE_CHUNG",)
NO_CANDIDATE_REASON = (
    "이 기간에 두 사람 모두 핵심 결혼 단서가 있고 어느 쪽에도 배우자궁 충이 없는 해가 없음"
)


def _side(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal": row["signal"],
        "core_count": row["core_count"],
        "cues": row["cues"],
        "cautions": row["cautions"],
    }


def _qualifies(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["core_count"] < 1 or b["core_count"] < 1:
        return False
    return not any(c in BLOCKING_CAUTIONS for c in a["cautions"] + b["cautions"])


def overlap(rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]]) -> dict[str, Any]:
    """Join two people's year rows (same years) into per-year records and ranked candidates."""
    by_year_b = {r["year"]: r for r in rows_b}
    years = []
    for a in rows_a:
        b = by_year_b[a["year"]]
        years.append(
            {
                "year": a["year"],
                "pillar": a["pillar"],
                "a": _side(a),
                "b": _side(b),
                "candidate": _qualifies(a, b),
                "candidate_rank": None,
            }
        )
    candidates = sorted(
        (y for y in years if y["candidate"]),
        key=lambda y: (
            -min(y["a"]["signal"], y["b"]["signal"]),
            -(y["a"]["signal"] + y["b"]["signal"]),
            y["year"],
        ),
    )
    for rank, y in enumerate(candidates, start=1):
        y["candidate_rank"] = rank
    return {
        "years": years,
        "candidates": [
            {
                "year": y["year"],
                "pillar": y["pillar"],
                "a_signal": y["a"]["signal"],
                "b_signal": y["b"]["signal"],
            }
            for y in candidates
        ],
        "no_candidate_reason": None if candidates else NO_CANDIDATE_REASON,
    }


def life_overlap(
    a: ChartSnapshot, b: ChartSnapshot, ages: tuple[int, int] = LIFE_AGES, limit: int = 5
) -> dict[str, Any]:
    """Overlap candidates over the years in which both people are inside the ages window."""
    start = max(birth_year(a), birth_year(b)) + ages[0]
    end = min(birth_year(a), birth_year(b)) + ages[1]
    if start > end:
        return {
            "from_year": start,
            "to_year": end,
            "candidates": [],
            "no_candidate_reason": f"두 사람의 나이가 동시에 {ages[0]}~{ages[1]}세인 해가 없음",
        }
    years = end - start + 1
    result = overlap(year_rows(a, start, years), year_rows(b, start, years))
    return {
        "from_year": start,
        "to_year": end,
        "candidates": result["candidates"][:limit],
        "no_candidate_reason": result["no_candidate_reason"],
    }
