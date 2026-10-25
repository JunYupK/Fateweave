from datetime import time
from uuid import uuid4

import pytest

from fateweave.domain.calendar import normalize_birth
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import build_individual_evidence
from fateweave.domain.validation import REQUIRED_SECTIONS, validate_report
from fateweave.models.facts import Evidence, PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.models.reports import Claim, ReportDraft


@pytest.fixture(scope="module")
def run() -> PreparedAnalysis:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date="1990-01-01",
            calendar="solar",
            birth_time=time(16, 30),
            gender_for_daewoon="male",
        )
    )
    snap = compute_chart(birth, sewoon_start_year=2026, sewoon_years=3)
    return PreparedAnalysis(
        analysis_id=uuid4(),
        mode="individual",
        facts={"self": snap},
        evidence_catalog=build_individual_evidence(snap, "self"),
        missing_data=[],
        policy_version="manse-v1",
        rule_version="rules-v1",
        horizon_years=3,
        start_year=2026,
    )


def ev(run: PreparedAnalysis, rule: str, **match) -> Evidence:
    for e in run.evidence_catalog:
        if e.rule_code == rule and all(e.operands.get(k) == v for k, v in match.items()):
            return e
    raise AssertionError(rule)


def sections(report_type: str = "individual") -> dict[str, str]:
    return {name: f"{name} text" for name in REQUIRED_SECTIONS[report_type]}


def draft(claims=(), caveats=(), secs=None, report_type="individual") -> ReportDraft:
    return ReportDraft(
        report_type=report_type,
        sections=secs if secs is not None else sections(report_type),
        claims=list(claims),
        caveats=list(caveats),
        generated_by="claude",
        prompt_version="p1",
    )


def computed(rule, ids, values, statement="x") -> Claim:
    return Claim(
        kind="computed",
        rule_code=rule,
        evidence_ids=ids,
        computed_values=values,
        statement=statement,
    )


def codes(result) -> list[str]:
    return [e.code for e in result.errors]


def test_valid_draft_passes(run):
    e = ev(run, "SEWOON", year=2027)
    claim = computed("SEWOON", [e.id], {"year": 2027, "pillar": e.operands["pillar"]})
    result = validate_report(draft([claim]), run)
    assert result.valid and result.errors == []


def test_rejects_unknown_evidence_id(run):
    claim = computed("SEWOON", ["E-self-SEWOON-deadbeef"], {"year": 2027})
    result = validate_report(draft([claim]), run)
    assert "UNKNOWN_EVIDENCE" in codes(result) and not result.valid


def test_rejects_wrong_year_or_stem(run):
    e = ev(run, "SEWOON", year=2027)
    claims = [
        computed("SEWOON", [e.id], {"year": 2030}),
        computed("SEWOON", [e.id], {"pillar": "甲甲"}),
        computed("SEWOON", [e.id], {"nope": "x"}),
    ]
    result = validate_report(draft(claims), run)
    assert codes(result) == ["FACT_MISMATCH"] * 3
    assert [x.path for x in result.errors] == [
        "claims.0.computed_values.year",
        "claims.1.computed_values.pillar",
        "claims.2.computed_values.nope",
    ]


def test_rule_code_mismatch_and_cue_rejected(run):
    e = ev(run, "SEWOON", year=2027)
    cue = ev(run, "YONGSIN")
    claims = [
        computed("DAEWOON", [e.id], {"year": 2027}),
        computed("YONGSIN", [cue.id], {"status": "not_computed"}),
    ]
    assert codes(validate_report(draft(claims), run)) == ["FACT_MISMATCH", "UNSUPPORTED_CLAIM"]


def test_dotted_path_resolution(run):
    e = ev(run, "ELEMENTS")
    key = next(iter(e.operands["counts"]))
    ok = computed(
        "ELEMENTS",
        [e.id],
        {f"counts.{key}": e.operands["counts"][key], "positions.0": "year"},
    )
    assert validate_report(draft([ok]), run).valid
    bad = computed("ELEMENTS", [e.id], {"positions.9": "year"})
    assert codes(validate_report(draft([bad]), run)) == ["FACT_MISMATCH"]


@pytest.mark.parametrize(
    "key", ["positions.²", "positions.①", "counts..x", "a..b", "counts.木.x", "positions.x", ""]
)
def test_malformed_paths_are_mismatch_not_crash(run, key):
    e = ev(run, "ELEMENTS")
    result = validate_report(draft([computed("ELEMENTS", [e.id], {key: "year"})]), run)
    assert codes(result) == ["FACT_MISMATCH"]


