"""timing-score-v1: weighted year signals, the both-favorable overlap, and life-span summaries."""

from datetime import time

import pytest

from fateweave.domain import timing
from fateweave.domain.calendar import normalize_birth
from fateweave.domain.manse import compute_chart
from fateweave.models.facts import ChartSnapshot
from fateweave.models.inputs import BirthProfileInput


def chart(birth_date: str, birth_time: time | None, gender: str) -> ChartSnapshot:
    birth = normalize_birth(
        BirthProfileInput(
            birth_date=birth_date,
            calendar="solar",
            birth_time=birth_time,
            gender_for_daewoon=gender,
            longitude=126.9784,
        )
    )
    return compute_chart(birth, sewoon_start_year=2026, sewoon_years=10)


@pytest.fixture(scope="module")
def jia() -> ChartSnapshot:
    return chart("1990-03-10", time(10, 0), "male")  # 甲戌 day, male


@pytest.fixture(scope="module")
def gui() -> ChartSnapshot:
    return chart("1990-03-19", time(10, 0), "female")  # 癸未 day, female


def row(year: int, core: int, signal: int, cautions=()) -> dict:
    return {
        "year": year,
        "pillar": timing.year_pillar(year),
        "cues": ["SPOUSE_STAR_STEM"] * core,
        "cautions": list(cautions),
        "core_count": core,
        "signal": signal,
    }


def test_signal_points():
    assert timing.TIMING_VERSION == "timing-score-v1"
    sig = {"cues": ["SPOUSE_STAR_STEM", "DAY_STEM_HAP", "DOHWA"], "cautions": ["PALACE_CHUNG"]}
    assert timing.signal_points(sig["cues"], sig["cautions"]) == 2 + 2 + 1 - 2
    assert timing.signal_points([], ["PALACE_WONJIN", "RIVAL_STAR"]) == -2
    for code in timing.CORE_CUES:
        assert timing.CUE_POINTS[code] == 2
    assert timing.CUE_POINTS["SEWOON_DAEWOON_HAP"] == 1
    assert timing.CAUTION_POINTS["SEWOON_DAEWOON_CHUNG"] == -1


def test_year_rows_rank_by_signal(jia):
    rows = timing.year_rows(jia, 2026, 10)
    for r in rows:
        assert r["signal"] == timing.signal_points(r["cues"], r["cautions"])
    order = sorted(rows, key=lambda r: r["rank"])
    keys = [(-r["signal"], -r["core_count"], r["year"]) for r in order]
    assert keys == sorted(keys)


def test_sewoon_daewoon_relation_cues(jia):
    # 2032 壬子: jia's running daewoon branch is 午 at 42 → 子午 沖 is a caution.
    rows = {r["year"]: r for r in timing.year_rows(jia, 2026, 10)}
    for r in rows.values():
        running = [p[1] for p in r["daewoon"] if p != timing.DAEWOON_UNAVAILABLE]
        chung = any(
            rel == "沖" for b in running for rel, _, _ in timing.t.pair_relations(r["pillar"][1], b)
        )
        assert ("SEWOON_DAEWOON_CHUNG" in r["cautions"]) == chung, r["year"]


def test_overlap_requires_both_and_sorts_by_min():
    a = [row(2026, 1, 6), row(2027, 1, 2), row(2028, 0, 7), row(2029, 2, 9), row(2030, 1, 10)]
    b = [
        row(2026, 1, 2),
        row(2027, 1, 3),
        row(2028, 1, 9),
        row(2029, 1, 5, ["PALACE_CHUNG"]),
        row(2030, 1, 1),
    ]
    result = timing.overlap(a, b)
    # 2028: A has no core cue; 2029: B's spouse palace is clashed -> not candidates.
    # 2030 has the highest mean (5.5) but the lowest minimum (1), so it comes last:
    # 2026 (min 2, sum 8) > 2027 (min 2, sum 5) > 2030 (min 1).
    assert [c["year"] for c in result["candidates"]] == [2026, 2027, 2030]
    assert result["no_candidate_reason"] is None
    by_year = {y["year"]: y for y in result["years"]}
    assert by_year[2028]["candidate"] is False and by_year[2029]["candidate"] is False
    assert [by_year[y]["candidate_rank"] for y in (2026, 2027, 2030)] == [1, 2, 3]
    assert by_year[2028]["candidate_rank"] is None


def test_overlap_without_candidates_says_so():
    a = [row(2026, 0, 3), row(2027, 2, 6)]
    b = [row(2026, 2, 6), row(2027, 0, 1)]
    result = timing.overlap(a, b)
    assert result["candidates"] == []
    assert result["no_candidate_reason"]
    assert all(y["candidate"] is False and y["candidate_rank"] is None for y in result["years"])


def test_life_summary_by_daewoon(jia):
    summary = timing.life_summary(jia)
    assert summary, "at least one daewoon overlaps ages 20-50"
    birth_year = int(jia.solar_date[:4])
    for block in summary:
        assert block["from_age"] >= 20 and block["to_age"] <= 50
        assert len(block["top_years"]) <= 3
        for y in block["top_years"]:
            assert block["from_age"] <= y["year"] - birth_year <= block["to_age"]
            assert y["signal"] > 0
        signals = [y["signal"] for y in block["top_years"]]
        assert signals == sorted(signals, reverse=True)


def test_couple_life_overlap_window(jia, gui):
    result = timing.life_overlap(jia, gui)
    # Both born 1990: ages 20-50 → 2010-2040.
    assert (result["from_year"], result["to_year"]) == (2010, 2040)
    assert len(result["candidates"]) <= 5
    for c in result["candidates"]:
        assert 2010 <= c["year"] <= 2040
