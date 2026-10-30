"""Scoring policies. Each version is immutable; a changed table is a new version.

The numbers are Fateweave design hypotheses (docs/superpowers/specs/
2026-10-30-compatibility-engine-design.md §4), not a myeongri standard and not calibrated
against relationship outcomes.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


def _frozen(d: dict) -> Mapping:
    return MappingProxyType(dict(d))


@dataclass(frozen=True)
class CompatPolicy:
    version: str
    weights: Mapping[str, float]
    # D: one day-stem relation, by precedence 合 > 沖 > 生 > 比和 > 剋
    day_master_relation: Mapping[str, int]
    spouse_star_stem_bonus: int
    spouse_star_branch_bonus: int
    # P: day-branch relations; the largest positive and the largest negative apply
    palace_base: int
    palace_deltas: Mapping[str, int]
    # E: directional element complement
    element_neutral: int
    element_base: int
    element_span: int
    excess_threshold: int
    excess_penalty: int
    asymmetry_threshold: int
    asymmetry_penalty: int
    # W: cross-pillar relations other than day stem-stem and day branch-branch
    structure_base: int
    structure_deltas: Mapping[str, int]
    structure_cap: int
    relation_order: tuple[str, ...] = field(default=("合", "沖", "生", "比和", "剋"))

    def __post_init__(self) -> None:
        if round(sum(self.weights.values()), 10) != 1.0:
            raise ValueError(f"{self.version}: weights must sum to 1")


COMPAT_SCORE_V1 = CompatPolicy(
    version="compat-score-v1",
    weights=_frozen(
        {
            "day_master": 0.20,
            "spouse_palace": 0.35,
            "element_balance": 0.30,
            "overall_structure": 0.15,
        }
    ),
    day_master_relation=_frozen({"合": 90, "沖": 25, "生": 75, "比和": 60, "剋": 40}),
    spouse_star_stem_bonus=10,
    spouse_star_branch_bonus=5,
    palace_base=60,
    palace_deltas=_frozen(
        {
            "合": 25,
            "半合": 15,
            "沖": -35,
            "刑": -20,
            "怨嗔": -20,
            "害": -15,
            "鬼門": -10,
            "破": -10,
        }
    ),
    element_neutral=70,
    element_base=50,
    element_span=50,
    excess_threshold=3,
    excess_penalty=15,
    asymmetry_threshold=30,
    asymmetry_penalty=10,
    structure_base=60,
    structure_deltas=_frozen(
        {
            "合": 5,
            "半合": 5,
            "沖": -6,
            "刑": -4,
            "怨嗔": -4,
            "害": -2,
            "破": -2,
            "鬼門": -2,
        }
    ),
    structure_cap=30,
)

_POLICIES = {COMPAT_SCORE_V1.version: COMPAT_SCORE_V1}
DEFAULT_VERSION = COMPAT_SCORE_V1.version


def get(version: str) -> CompatPolicy:
    return _POLICIES[version]
