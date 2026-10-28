"""Hangul readings for the hanja used in evidence (rules-v2).

Evidence `operands` keep hanja (stable IDs and machine checks); `text_ko` is rendered in hangul
so reports stay readable. `hangul()` reads every known hanja character by its myeongri reading;
`same_value()` lets a claim quote an operand in either script.
"""

from __future__ import annotations

import re

_READINGS: dict[str, str] = {
    # 천간 / 지지
    **dict(zip("甲乙丙丁戊己庚辛壬癸", "갑을병정무기경신임계", strict=True)),
    **dict(zip("子丑寅卯辰巳午未申酉戌亥", "자축인묘진사오미신유술해", strict=True)),
    # 오행 / 계절
    **dict(zip("木火土金水", "목화토금수", strict=True)),
    **dict(zip("春夏秋冬", "춘하추동", strict=True)),
    # 십성
    "比": "비",
    "肩": "견",
    "劫": "겁",
    "財": "재",
    "食": "식",
    "神": "신",
    "傷": "상",
    "官": "관",
    "偏": "편",
    "正": "정",
    "印": "인",
    # 관계·신살·12운성·격국 등에 쓰이는 글자
    "合": "합",
    "沖": "충",
    "刑": "형",
    "破": "파",
    "害": "해",
    "三": "삼",
    "半": "반",
    "怨": "원",
    "嗔": "진",
    "鬼": "귀",
    "門": "문",
    "格": "격",
    "建": "건",
    "祿": "록",
    "羊": "양",
    "刃": "인",
    "長": "장",
    "生": "생",
    "沐": "목",
    "浴": "욕",
    "冠": "관",
    "帶": "대",
    "臨": "임",
    "帝": "제",
    "旺": "왕",
    "衰": "쇠",
    "病": "병",
    "死": "사",
    "墓": "묘",
    "絕": "절",
    "胎": "태",
    "養": "양",
    "化": "화",
    "氣": "기",
    "本": "본",
    "中": "중",
    "餘": "여",
    "身": "신",
    "強": "강",
    "弱": "약",
    "極": "극",
    "和": "화",
    "從": "종",
    "雜": "잡",
    "曲": "곡",
    "直": "직",
    "炎": "염",
    "上": "상",
    "潤": "윤",
    "下": "하",
    "稼": "가",
    "穡": "색",
    "革": "혁",
    "外": "외",
    "內": "내",
}
_HANJA = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

STEM_KO = {s: _READINGS[s] for s in "甲乙丙丁戊己庚辛壬癸"}
BRANCH_KO = {b: _READINGS[b] for b in "子丑寅卯辰巳午未申酉戌亥"}
ELEMENT_KO = {e: _READINGS[e] for e in "木火土金水"}


def hangul(text: str) -> str:
    """Replace every known hanja character with its reading; unknown hanja stay as they are."""
    return "".join(_READINGS.get(ch, ch) for ch in text)


def has_hanja(text: str) -> bool:
    return bool(_HANJA.search(text))


def hanja_count(text: str) -> int:
    return len(_HANJA.findall(text))


def same_value(actual: object, claimed: object) -> bool:
    """Equal as strings, or equal once both are read in hangul (甲 == 갑, 正財 == 정재)."""
    a, c = str(actual), str(claimed)
    return a == c or hangul(a) == hangul(c)
