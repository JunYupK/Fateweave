from datetime import time
from functools import lru_cache
from uuid import uuid4

import pytest

from fateweave.domain.calendar import normalize_birth
from fateweave.domain.glossary import hangul
from fateweave.domain.guide import LEGACY_REQUIRED, SECTIONS
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import build_individual_evidence
from fateweave.domain.validation import REQUIRED_SECTIONS, validate_report
from fateweave.models.facts import Evidence, PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.models.reports import Claim, ReportDraft


@lru_cache
def _prepared() -> PreparedAnalysis:
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


@pytest.fixture(scope="module")
def run() -> PreparedAnalysis:
    return _prepared()


def ev(run: PreparedAnalysis, rule: str, **match) -> Evidence:
    for e in run.evidence_catalog:
        if e.rule_code == rule and all(e.operands.get(k) == v for k, v in match.items()):
            return e
    raise AssertionError(rule)


def sections(report_type: str = "individual") -> dict[str, str]:
    return {name: f"{name} text" for name in REQUIRED_SECTIONS[report_type]}


def anchor() -> Claim:
    """A valid computed claim: every draft needs one (appended last, so indices are unchanged)."""
    e = ev(_prepared(), "SEWOON", year=2026)
    return computed("SEWOON", [e.id], {"year": 2026, "pillar": e.operands["pillar"]})


def draft(
    claims=(), caveats=(), secs=None, report_type="individual", with_anchor=True
) -> ReportDraft:
    return ReportDraft(
        report_type=report_type,
        sections=secs if secs is not None else sections(report_type),
        claims=[*claims, anchor()] if with_anchor else list(claims),
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
    cue = Evidence(
        id="E-self-GYEOKGUK-00000000",
        kind="interpretation_cue",
        rule_code="GYEOKGUK",
        operands={"status": "not_determined"},
        text_ko="격국 미판정",
        source_ref=None,
        assumptions=[],
    )
    with_cue = run.model_copy(update={"evidence_catalog": [*run.evidence_catalog, cue]})
    claims = [
        computed("DAEWOON", [e.id], {"year": 2027}),
        computed("GYEOKGUK", [cue.id], {"status": "not_determined"}),
    ]
    assert codes(validate_report(draft(claims), with_cue)) == [
        "FACT_MISMATCH",
        "UNSUPPORTED_CLAIM",
    ]


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
    "key",
    [
        "positions.²",
        "positions.①",
        "counts..x",
        "a..b",
        "counts.木.x",
        "positions.x",
        "",
        "positions." + "9" * 5000,
    ],
)
def test_malformed_paths_are_mismatch_not_crash(run, key):
    e = ev(run, "ELEMENTS")
    result = validate_report(draft([computed("ELEMENTS", [e.id], {key: "year"})]), run)
    assert codes(result) == ["FACT_MISMATCH"]


def test_path_through_scalar_is_mismatch(run):
    e = ev(run, "SEWOON", year=2027)
    result = validate_report(draft([computed("SEWOON", [e.id], {"year.x": 1})]), run)
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


def test_rejects_report_over_80000_chars(run):
    secs = sections()
    pad = 80_000 - sum(len(v) for k, v in secs.items() if k != "summary")
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


def test_rejects_draft_without_computed_claim(run):
    cue = ev(run, "YONGSIN")
    interp = Claim(
        kind="interpretation", rule_code="YONGSIN", evidence_ids=[cue.id], statement="reading"
    )
    for claims in ([], [interp]):
        result = validate_report(draft(claims, with_anchor=False), run)
        assert codes(result) == ["UNSUPPORTED_CLAIM"] and not result.valid
        assert result.errors[0].path == "claims"
        assert "at least one structured computed claim" in result.errors[0].message
    # a computed claim citing only unknown evidence does not count as citing server evidence
    ghost = computed("SEWOON", ["E-self-SEWOON-deadbeef"], {"year": 2027})
    result = validate_report(draft([ghost], with_anchor=False), run)
    assert codes(result) == ["UNKNOWN_EVIDENCE", "UNSUPPORTED_CLAIM"]
    assert result.errors[-1].path == "claims"
    assert validate_report(draft([interp]), run).valid  # with the anchor it passes


