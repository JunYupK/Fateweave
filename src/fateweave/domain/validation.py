"""Deterministic validation of a ReportDraft against a PreparedAnalysis.

Only structured claims are machine-checked; free prose cannot be exhaustively fact-checked
(the probability-phrase guard is best-effort).
"""

import re
from typing import Any

from fateweave.models.facts import Evidence, PreparedAnalysis
from fateweave.models.reports import Claim, ReportDraft, ValidationError, ValidationResult

REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "individual": (
        "summary",
        "personality",
        "relationship_style",
        "spouse_profile",
        "married_life",
        "marriage_timing",
        "evidence_explanation",
        "limitations",
    ),
    "couple": (
        "summary",
        "marital_compatibility",
        "relationship_potential",
        "marriage_timing",
        "evidence_explanation",
        "limitations",
    ),
}

MAX_SECTION_CHARS = 40_000

PROBABILITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"결혼 확률\s*\d+(?:\.\d+)?%"),
    re.compile(r"결혼 가능성\s*\d+(?:\.\d+)?%"),
)

_MISSING = object()


def _err(code: str, message: str, path: str | None) -> ValidationError:
    return ValidationError(code=code, message=message, path=path)


def _resolve(operands: dict[str, Any], key: str) -> Any:
    """Top-level key first, else a dotted path through nested dicts and list indices."""
    if key in operands:
        return operands[key]
    node: Any = operands
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif (
            isinstance(node, list)
            and part.isascii()
            and part.isdigit()
            and len(part) <= 9
            and int(part) < len(node)
        ):
            node = node[int(part)]
        else:
            return _MISSING
    return node


def _check_computed(
    index: int, claim: Claim, catalog: dict[str, Evidence]
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    base = f"claims.{index}"
    cited: list[Evidence] = []
    if not claim.evidence_ids:
        errors.append(
            _err("UNSUPPORTED_CLAIM", "computed claim cites no evidence", f"{base}.evidence_ids")
        )
    for eid in claim.evidence_ids:
        ev = catalog.get(eid)
        if ev is None:
            errors.append(
                _err("UNKNOWN_EVIDENCE", f"unknown evidence id {eid}", f"{base}.evidence_ids")
            )
            continue
        cited.append(ev)
        if ev.kind == "interpretation_cue":
            errors.append(
                _err(
                    "UNSUPPORTED_CLAIM",
                    f"computed claim cites interpretation cue {eid}",
                    f"{base}.evidence_ids",
                )
            )
        if ev.rule_code != claim.rule_code:
            errors.append(
                _err(
                    "FACT_MISMATCH",
                    f"evidence {eid} rule_code is {ev.rule_code}; claim says {claim.rule_code}",
                    f"{base}.rule_code",
                )
            )
    if not claim.computed_values:
        errors.append(
            _err(
                "UNSUPPORTED_CLAIM",
                "computed claim has no computed_values",
                f"{base}.computed_values",
            )
        )
        return errors
    if not cited:
        return errors
    # All keys must be satisfied by ONE cited evidence; values may not be mixed across evidences.
    best_failures: list[ValidationError] | None = None
    for ev in cited:
        failures: list[ValidationError] = []
        for key, claimed in claim.computed_values.items():
            path = f"{base}.computed_values.{key}"
            actual = _resolve(ev.operands, key)
            if actual is _MISSING:
                failures.append(_err("FACT_MISMATCH", f"key {key} not found in {ev.id}", path))
            elif str(actual) != str(claimed):
                failures.append(
                    _err(
                        "FACT_MISMATCH",
                        f"key {key}: expected {actual}, claimed {claimed} ({ev.id})",
                        path,
                    )
                )
        if not failures:
            return errors
        if best_failures is None or len(failures) < len(best_failures):
            best_failures = failures
    errors.extend(best_failures or [])
    return errors


def _check_interpretation(
    index: int, claim: Claim, catalog: dict[str, Evidence]
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    base = f"claims.{index}"
    for eid in claim.evidence_ids:
        if eid not in catalog:
            errors.append(
                _err("UNKNOWN_EVIDENCE", f"unknown evidence id {eid}", f"{base}.evidence_ids")
            )
    if claim.computed_values:
        errors.append(
            _err(
                "UNSUPPORTED_CLAIM",
                "interpretation claim must not carry computed_values",
                f"{base}.computed_values",
            )
        )
    return errors


def validate_report(draft: ReportDraft, run: PreparedAnalysis) -> ValidationResult:
    """Collect all validation errors in a deterministic order (size check short-circuits)."""
    total = sum(len(v) for v in draft.sections.values())
    if total > MAX_SECTION_CHARS:
        too_large = _err(
            "REPORT_TOO_LARGE",
            f"sections total {total} chars; limit is {MAX_SECTION_CHARS}",
            "sections",
        )
        return ValidationResult(valid=False, errors=[too_large])

    errors: list[ValidationError] = []
    if draft.report_type != run.mode:
        errors.append(
            _err(
                "REPORT_TYPE_MISMATCH",
                f"report_type {draft.report_type} does not match analysis mode {run.mode}",
                "report_type",
            )
        )

    required = REQUIRED_SECTIONS[draft.report_type]
    for name in required:
        if not draft.sections.get(name, "").strip():
            errors.append(
                _err(
                    "MISSING_SECTION",
                    f"required section {name} is missing or blank",
                    f"sections.{name}",
                )
            )
    for name, text in draft.sections.items():
        if name not in required and not text.strip():
            errors.append(_err("MISSING_SECTION", f"section {name} is blank", f"sections.{name}"))

    catalog = {ev.id: ev for ev in run.evidence_catalog}
    for i, claim in enumerate(draft.claims):
        if claim.kind == "computed":
            errors.extend(_check_computed(i, claim, catalog))
        else:
            errors.extend(_check_interpretation(i, claim, catalog))

    texts = [(f"sections.{k}", v) for k, v in draft.sections.items()]
    texts += [(f"claims.{i}.statement", c.statement) for i, c in enumerate(draft.claims)]
    texts += [(f"caveats.{i}", c) for i, c in enumerate(draft.caveats)]
    for path, text in texts:
        if any(p.search(text) for p in PROBABILITY_PATTERNS):
            errors.append(
                _err("UNSUPPORTED_CLAIM", "unsupported marriage probability expression", path)
            )

    return ValidationResult(valid=not errors, errors=errors)
