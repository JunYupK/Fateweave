"""Traditional myeongri tables shared by the rules-v2 evidence builders.

Everything here is a fixed lookup (no chart state). Where schools disagree, the table follows
the variant most Korean manse apps use and `*_VARIANT` names the alternative so evidence can say
so in its assumptions.
"""

from __future__ import annotations

from korean_saju import CheonGan, JiJi, ShipsinCalculator

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
ELEMENT_ORDER = "木火土金水"

STEM_ELEMENT = dict(zip(STEMS, "木木火火土土金金水水", strict=True))
BRANCH_ELEMENT = dict(zip(BRANCHES, "水土木木土火火土金金土水", strict=True))
SEASON = dict(zip("寅卯辰巳午未申酉戌亥子丑", "春春春夏夏夏秋秋秋冬冬冬", strict=True))

# (relation, Korean label, member branches)
PAIR_RELATIONS: tuple[tuple[str, str, str], ...] = (
    *(("合", "육합", m) for m in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")),
    *(("沖", "충", m) for m in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")),
    *(("刑", "형", m) for m in ("子卯", "辰辰", "午午", "酉酉", "亥亥")),  # 相刑 + 自刑
    *(("破", "파", m) for m in ("子酉", "卯午", "巳申", "寅亥", "丑辰", "未戌")),
    *(("害", "해", m) for m in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")),
    *(("怨嗔", "원진", m) for m in ("子未", "丑午", "寅酉", "卯申", "辰亥", "巳戌")),
    *(("鬼門", "귀문", m) for m in ("子酉", "丑午", "寅未", "卯申", "辰亥", "巳戌")),
)
TRIPLE_RELATIONS: tuple[tuple[str, str, str], ...] = (
    *(("三合", "삼합", m) for m in ("申子辰", "寅午戌", "巳酉丑", "亥卯未")),
    *(("三刑", "삼형", m) for m in ("寅巳申", "丑戌未")),
)
STEM_RELATIONS: tuple[tuple[str, str, str], ...] = (
    *(("合", "천간합", m) for m in ("甲己", "乙庚", "丙辛", "丁壬", "戊癸")),
    *(("沖", "천간충", m) for m in ("甲庚", "乙辛", "丙壬", "丁癸")),
)
STEM_CHUNG_ASSUMPTION = "school-dependent: 天干沖 limited to 甲庚·乙辛·丙壬·丁癸 (戊己 沖 not used)"

SAMHAP_GROUPS = ("申子辰", "寅午戌", "巳酉丑", "亥卯未")
# 12신살 시작점: group → (도화, 역마, 화개)
_SAMHAP_SINSAL = {
    "申子辰": ("酉", "寅", "辰"),
    "寅午戌": ("卯", "申", "戌"),
    "巳酉丑": ("午", "亥", "丑"),
    "亥卯未": ("子", "巳", "未"),
}
# 방합 group → (고신, 과숙)
_BANGHAP_GOGWA = {
    "亥子丑": ("寅", "戌"),
    "寅卯辰": ("巳", "丑"),
    "巳午未": ("申", "辰"),
    "申酉戌": ("亥", "未"),
}

HONGYEOM = dict(zip(STEMS, "午午寅未辰辰戌酉子申", strict=True))
HONGYEOM_VARIANT = (
    "school-dependent: 紅艶 table 甲乙午 丙寅 丁未 戊己辰 庚戌 辛酉 壬子 癸申 "
    "(乙申 variant not used)"
)
CHEONEUL = {
    "甲": "丑未",
    "戊": "丑未",
    "庚": "丑未",
    "乙": "子申",
    "己": "子申",
    "丙": "亥酉",
    "丁": "亥酉",
    "辛": "寅午",
    "壬": "巳卯",
    "癸": "巳卯",
}
YANGIN = {"甲": "卯", "丙": "午", "戊": "午", "庚": "酉", "壬": "子"}
BAEKHO_PILLARS = frozenset({"甲辰", "乙未", "丙戌", "丁丑", "戊辰", "壬戌", "癸丑"})
GOEGANG_PILLARS = frozenset({"庚辰", "庚戌", "壬辰", "壬戌", "戊戌"})
GOEGANG_VARIANT = "school-dependent: 魁罡 day pillars 庚辰·庚戌·壬辰·壬戌·戊戌 (戊辰 not used)"
GORAN_PILLARS = frozenset({"甲寅", "乙巳", "丁巳", "戊申", "辛亥"})
EUMYANG_CHACHAK_PILLARS = frozenset(
    {"丙子", "丙午", "丁丑", "丁未", "戊寅", "戊申", "辛卯", "辛酉", "壬辰", "壬戌", "癸巳", "癸亥"}
)

SPOUSE_STARS = {"male": ("正財", "偏財"), "female": ("正官", "偏官")}
SPOUSE_STAR_ASSUMPTION = (
    "school-dependent: spouse star by gender_for_daewoon — male 正財/偏財, female 正官/偏官"
)
TEN_GOD_GROUP = {
    "比肩": "比劫",
    "劫財": "比劫",
    "食神": "食傷",
    "傷官": "食傷",
    "偏財": "財星",
    "正財": "財星",
    "偏官": "官星",
    "正官": "官星",
    "偏印": "印星",
    "正印": "印星",
}
GROUP_KO = {"比劫": "비겁", "食傷": "식상", "財星": "재성", "官星": "관성", "印星": "인성"}

TWELVE_STAGES = ("長生", "沐浴", "冠帶", "臨官", "帝旺", "衰", "病", "死", "墓", "絕", "胎", "養")
TWELVE_STAGES_KO = dict(
    zip(
        TWELVE_STAGES,
        ("장생", "목욕", "관대", "건록", "제왕", "쇠", "병", "사", "묘", "절", "태", "양"),
        strict=True,
    )
)
_JANGSAENG = dict(zip(STEMS, "亥午寅酉寅酉巳子申卯", strict=True))  # 火土同法
TWELVE_STAGES_ASSUMPTION = (
    "school-dependent: 火土同法 (戊 follows 丙, 己 follows 丁); yin stems run backward"
)

ROLE_KO = {"餘氣": "여기", "中氣": "중기", "本氣": "본기"}


def _stem(hanja: str) -> CheonGan:
    stem = CheonGan.from_hanja(hanja)
    if stem is None:
        raise ValueError(f"invalid stem: {hanja!r}")
    return stem


def _branch(hanja: str) -> JiJi:
    branch = JiJi.from_hanja(hanja)
    if branch is None:
        raise ValueError(f"invalid branch: {hanja!r}")
    return branch


def ten_god(day_stem: str, target_stem: str) -> str:
    return ShipsinCalculator.for_cheon_gan(_stem(day_stem), _stem(target_stem)).hanja


def bongi(branch: str) -> str:
    return _branch(branch).bongi.hanja


def branch_ten_god(day_stem: str, branch: str) -> str:
    """Ten god of the branch by its 本氣 (the convention of the snapshot's ten_gods)."""
    return ten_god(day_stem, bongi(branch))


def hidden_stems(branch: str) -> list[tuple[str, str]]:
    """(stem, role) pairs in 餘氣 → 中氣 → 本氣 order."""
    return [(c.stem.hanja, c.role.hanja) for c in _branch(branch).ji_jang_gan]


def twelve_stage(day_stem: str, branch: str) -> str:
    start = BRANCHES.index(_JANGSAENG[day_stem])
    step = 1 if STEMS.index(day_stem) % 2 == 0 else -1
    return TWELVE_STAGES[((BRANCHES.index(branch) - start) * step) % 12]


def samhap_group(branch: str) -> str:
    return next(g for g in SAMHAP_GROUPS if branch in g)


def dohwa(branch: str) -> str:
    return _SAMHAP_SINSAL[samhap_group(branch)][0]


def yeokma(branch: str) -> str:
    return _SAMHAP_SINSAL[samhap_group(branch)][1]


def hwagae(branch: str) -> str:
    return _SAMHAP_SINSAL[samhap_group(branch)][2]


def gosin_gwasuk(year_branch: str) -> tuple[str, str]:
    return next(v for g, v in _BANGHAP_GOGWA.items() if year_branch in g)


def gongmang(day_pillar: str) -> tuple[str, str]:
    """旬空: the two branches left over in the day pillar's ten-day cycle."""
    index = next(i for i in range(60) if STEMS[i % 10] + BRANCHES[i % 12] == day_pillar)
    start = (index // 10) * 10
    return BRANCHES[(start + 10) % 12], BRANCHES[(start + 11) % 12]


def pair_relations(x: str, y: str) -> list[tuple[str, str, str]]:
    """Branch pair relations between two branches (any order)."""
    return [(rel, label, m) for rel, label, m in PAIR_RELATIONS if sorted(x + y) == sorted(m)]


def stem_relations(x: str, y: str) -> list[tuple[str, str, str]]:
    return [(rel, label, m) for rel, label, m in STEM_RELATIONS if sorted(x + y) == sorted(m)]


def generates(a: str, b: str) -> bool:
    """Element a generates element b (木→火→土→金→水→木)."""
    return (ELEMENT_ORDER.index(a) + 1) % 5 == ELEMENT_ORDER.index(b)


def controls(a: str, b: str) -> bool:
    """Element a controls element b (木→土→水→火→金→木)."""
    return (ELEMENT_ORDER.index(a) + 2) % 5 == ELEMENT_ORDER.index(b)


def group_element(day_stem: str, group: str) -> str:
    """The element a ten-god group stands for relative to the day stem."""
    me = STEM_ELEMENT[day_stem]
    i = ELEMENT_ORDER.index(me)
    offset = {"比劫": 0, "食傷": 1, "財星": 2, "官星": 3, "印星": 4}[group]
    return ELEMENT_ORDER[(i + offset) % 5]
