"""Deterministic validation of a ReportDraft against a PreparedAnalysis.

Only structured claims are machine-checked; free prose cannot be exhaustively fact-checked
(the probability-phrase guard is best-effort).
"""

import re
from typing import Any

from fateweave.domain.assessments import COMPONENT_KO
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

# rules-v5 (spec §8): quoted scores must be the server's, and years presented as the couple's
# common favorable years must be overlap candidates. Prose checks are best-effort.
SCORE_RULES = ("COMPAT_SCORE", "COMPAT_COMPONENT")
CANDIDATE_RULES = ("COUPLE_TIMING_OVERLAP", "COUPLE_LIFE_TIMING")
_NUMBER = (
    r"(?:[은는이가:]\s*)?(?:총\s*)?(?:100\s*점\s*만점에?\s*)?(\d{1,3})\s*(?:점(?!\s*만점)|/\s*100)"
)
TOTAL_SCORE_PATTERN = re.compile(r"궁합\s*(?:지수|점수)\s*" + _NUMBER)
COMPONENT_SCORE_PATTERNS = {
    key: re.compile(re.escape(label) + r"\s*(?:영역\s*)?(?:점수|지수)?\s*" + _NUMBER)
    for key, label in COMPONENT_KO.items()
}
FAVORABLE_YEAR_PATTERN = re.compile(
    r"공통\s*(?:유리|후보)|두\s*사람\s*모두(?:에게)?\s*유리|최적의?\s*(?:해|시기|연도|결혼)"
    r"|결혼\s*적기|가장\s*(?:좋은|유리한)\s*(?:해|시기|연도)"
)
_NEGATION = re.compile(r"아니|아님|않|없|제외|빠지|빠진|빠져|빠졌|못")
_YEAR_RANGE = re.compile(r"(?:19|20)\d{2}\s*(?:년\s*)?[~\-–]\s*(?:(?:19|20)\d{2}|\d{2})")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)(?!\s*년?\s*생)")  # not "1990년생"
_SENTENCE = re.compile(r"(?<=[.!?。])\s+|\n")

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
                score = ev.rule_code in SCORE_RULES and key == "score"
                failures.append(
                    _err(
                        "SCORE_MISMATCH" if score else "FACT_MISMATCH",
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


def _check_scores(
    draft: ReportDraft, catalog: dict[str, Evidence], texts: list[tuple[str, str]]
) -> list[ValidationError]:
    """The couple index must be cited, and every quoted score must be the server's."""
    total = next((e for e in catalog.values() if e.rule_code == "COMPAT_SCORE"), None)
    if total is None:
        return []
    errors: list[ValidationError] = []
    if not any(
        c.kind == "computed"
        and "score" in (c.computed_values or {})
        and any(eid == total.id for eid in c.evidence_ids)
        for c in draft.claims
    ):
        errors.append(
            _err(
                "UNSUPPORTED_CLAIM",
                f"the couple report needs a computed claim citing {total.id} (COMPAT_SCORE) with "
                "computed_values.score",
                "claims",
            )
        )
    allowed = {total.operands["score"], *(total.operands.get("score_range") or [])}
    components = {
        e.operands["component"]: e.operands["score"]
        for e in catalog.values()
        if e.rule_code == "COMPAT_COMPONENT"
    }
    for path, text in texts:
        for m in TOTAL_SCORE_PATTERN.finditer(text):
            if int(m.group(1)) not in allowed:
                errors.append(
                    _err(
                        "SCORE_MISMATCH",
                        f"quoted compatibility index {m.group(1)} is not the server value "
                        f"{total.operands['score']}",
                        path,
                    )
                )
        for key, pattern in COMPONENT_SCORE_PATTERNS.items():
            if key not in components:
                continue
            for m in pattern.finditer(text):
                if int(m.group(1)) != components[key]:
                    errors.append(
                        _err(
                            "SCORE_MISMATCH",
                            f"quoted {key} score {m.group(1)} is not the server value "
                            f"{components[key]}",
                            path,
                        )
                    )
    return errors


def _check_candidate_years(
    catalog: dict[str, Evidence], texts: list[tuple[str, str]]
) -> list[ValidationError]:
    """Years presented as common favorable (or best) years must be overlap candidates."""
    sources = [e for e in catalog.values() if e.rule_code in CANDIDATE_RULES]
    if not sources:
        return []
    candidates = {c["year"] for e in sources for c in e.operands.get("candidates", [])}
    shown = ", ".join(str(y) for y in sorted(candidates)) or "none"
    errors: list[ValidationError] = []
    for path, text in texts:
        for sentence in _SENTENCE.split(text):
            if not FAVORABLE_YEAR_PATTERN.search(sentence) or _NEGATION.search(sentence):
                continue
            for year in _YEAR.findall(_YEAR_RANGE.sub(" ", sentence)):
                if int(year) not in candidates:
                    errors.append(
                        _err(
                            "TIMING_NOT_CANDIDATE",
                            f"{year} is presented as a common favorable year but is not a "
                            f"COUPLE_TIMING_OVERLAP/COUPLE_LIFE_TIMING candidate ({shown})",
                            path,
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
    if (
        run.rule_version != "rules-v1"
        and has_timing
        and not any(
            catalog.get(eid) is not None and catalog[eid].rule_code == timing_rule
            for c in draft.claims
            for eid in c.evidence_ids
        )
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
    if draft.report_type == "couple" and run.mode == "couple":
        errors.extend(_check_scores(draft, catalog, texts))
        errors.extend(_check_candidate_years(catalog, texts))
    for path, text in texts:
        if any(p.search(text) for p in PROBABILITY_PATTERNS):
            errors.append(
                _err("UNSUPPORTED_CLAIM", "unsupported marriage probability expression", path)
            )

    return ValidationResult(valid=not errors, errors=errors)
