"""Deterministic validation of a ReportDraft against a PreparedAnalysis.

Only structured claims are machine-checked; free prose cannot be exhaustively fact-checked
(the probability-phrase guard is best-effort).
"""

import re
from typing import Any

from fateweave.domain.glossary import hanja_count, same_value
from fateweave.domain.guide import MAX_HANJA_RATIO, SECTIONS, TIMING_RULES, required_sections
from fateweave.models.facts import Evidence, PreparedAnalysis
from fateweave.models.reports import Claim, ReportDraft, ValidationError, ValidationResult

# Current (rules-v2) required sections per mode; rules-v1 analyses keep their own set.
REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    mode: tuple(sec.key for sec in sections) for mode, sections in SECTIONS.items()
}

MAX_SECTION_CHARS = 80_000

PROBABILITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"결혼 확률\s*\d+(?:\.\d+)?%"),
    re.compile(r"결혼 가능성\s*\d+(?:\.\d+)?%"),
    # 확률/가능성 within 15 chars (same line) before or after a percentage: "성사 확률 70%",
    # "결혼할 확률은 80%", "80%의 확률로". A bare percentage ("목(木)이 40%") is not matched.
    re.compile(
        r"(?:확률|가능성)[^\n]{0,15}?\d+(?:\.\d+)?\s*%"
        r"|\d+(?:\.\d+)?\s*%[^\n]{0,15}?(?:확률|가능성)"
    ),
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
            elif not same_value(actual, claimed):
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


def _check_depth(draft: ReportDraft) -> list[ValidationError]:
    """rules-v2: minimum section length and a hangul-first style (few hanja per section)."""
    errors: list[ValidationError] = []
    for sec in SECTIONS[draft.report_type]:
        text = draft.sections.get(sec.key, "").strip()
        if text and len(text) < sec.min_chars:
            errors.append(
                _err(
                    "SECTION_TOO_SHORT",
                    f"section {sec.key} has {len(text)} chars; write at least {sec.min_chars} "
                    f"(target about {sec.target_chars})",
                    f"sections.{sec.key}",
                )
            )
    for key, text in draft.sections.items():
        count = hanja_count(text)
        if len(text) >= 100 and count / len(text) > MAX_HANJA_RATIO:
            errors.append(
                _err(
                    "HANJA_HEAVY",
                    f"section {key} uses {count} hanja characters; write terms in hangul "
                    f"(e.g. 을미, 정재) and keep hanja under {MAX_HANJA_RATIO:.0%}",
                    f"sections.{key}",
                )
            )
    return errors


def _cites_server_evidence(claim: Claim, catalog: dict[str, Evidence]) -> bool:
    return claim.kind == "computed" and any(eid in catalog for eid in claim.evidence_ids)


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

    required = required_sections(draft.report_type, run.rule_version)
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

    if run.rule_version != "rules-v1":
        errors.extend(_check_depth(draft))

    catalog = {ev.id: ev for ev in run.evidence_catalog}
    for i, claim in enumerate(draft.claims):
        if claim.kind == "computed":
            errors.extend(_check_computed(i, claim, catalog))
        else:
            errors.extend(_check_interpretation(i, claim, catalog))

    if not any(_cites_server_evidence(c, catalog) for c in draft.claims):
        errors.append(
            _err(
                "UNSUPPORTED_CLAIM",
                "at least one structured computed claim citing server evidence "
                "(an evidence_catalog id) is required",
                "claims",
            )
        )

    timing_rule = TIMING_RULES[draft.report_type]
    has_timing = any(e.rule_code == timing_rule for e in run.evidence_catalog)
    if run.rule_version != "rules-v1" and has_timing and not any(
        catalog.get(eid) is not None and catalog[eid].rule_code == timing_rule
        for c in draft.claims
        for eid in c.evidence_ids
    ):
        errors.append(
            _err(
                "UNSUPPORTED_CLAIM",
                f"marriage_timing needs at least one claim citing {timing_rule} evidence",
                "claims",
            )
        )

    texts = [(f"sections.{k}", v) for k, v in draft.sections.items()]
    texts += [(f"claims.{i}.statement", c.statement) for i, c in enumerate(draft.claims)]
    texts += [(f"caveats.{i}", c) for i, c in enumerate(draft.caveats)]
    for path, text in texts:
        if any(p.search(text) for p in PROBABILITY_PATTERNS):
            errors.append(
                _err("UNSUPPORTED_CLAIM", "unsupported marriage probability expression", path)
            )

    return ValidationResult(valid=not errors, errors=errors)