def test_rejects_values_mixed_across_evidences(run):
    a = ev(run, "SEWOON", year=2027)
    b = ev(run, "SEWOON", year=2028)
    mixed = computed("SEWOON", [a.id, b.id], {"year": 2028, "pillar": a.operands["pillar"]})
    result = validate_report(draft([mixed]), run)
    assert codes(result) == ["FACT_MISMATCH"]
    assert result.errors[0].path == "claims.0.computed_values.year"  # tie: first evidence
    ok = computed("SEWOON", [a.id, b.id], {"year": 2028, "pillar": b.operands["pillar"]})
    assert validate_report(draft([ok]), run).valid


def test_rejects_missing_section(run):
    secs = sections()
    del secs["limitations"]
    secs["summary"] = "   "
    result = validate_report(draft(secs=secs), run)
    assert codes(result) == ["MISSING_SECTION", "MISSING_SECTION"]
    assert {e.path for e in result.errors} == {"sections.summary", "sections.limitations"}


def test_rejects_blank_extra_section(run):
    secs = sections() | {"extra": ""}
    assert codes(validate_report(draft(secs=secs), run)) == ["MISSING_SECTION"]


def test_rejects_wrong_report_type(run):
    result = validate_report(draft(report_type="couple"), run)
    assert "REPORT_TYPE_MISMATCH" in codes(result)


def test_accepts_alternative_school_as_interpretation(run):
    cue = ev(run, "YONGSIN")
    claim = Claim(
        kind="interpretation",
        rule_code="YONGSIN",
        evidence_ids=[cue.id],
        statement="school-dependent reading",
    )
    assert validate_report(draft([claim]), run).valid
    no_ev = claim.model_copy(update={"evidence_ids": []})
    assert validate_report(draft([no_ev]), run).valid


def test_interpretation_cannot_carry_values_or_unknown_ids(run):
    claim = Claim(
        kind="interpretation",
        rule_code="X",
        evidence_ids=["E-nope"],
        computed_values={"a": 1},
        statement="x",
    )
    assert codes(validate_report(draft([claim]), run)) == ["UNKNOWN_EVIDENCE", "UNSUPPORTED_CLAIM"]


def test_rejects_computed_claim_without_values(run):
    e = ev(run, "SEWOON", year=2027)
    for values in (None, {}):
        claim = computed("SEWOON", [e.id], values)
        assert codes(validate_report(draft([claim]), run)) == ["UNSUPPORTED_CLAIM"]
    no_ids = computed("SEWOON", [], {"year": 2027})
    assert "UNSUPPORTED_CLAIM" in codes(validate_report(draft([no_ids]), run))


@pytest.mark.parametrize("phrase", ["결혼 확률 82%", "결혼 가능성  7.5%"])
def test_rejects_unsupported_marriage_probability_phrase(run, phrase):
    secs = sections() | {"summary": f"요약: {phrase} 입니다"}
    result = validate_report(draft(secs=secs, caveats=[phrase]), run)
    assert codes(result) == ["UNSUPPORTED_CLAIM"] * 2
    claim = Claim(kind="interpretation", rule_code="X", evidence_ids=[], statement=phrase)
    assert codes(validate_report(draft([claim]), run)) == ["UNSUPPORTED_CLAIM"]


def test_rejects_report_over_40000_chars(run):
    secs = sections()
    pad = 40_000 - sum(len(v) for k, v in secs.items() if k != "summary")
    over = secs | {"summary": "가" * (pad + 1)}
    assert codes(validate_report(draft(secs=over), run)) == ["REPORT_TOO_LARGE"]
    ok = secs | {"summary": "가" * pad}
    assert "REPORT_TOO_LARGE" not in codes(validate_report(draft(secs=ok), run))


def test_schema_is_strict():
    with pytest.raises(ValueError):
        ReportDraft(report_type="individual", sections={}, generated_by=" ", prompt_version="p")
    with pytest.raises(ValueError):
        Claim(kind="computed", rule_code="X", evidence_ids=[], statement="x", extra=1)
    with pytest.raises(ValueError):
        ReportDraft(
            schema_version="report-v2",
            report_type="individual",
            sections={},
            generated_by="c",
            prompt_version="p",
        )