@pytest.mark.parametrize("phrase", ["결혼할 확률은 80%", "성사 확률 70%", "80%의 확률로"])
def test_rejects_probability_phrases_near_percentages(run, phrase):
    secs = sections() | {"summary": f"요약: {phrase} 이어진다"}
    result = validate_report(draft(secs=secs), run)
    assert codes(result) == ["UNSUPPORTED_CLAIM"]
    assert result.errors[0].path == "sections.summary"


def test_plain_percentage_is_not_a_probability(run):
    secs = sections() | {"summary": "오행 중 목(木)이 40% 정도로 강하다"}
    assert validate_report(draft(secs=secs), run).valid


# --- rules-v2: depth, hangul style, timing claims ---------------------------------------------


@pytest.fixture(scope="module")
def run_v2(run) -> PreparedAnalysis:
    return run.model_copy(update={"rule_version": "rules-v2"})


def full_sections(report_type: str = "individual") -> dict[str, str]:
    return {s.key: "가나다라 마바사. " * (s.min_chars // 9 + 1) for s in SECTIONS[report_type]}


def timing_claim(run: PreparedAnalysis) -> Claim:
    row = next(e for e in run.evidence_catalog if e.rule_code == "YEAR_TIMING")
    return computed(
        "YEAR_TIMING", [row.id], {"year": row.operands["year"], "rank": row.operands["rank"]}
    )


def test_v2_full_draft_passes(run_v2):
    d = draft([timing_claim(run_v2)], secs=full_sections())
    assert validate_report(d, run_v2).valid, validate_report(d, run_v2).errors


def test_v2_short_section_rejected(run_v2):
    secs = full_sections() | {"marriage_timing": "짧은 결혼 시기 설명"}
    result = validate_report(draft([timing_claim(run_v2)], secs=secs), run_v2)
    assert codes(result) == ["SECTION_TOO_SHORT"]
    assert result.errors[0].path == "sections.marriage_timing"


def test_v2_new_sections_required(run_v2):
    secs = {k: v for k, v in full_sections().items() if k != "caution_periods"}
    assert codes(validate_report(draft([timing_claim(run_v2)], secs=secs), run_v2)) == [
        "MISSING_SECTION"
    ]


def test_v2_hanja_heavy_section_rejected(run_v2):
    heavy = "乙未 日柱 偏財 正財 午未合 " * 40
    secs = full_sections() | {"personality": heavy}
    assert codes(validate_report(draft([timing_claim(run_v2)], secs=secs), run_v2)) == [
        "HANJA_HEAVY"
    ]
    # A few hanja in parentheses on first mention are fine.
    light = full_sections()["personality"] + " 을미(乙未) 일주"
    secs = full_sections() | {"personality": light}
    assert validate_report(draft([timing_claim(run_v2)], secs=secs), run_v2).valid


def test_v2_requires_a_timing_claim(run_v2):
    result = validate_report(draft(secs=full_sections()), run_v2)
    assert codes(result) == ["UNSUPPORTED_CLAIM"]
    assert "YEAR_TIMING" in result.errors[0].message


def test_computed_values_accept_hangul_reading(run):
    e = ev(run, "SEWOON", year=2026)
    pillar = e.operands["pillar"]
    hangul_pillar = hangul(pillar)
    assert hangul_pillar != pillar
    ok = computed("SEWOON", [e.id], {"year": 2026, "pillar": hangul_pillar})
    assert validate_report(draft([ok]), run).valid
    bad = computed("SEWOON", [e.id], {"year": 2026, "pillar": "갑자"})
    assert codes(validate_report(draft([bad]), run)) == ["FACT_MISMATCH"]


def test_legacy_rules_v1_keeps_old_sections(run):
    # Analyses prepared under rules-v1 keep their 8 sections and no minimum length.
    secs = {k: f"{k} text" for k in LEGACY_REQUIRED["individual"]}
    assert validate_report(draft(secs=secs), run).valid
