"""compat-score rules as pure functions of stems, branches and element counts.

Facts (which relations hold) come from the traditional tables in domain/tables.py; this module
only decides how many points each fact is worth under a policy. Every fact that holds is kept
as a Contribution; when several relations of the same sign hold for one pair, only the largest
is applied (`applied=False` on the rest), so a pair is never double counted.
"""

from __future__ import annotations

from collections.abc import Iterable

from fateweave.domain import tables as t
from fateweave.domain.compatibility.models import ComponentScore, Contribution
from fateweave.domain.compatibility.policies import CompatPolicy
from fateweave.domain.glossary import ELEMENT_KO, hangul


def clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def branch_relations(a: str, b: str) -> list[str]:
    """Relation names between two branches: the pair table plus 半合 (same 三合 group)."""
    names = [rel for rel, _, _ in t.pair_relations(a, b)]
    if a != b and t.samhap_group(a) == t.samhap_group(b):
        names.append("半合")
    return names


def stem_relation(a: str, b: str) -> str:
    """The one day-stem relation by precedence: 合 > 沖 > 生 > 比和 > 剋."""
    rels = {rel for rel, _, _ in t.stem_relations(a, b)}
    if "合" in rels:
        return "合"
    if "沖" in rels:
        return "沖"
    ea, eb = t.STEM_ELEMENT[a], t.STEM_ELEMENT[b]
    if ea == eb:
        return "比和"
    if t.generates(ea, eb) or t.generates(eb, ea):
        return "生"
    return "剋"


def pick_strongest(
    candidates: Iterable[tuple[str, float, str, str | None]], prefix: str
) -> tuple[float, list[Contribution]]:
    """(name, points, basis, evidence_id) -> sum of the largest positive and largest negative."""
    items = list(candidates)
    best_pos = max((c for c in items if c[1] > 0), key=lambda c: c[1], default=None)
    best_neg = min((c for c in items if c[1] < 0), key=lambda c: c[1], default=None)
    contributions = [
        Contribution(
            rule=f"{prefix}{name}",
            points=points,
            basis=basis,
            evidence_id=evidence_id,
            applied=(name, points, basis, evidence_id) in (best_pos, best_neg),
        )
        for name, points, basis, evidence_id in items
    ]
    total = (best_pos[1] if best_pos else 0.0) + (best_neg[1] if best_neg else 0.0)
    return total, contributions


def spouse_palace(
    a: str, b: str, policy: CompatPolicy, evidence_ids: dict[str, str] | None = None
) -> ComponentScore:
    """P: the two day branches (spouse palaces)."""
    ids = evidence_ids or {}
    basis = f"배우자궁(일지) {hangul(a)} · {hangul(b)}"
    candidates = [
        (name, float(policy.palace_deltas[name]), f"{basis}: {hangul(name)}", ids.get(name))
        for name in branch_relations(a, b)
    ]
    delta, contributions = pick_strongest(candidates, "P.")
    return ComponentScore(
        key="spouse_palace",
        score=round(clamp(policy.palace_base + delta)),
        status="OK",
        contributions=contributions,
        details={"base": policy.palace_base, "relations": [c[0] for c in candidates]},
    )


def day_master(
    a_stem: str,
    a_branch: str,
    a_gender: str,
    b_stem: str,
    b_branch: str,
    b_gender: str,
    policy: CompatPolicy,
    relation_evidence_id: str | None = None,
    star_evidence_id: str | None = None,
) -> ComponentScore:
    """D: one day-stem relation plus each side's spouse-star bonus."""
    kind = stem_relation(a_stem, b_stem)
    base = policy.day_master_relation[kind]
    contributions = [
        Contribution(
            rule=f"D.relation.{kind}",
            points=base,
            basis=f"일간 {hangul(a_stem)} · {hangul(b_stem)}: {hangul(kind)}",
            evidence_id=relation_evidence_id,
        )
    ]
    score = float(base)
    sides = (
        ("A", a_stem, a_gender, b_stem, b_branch),
        ("B", b_stem, b_gender, a_stem, a_branch),
    )
    for label, me, gender, other_stem, other_branch in sides:
        stars = t.SPOUSE_STARS[gender]
        stem_god = t.ten_god(me, other_stem)
        if stem_god in stars:
            score += policy.spouse_star_stem_bonus
            contributions.append(
                Contribution(
                    rule="D.spouse_star_stem",
                    points=policy.spouse_star_stem_bonus,
                    basis=f"{label} 기준 상대 일간 {hangul(other_stem)} = "
                    f"{hangul(stem_god)}(배우자성)",
                    evidence_id=star_evidence_id,
                )
            )
        branch_god = t.branch_ten_god(me, other_branch)
        if branch_god in stars:
            score += policy.spouse_star_branch_bonus
            contributions.append(
                Contribution(
                    rule="D.spouse_star_branch",
                    points=policy.spouse_star_branch_bonus,
                    basis=f"{label} 기준 상대 일지 {hangul(other_branch)} 본기 = "
                    f"{hangul(branch_god)}(배우자성)",
                    evidence_id=star_evidence_id,
                )
            )
    return ComponentScore(
        key="day_master",
        score=round(clamp(score)),
        status="OK",
        contributions=contributions,
        details={"relation": kind},
    )


def element_direction(
    need: set[str], excess: set[str], partner_counts: dict[str, int], policy: CompatPolicy
) -> float:
    """How much the partner supplies one person's needs (0..100)."""
    if not need:
        score = float(policy.element_neutral)
    else:
        supplied = sum(1 for e in need if partner_counts.get(e, 0) > 0)
        score = policy.element_base + policy.element_span * supplied / len(need)
    if any(partner_counts.get(e, 0) >= policy.excess_threshold for e in excess):
        score -= policy.excess_penalty
    return clamp(score)


def elements_ko(items: Iterable[str]) -> str:
    return "·".join(ELEMENT_KO[e] for e in sorted(items, key=t.ELEMENT_ORDER.index)) or "없음"
