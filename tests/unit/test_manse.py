import json
import subprocess
import sys
from datetime import date, time
from pathlib import Path

import pytest

from fateweave.domain.calendar import BirthInputError, normalize_birth
from fateweave.domain.manse import compute_chart
from fateweave.models.inputs import BirthProfileInput

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "verified_manse_cases.json").read_text("utf-8")
)
CASES = {c["id"]: c for c in FIXTURE["cases"]}

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
JIAZI_ANCHOR = date(1949, 10, 1)  # Wikipedia "Sexagenary cycle": 甲子 day


def independent_day_pillar(d: date) -> str:
    """Oracle independent of korean-saju: day count from a cited 甲子 anchor."""
    i = (d.toordinal() - JIAZI_ANCHOR.toordinal()) % 60
    return STEMS[i % 10] + BRANCHES[i % 12]


def independent_hour_pillar(d: date, kst: time, longitude: float) -> str:
    """Oracle independent of korean-saju for non-子 hours.

    Local mean time = KST + (longitude - 135) * 4 min (manse-v1, no equation of time);
    two-hour branches start at 子 23:00; 五鼠遁 gives the 子 stem from the day stem.
    """
    minutes = kst.hour * 60 + kst.minute + (longitude - 135.0) * 4.0
    assert 60 <= minutes < 23 * 60, "oracle covers 丑..亥 hours on the same day only"
    branch = int((minutes + 60) // 120) % 12
    day_stem = STEMS.index(independent_day_pillar(d)[0])
    return STEMS[((day_stem % 5) * 2 + branch) % 10] + BRANCHES[branch]


def birth(**kw):
    base = {"birth_date": "1990-01-01", "calendar": "solar", "gender_for_daewoon": "male"}
    base.update(kw)
    return normalize_birth(BirthProfileInput(**base))


def from_case(case_id: str, **overrides):
    inp = dict(CASES[case_id]["input"])
    if inp.get("birth_time"):
        inp["birth_time"] = time.fromisoformat(inp["birth_time"])
    inp.update(overrides)
    return birth(**inp)


def pillars(snap):
    return (snap.year_pillar, snap.month_pillar, snap.day_pillar, snap.hour_pillar)


def test_jiazi_anchor_is_self_consistent():
    # Wikipedia lists 1912-02-18 as 甲子 too; the anchors must agree.
    assert independent_day_pillar(date(1912, 2, 18)) == "甲子"


def test_known_1990_case():
    case = CASES["known_1990"]
    snap = compute_chart(from_case("known_1990"))
    exp = case["expected"]
    assert pillars(snap) == (
        exp["year_pillar"],
        exp["month_pillar"],
        exp["day_pillar"],
        exp["hour_pillar"],
    )
    assert snap.day_pillar == independent_day_pillar(date(1990, 1, 1))
    assert snap.certainty == exp["certainty"]
    assert snap.alternatives == []
    assert snap.policy_version == "manse-v2"
    assert snap.library_version == "0.3.0"
    assert snap.longitude == 126.9784
    assert "LONGITUDE_ASSUMED_SEOUL" in snap.warning_codes
    assert "SOLAR_TERMS_COMPUTED" in snap.warning_codes  # 1990 is outside KASI 2000-2027
    assert snap.solar_term_source == "computed"
    # Ten gods against a 丙 day stem, worked by hand: 己 傷官, 丙 比肩, 壬 偏官.
    assert snap.ten_gods["year_stem"] == "傷官"
    assert snap.ten_gods["month_stem"] == "比肩"
    assert snap.ten_gods["hour_stem"] == "偏官"
    assert snap.daewoon.forward is False  # 己 year (yin) + male
    assert snap.daewoon.entries[0].pillar == "乙亥"  # 丙子 stepped backwards


@pytest.mark.parametrize("case_id", ["known_1990", "known_1990_0935"])
def test_hour_pillar_matches_fixture_and_independent_oracle(case_id):
    case = CASES[case_id]
    snap = compute_chart(from_case(case_id))
    exp = case["expected"]
    assert pillars(snap) == (
        exp["year_pillar"],
        exp["month_pillar"],
        exp["day_pillar"],
        exp["hour_pillar"],
    )
    kst = time.fromisoformat(case["input"]["birth_time"])
    assert snap.hour_pillar == independent_hour_pillar(date(1990, 1, 1), kst, 126.9784)
    assert snap.certainty == exp["certainty"]
    if "alternative_hour_pillar" in exp:  # manse-v2: within 15 min of the hour boundary
        assert [a.hour_pillar for a in snap.alternatives] == [exp["alternative_hour_pillar"]]
        assert "HOUR_BOUNDARY_NEAR" in snap.warning_codes


@pytest.mark.parametrize(
    ("kst", "expected"),
    [
        (time(9, 0), "壬辰"),
        (time(9, 32), "壬辰"),  # 08:59:55 local mean time
        (time(9, 33), "癸巳"),  # 09:00:55 local mean time
        (time(9, 35), "癸巳"),
    ],
)
def test_seoul_chen_si_boundary(kst, expected):
    snap = compute_chart(birth(birth_time=kst, longitude=126.9784))
    assert snap.hour_pillar == expected
    assert independent_hour_pillar(date(1990, 1, 1), kst, 126.9784) == expected


def test_manse_time_policy_is_explicit():
    from korean_saju import SolarTimeCorrection

    from fateweave.domain import manse

    policy = FIXTURE["policy"]
    assert manse.KST_STANDARD_MERIDIAN == 135.0 == policy["kst_standard_meridian"]
    assert SolarTimeCorrection.KOREAN_STANDARD_MERIDIAN == manse.KST_STANDARD_MERIDIAN
    assert manse.APPLY_EQUATION_OF_TIME is False
    assert policy["equation_of_time"] == "not applied"
    assert manse.YAJA_SI_SEPARATED is True and policy["yaja_si_separated"] is True
    assert manse.DEFAULT_LONGITUDE == policy["default_longitude"] == 126.9784


def test_known_1990_no_correction_value_is_documented():
    # Without the longitude correction (meridian 135E) the hour is the plan's 癸巳.
    snap = compute_chart(from_case("known_1990", longitude=135.0))
    assert snap.hour_pillar == "癸巳"
    assert "癸巳" in CASES["known_1990"]["notes"]


def test_yaja_toggle_boundary():
    case = CASES["yaja_1994"]
    snap = compute_chart(from_case("yaja_1994"))
    exp = case["expected"]
    assert pillars(snap) == (
        exp["year_pillar"],
        exp["month_pillar"],
        exp["day_pillar"],
        exp["hour_pillar"],
    )
    assert snap.day_pillar == independent_day_pillar(date(1994, 4, 28)) == "甲申"
    # manse-v2: 23:08 local mean time is 8 min into 子時, so 乙亥 is a boundary alternative.
    assert snap.certainty == exp["certainty"] == "PARTIAL"
    assert [a.hour_pillar for a in snap.alternatives] == [exp["alternative_hour_pillar"]]
    assert snap.yaja_si_separated is True

    contrast = compute_chart(from_case("yaja_1994"), yaja_si_separated=False)
    assert contrast.day_pillar == case["contrast"]["day_pillar"] == "乙酉"
    assert contrast.day_pillar == independent_day_pillar(date(1994, 4, 29))
    assert contrast.hour_pillar == case["contrast"]["hour_pillar"]
    assert "NON_DEFAULT_YAJA_POLICY" in contrast.warning_codes
    assert contrast.facts_hash != snap.facts_hash


def test_yaja_with_unknown_longitude_is_partial():
    # 23:40 KST: 子時 at Seoul, but 亥時 at Korea's western extreme -> not definitive.
    snap = compute_chart(from_case("yaja_1994", longitude=None))
    assert snap.day_pillar == "甲申"
    assert snap.hour_pillar == "丙子"
    assert snap.certainty == "PARTIAL"
    assert "BOUNDARY_REVIEW_REQUIRED" in snap.warning_codes
    alt = {a.hour_pillar: a for a in snap.alternatives}
    assert "LONGITUDE_UNKNOWN" in alt["乙亥"].reasons


def test_unknown_hour_no_hour_pillar():
    b = birth(birth_date="1990-01-01")
    snap = compute_chart(b)
    assert snap.hour_pillar is None
    assert snap.birth_time is None
    assert b.birth_time is None
    dumped = snap.model_dump(mode="json")
    assert dumped["hour_pillar"] is None and dumped["birth_time"] is None
    assert not any(k.startswith("hour") for k in snap.ten_gods)
    assert (snap.year_pillar, snap.month_pillar, snap.day_pillar) == ("己巳", "丙子", "丙寅")
    assert any("noon" in a for a in snap.assumptions)
    assert "DAEWOON_START_APPROXIMATE" in snap.warning_codes
    # Under true-solar-time + separated yaja-si, 00:00-00:32 KST is still the previous
    # solar day, so the day pillar is not definitive for an unknown time.
    assert snap.certainty == "PARTIAL"
    assert "BOUNDARY_REVIEW_REQUIRED" in snap.warning_codes
    prev = [
        a for a in snap.alternatives if a.day_pillar == independent_day_pillar(date(1989, 12, 31))
    ]
    assert len(prev) == 1
    assert "DAY_BOUNDARY" in prev[0].reasons
    assert prev[0].hour_pillar is None
    assert "00:00-00:32" in prev[0].local_windows


def test_unknown_hour_on_solar_term_boundary_partial():
    # KASI 2024 立春 = 2024-02-04 17:27 KST: the year and month change within the date.
    snap = compute_chart(birth(birth_date="2024-02-04", longitude=126.9784))
    assert snap.hour_pillar is None
    assert snap.solar_term_source == "kasi"
    assert (snap.year_pillar, snap.month_pillar) == ("癸卯", "乙丑")  # noon reference
    assert snap.day_pillar == independent_day_pillar(date(2024, 2, 4))
    assert snap.certainty == "PARTIAL"
    assert "BOUNDARY_REVIEW_REQUIRED" in snap.warning_codes
    term_alts = [a for a in snap.alternatives if a.year_pillar == "甲辰"]
    assert len(term_alts) == 1
    assert term_alts[0].month_pillar == "丙寅"
    assert "SOLAR_TERM" in term_alts[0].reasons
    assert term_alts[0].local_windows == ["17:27-23:59"]


def test_nonbundled_solar_term_warns():
    # 1990 立春 ~11:14 KST, computed (not KASI); a birth 1h14m before it is not definitive.
    snap = compute_chart(birth(birth_date="1990-02-04", birth_time=time(10, 0), longitude=126.9784))
    assert (snap.year_pillar, snap.month_pillar) == ("己巳", "丁丑")
    assert snap.certainty == "PARTIAL"
    assert "BOUNDARY_REVIEW_REQUIRED" in snap.warning_codes
    alt = [a for a in snap.alternatives if a.year_pillar == "庚午"]
    assert len(alt) == 1
    assert alt[0].month_pillar == "戊寅"
    assert alt[0].day_pillar == snap.day_pillar
    assert alt[0].hour_pillar == snap.hour_pillar
    assert "SOLAR_TERM_COMPUTED" in alt[0].reasons

    # Same distance from a KASI-bundled 立春 (2024-02-04 17:27) is definitive.
    kasi = compute_chart(birth(birth_date="2024-02-04", birth_time=time(10, 0), longitude=126.9784))
    assert kasi.certainty == "CONFIRMED"
    assert kasi.alternatives == []


def test_historical_civil_time_offset_flagged():
    # 1987 had Korean DST: a 09:50 wall clock may be 08:50 UTC+9 (巳 vs 辰 at Seoul).
    snap = compute_chart(birth(birth_date="1987-07-01", birth_time=time(9, 50), longitude=126.9784))
    assert "CIVIL_TIME_OFFSET_UNVERIFIED" in snap.warning_codes
    assert snap.certainty == "PARTIAL"
    assert any("CIVIL_TIME_OFFSET" in a.reasons for a in snap.alternatives)


@pytest.mark.parametrize("year", [1905, 1910])
def test_pre_1912_civil_time_offset_flagged(year):
    # 1900-1911 Korean civil time was LMT (+8:27:52, to 1908-04-01) then UTC+8:30, so a
    # 11:10 wall clock may be ~11:40 UTC+9: AST 10:38 (巳) vs ~11:08 (午) at Seoul.
    snap = compute_chart(
        birth(birth_date=f"{year}-07-01", birth_time=time(11, 10), longitude=126.9784)
    )
    assert snap.hour_pillar[1] == "巳"
    assert "CIVIL_TIME_OFFSET_UNVERIFIED" in snap.warning_codes
    assert snap.certainty == "PARTIAL"
    alts = [a for a in snap.alternatives if "CIVIL_TIME_OFFSET" in a.reasons]
    assert [a.hour_pillar[1] for a in alts] == ["午"]


def test_1912_is_not_flagged():
    snap = compute_chart(
        birth(birth_date="1912-07-01", birth_time=time(11, 10), longitude=126.9784)
    )
    assert "CIVIL_TIME_OFFSET_UNVERIFIED" not in snap.warning_codes


def test_sewoon_range():
    b = birth(birth_time=time(9, 0))
    assert compute_chart(b).sewoon == []
    sewoon = compute_chart(b, sewoon_start_year=2026, sewoon_years=3).sewoon
    assert [(s.year, s.pillar) for s in sewoon] == [(2026, "丙午"), (2027, "丁未"), (2028, "戊申")]
    assert sewoon[0].age == 36


def test_pre_1900_rejected():
    with pytest.raises(BirthInputError) as exc:
        compute_chart(birth(birth_date="1899-06-01", birth_time=time(9, 0)))
    assert exc.value.code == "UNSUPPORTED_DATE"


HASH_SCRIPT = """
from datetime import time
from fateweave.domain.calendar import normalize_birth
from fateweave.domain.manse import compute_chart
from fateweave.models.inputs import BirthProfileInput
b = normalize_birth(BirthProfileInput(birth_date="1990-01-01", calendar="solar",
                                      birth_time=time(9, 0), gender_for_daewoon="male"))
print(compute_chart(b, sewoon_start_year=2026).facts_hash)
"""


def test_facts_hash_stable():
    b = birth(birth_time=time(9, 0))
    first = compute_chart(b, sewoon_start_year=2026)
    second = compute_chart(b, sewoon_start_year=2026)
    assert first.facts_hash == second.facts_hash
    assert len(first.facts_hash) == 64
    other = subprocess.run(
        [sys.executable, "-c", HASH_SCRIPT],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": "12345", **_minimal_env()},
    )
    assert other.stdout.strip() == first.facts_hash
    assert compute_chart(birth(birth_time=time(11, 0))).facts_hash != first.facts_hash
    assert compute_chart(b).facts_hash != first.facts_hash  # sewoon range is a fact
    tampered = first.model_copy(update={"hour_pillar": "癸巳"})
    assert tampered.facts_hash != first.facts_hash
    assert "facts_hash" in first.model_dump()


def _minimal_env():
    import os

    keep = ("PATH", "SYSTEMROOT", "PYTHONPATH", "VIRTUAL_ENV", "TEMP", "TMP")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    src = str(Path(__file__).parents[2] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


# --- manse-v2: a known birth time close to an hour boundary -------------------------------


def test_hour_boundary_near_is_partial_with_alternative():
    # 1998-06-17 11:27 KST at 126.83E: local mean time 10:54 -> 辛巳, 6 minutes before 午.
    snap = compute_chart(birth(birth_date="1998-06-17", birth_time=time(11, 27), longitude=126.83))
    assert pillars(snap) == ("戊寅", "戊午", "乙未", "辛巳")
    assert snap.certainty == "PARTIAL"
    assert "HOUR_BOUNDARY_NEAR" in snap.warning_codes
    assert "BOUNDARY_REVIEW_REQUIRED" in snap.warning_codes
    (alt,) = snap.alternatives
    assert alt.hour_pillar == "壬午" and alt.day_pillar == "乙未"
    assert {"HOUR_BOUNDARY", "HOUR_BOUNDARY_NEAR"} <= set(alt.reasons)
    # The wall-clock window of the scan that yields 壬午 starts at the boundary minute.
    assert alt.local_windows and alt.local_windows[0].startswith("11:33")
    near = next(w for w in snap.warnings if w.code == "HOUR_BOUNDARY_NEAR")
    assert "6 min" in near.detail


def test_mid_hour_birth_stays_confirmed():
    # 16:30 KST Seoul -> 15:58 local mean time, 58 minutes from either 申 boundary.
    snap = compute_chart(birth(birth_time=time(16, 30), longitude=126.9784))
    assert snap.certainty == "CONFIRMED"
    assert "HOUR_BOUNDARY_NEAR" not in snap.warning_codes


def test_hour_boundary_margin_is_fifteen_minutes():
    from fateweave.domain import manse

    assert manse.HOUR_BOUNDARY_MARGIN_MINUTES == 15
    # 辰/巳 at Seoul is 09:32:05 KST: 09:16 is 16 minutes before it, 09:18 is 14 minutes before.
    far = compute_chart(birth(birth_time=time(9, 16), longitude=126.9784))
    near = compute_chart(birth(birth_time=time(9, 18), longitude=126.9784))
    assert far.certainty == "CONFIRMED"
    assert near.certainty == "PARTIAL"
    assert [a.hour_pillar for a in near.alternatives] == ["癸巳"]


@pytest.mark.parametrize(
    ("birth_date", "kst", "expected"),
    [
        # Research report's illustrative cases (2026 KASI solar terms; Seoul).
        ("2026-08-01", time(10, 30), ("丙午", "乙未", "丁未", "乙巳")),  # before 立秋
        ("2026-10-11", time(14, 0), ("丙午", "戊戌", "戊午", "己未")),  # after 寒露
        ("2026-12-09", time(18, 30), ("丙午", "庚子", "丁巳", "己酉")),  # after 大雪
    ],
)
def test_reference_cases_from_research_report(birth_date, kst, expected):
    snap = compute_chart(birth(birth_date=birth_date, birth_time=kst, longitude=126.9784))
    assert pillars(snap) == expected
    assert snap.certainty == "CONFIRMED"
    assert snap.solar_term_source == "kasi"
