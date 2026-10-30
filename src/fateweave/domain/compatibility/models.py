"""Result models of the compatibility assessment (scores are interpretive indexes, not odds)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ComponentStatus = Literal["OK", "REDUCED_SCOPE", "UNAVAILABLE"]


class Contribution(BaseModel):
    """One rule applied to one fact. `applied` is False when a stronger same-sign relation won."""

    model_config = ConfigDict(frozen=True)

    rule: str  # policy rule id, e.g. "P.合"
    points: float
    basis: str  # the fact in plain Korean (no birth data)
    evidence_id: str | None = None  # the Fact evidence it scores, when one exists
    applied: bool = True


class ComponentScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    score: int | None
    status: ComponentStatus
    contributions: list[Contribution]
    details: dict[str, Any] = {}


class CompatibilityAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    scoring_version: str
    score_type: Literal["interpretive_index"] = "interpretive_index"
    status: Literal["OK", "PARTIAL"]
    score: int
    score_range: list[int] | None  # [min, max] over alternative pillar sets, when any exist
    scale: Literal[100] = 100
    weights: dict[str, float]
    components: dict[str, ComponentScore]
    excluded: list[str]
