"""Structured report draft schema (report-v1) and validation result models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["computed", "interpretation"]
    rule_code: str
    evidence_ids: list[str]
    computed_values: dict[str, str | int | float] | None = None
    statement: str

    @field_validator("statement")
    @classmethod
    def _statement_not_blank(cls, value: str) -> str:
        return _non_blank(value)


class ReportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["report-v1"] = "report-v1"
    report_type: Literal["individual", "couple"]
    sections: dict[str, str]
    claims: list[Claim] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    generated_by: str
    prompt_version: str

    @field_validator("generated_by", "prompt_version")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _non_blank(value)


class ValidationError(BaseModel):
    """A report validation finding (not pydantic's own ValidationError)."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    path: str | None = None


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[ValidationError]
