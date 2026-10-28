from datetime import time

import pytest

from fateweave.domain import depth, timing
from fateweave.domain import tables as t
from fateweave.domain.calendar import normalize_birth
from fateweave.domain.glossary import hangul, has_hanja, same_value
from fateweave.domain.manse import compute_chart
from fateweave.domain.rules import build_individual_evidence
from fateweave.models.facts import ChartSnapshot
from fateweave.models.inputs import BirthProfileInput


@pytest.fixture(scope="module")
def known() -> ChartSnapshot:
    # 己巳 丙子 丙寅 丙申, male.
    birth = normalize_birth(
        BirthProfileInput(
            birth_date="1990-01-01",
            calendar="solar",
            birth_time=time(16, 30),
            gender_for_daewoon="male",
        )
    )
    return compute_chart(birth, sewoon_start_year=2026, sewoon_years=10)


def test_hangul_readings():
    assert hangul("正財") == "정재"
    assert hangul("乙未 午未合") == "을미 오미합"
    assert hangul("子未怨嗔") == "자미원진"
    assert same_value("丙午", "병오") and same_value(2026, "2026")
    assert not same_value("丙午", "갑자")
    assert has_hanja("을미(乙未)") and not has_hanja("을미")


@pytest.mark.parametrize(
    ("stem", "branch", "stage"),
    [
        ("甲", "亥", "長生"),
        ("乙", "午", "長生"),
        ("乙", "巳", "沐浴"),
        ("丙", "午", "帝旺"),
        ("己", "卯", "病"),  # 火土同法: 己 follows 丁
        ("壬", "子", "帝旺"),
        ("癸", "寅", "沐浴"),
    ],
)
def test_twelve_stages(stem, branch, stage):
    assert t.twelve_stage(stem, branch) == stage


def test_sinsal_tables():
    assert t.gongmang("甲子") == ("戌", "亥")
    assert t.gongmang("甲戌") == ("申", "酉")
    assert t.gongmang("丙寅") == ("戌", "亥")
    assert (t.dohwa("寅"), t.dohwa("子"), t.dohwa("巳"), t.dohwa("亥")) == ("卯", "酉", "午", "子")
    assert (t.yeokma("寅"), t.hwagae("子")) == ("申", "辰")
    assert t.gosin_gwasuk("子") == ("寅", "戌")
    assert t.gosin_gwasuk("巳") == ("申", "辰")
    assert [n for n, _, m in t.PAIR_RELATIONS if m == "子未"] == ["害", "怨嗔"]
    assert [n for n, _, m in t.PAIR_RELATIONS if m == "子酉"] == ["破", "鬼門"]


def test_ten_god_groups():
    assert t.group_element("甲", "財星") == "土"
    assert t.group_element("甲", "官星") == "金"
    assert t.group_element("甲", "印星") == "水"
    assert t.group_element("甲", "食傷") == "火"
    assert t.ten_god("丙", "庚") == "偏財" and t.branch_ten_god("丙", "申") == "偏財"


def test_month_pillars_by_five_tigers():
    months = timing.month_pillars("丙午")  # 2026
    assert months[0] == ("庚寅", "02-04")
    assert [p for p, _ in months] == [
        "庚寅", "辛卯", "壬辰", "癸巳", "甲午", "乙未",
        "丙申", "丁酉", "戊戌", "己亥", "庚子", "辛丑",
    ]  # fmt: skip
    assert months[-1][1] == "01-06"  # 丑月 starts in January of the next year
    assert timing.month_pillars("甲子")[0][0] == "丙寅"
    assert timing.year_pillar(2026) == "丙午" and timing.year_pillar(1984) == "甲子"


def test_signals_spouse_star_and_palace(known):
    # 丙 male: 庚 (偏財) stem and 申 (本氣 庚, 偏財) are spouse stars; 寅申沖 hits the palace.
    sig = timing.signals(known, "庚申")
    assert {"SPOUSE_STAR_STEM", "SPOUSE_STAR_BRANCH"} <= set(sig["cues"])
    assert "PALACE_CHUNG" in sig["cautions"]
    # 辛 forms 丙辛合 with the day stem; 亥 forms 寅亥合 with the spouse palace.
    sig = timing.signals(known, "辛亥")
    assert {"DAY_STEM_HAP", "SPOUSE_PALACE_HAP", "SPOUSE_STAR_STEM"} <= set(sig["cues"])
    # 比劫 stem for a male chart is a rival for the 財星.
    assert "RIVAL_STAR" in timing.signals(known, "丙午")["cautions"]


def test_year_rows_rank_and_month_detail(known):
    rows = timing.year_rows(known, 2026, 10)
    assert [r["year"] for r in rows] == list(range(2026, 2036))
    assert sorted(r["rank"] for r in rows) == list(range(1, 11))
    best = min(rows, key=lambda r: r["rank"])
    assert best["core_count"] == max(r["core_count"] for r in rows)
    top = timing.top_years(rows)
    assert 1 <= len(top) <= 3 and all(r["core_count"] > 0 for r in top)

    evidence = build_individual_evidence(known, "self")
    months = [e for e in evidence if e.rule_code == "MONTH_TIMING"]
    assert sorted(e.operands["year"] for e in months) == sorted(r["year"] for r in top)
    for e in months:
        assert len(e.operands["months"]) == 12
    years = [e.operands["year"] for e in evidence if e.rule_code == "YEAR_TIMING"]
    assert years == sorted(years)  # natural order in the catalog
    flows = [e.operands["index"] for e in evidence if e.rule_code == "DAEWOON_FLOW"]
    assert flows == sorted(flows) and len(flows) == len(known.daewoon.entries)


def test_chart_depth(known):
    names = {s["sinsal"]: s for s in depth.sinsal(known)}
    assert names["紅艶"]["found"] == ["day_branch"]  # 丙 → 寅
    assert names["孤辰"]["found"] == ["hour_branch"]  # 巳 year → 申
    star = depth.spouse_star(known)
    assert star["element"] == "金"
    assert {"position": "hour_branch", "value": "庚", "ten_god": "偏財", "role": "本氣"} in star[
        "visible"
    ]
    assert depth.strength(known)["level"] == "中和"
    assert depth.eokbu(known)["elements"] == []
    assert depth.johu(known)["elements"] == ["火"]
