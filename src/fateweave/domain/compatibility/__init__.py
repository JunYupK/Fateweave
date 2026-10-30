"""Couple compatibility assessment: Fact -> Assessment -> Scoring (see compat-score policies)."""

from fateweave.domain.compatibility import policies, scoring
from fateweave.domain.compatibility.evaluator import assess
from fateweave.domain.compatibility.models import (
    CompatibilityAssessment,
    ComponentScore,
    Contribution,
)

__all__ = [
    "CompatibilityAssessment",
    "ComponentScore",
    "Contribution",
    "assess",
    "policies",
    "scoring",
]
