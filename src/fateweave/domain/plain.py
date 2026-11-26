"""Plain-language lexicon (rules-v6): myeongri terms and what they mean in everyday Korean.

`PLAIN_TERMS` is sent with every writing guide so the same term is explained the same way in
every report. `jargon_terms` finds the terms a section still uses; validation rejects a section
with more than one per 300 characters (JARGON_HEAVY). Terms that are also ordinary words
(인성 "character", 지지 "support", 관대 "generous", ...) are glossed but never counted, and a few
terms are counted only when they are not the start of an ordinary word (상관없이, 비견되다).
"""

from __future__ import annotations

import re

PLAIN_TERMS: dict[str, str] = {
    # 십성
    "비견": "나와 어깨를 나란히 하는 자존심·독립심",
    "겁재": "지기 싫어하는 경쟁심·승부욕",
    "식신": "여유롭게 즐기며 재능을 꾸준히 펼치는 힘",
    "상관": "틀을 깨는 표현력·말솜씨",
    "편재": "크게 벌고 크게 쓰는 활동적인 재물 감각",
    "정재": "성실하게 모으는 안정적인 재물 감각",
    "편관": "압박을 견디는 추진력·책임감",
    "정관": "규칙과 신뢰를 지키는 반듯함·명예",
    "편인": "남다른 직관과 독특한 생각",
    "정인": "배우고 받아들이는 힘, 보살핌을 받는 복",
    # 십성 무리
    "비겁": "나와 같은 기운(자존감·동료·경쟁)",
    "식상": "밖으로 드러내는 기운(표현력·재능 발산)",
    "재성": "다루고 차지하는 기운(재물·현실 감각)",
    "관성": "나를 다스리는 기운(규칙·책임·조직)",
    "인성": "나를 돕는 기운(배움·보호·생각)",
    # 천간 오행
    "갑목": "곧게 뻗는 큰 나무 기운",
    "을목": "부드럽게 휘어 자라는 풀·덩굴 기운",
    "병화": "환하게 비추는 햇빛 기운",
    "정화": "은은하게 밝히는 촛불 기운",
    "무토": "큰 산 같은 묵직한 흙 기운",
    "기토": "곡식을 키우는 논밭 같은 흙 기운",
    "경금": "단단한 바위·쇠 기운",
    "신금": "날카롭게 다듬어진 보석·칼 기운",
    "임수": "넓게 흐르는 바다·큰 강 기운",
    "계수": "스며드는 빗물·이슬 기운",
    # 지지 오행 (신금은 천간과 같은 풀이)
    "자수": "한겨울 깊은 물 기운",
    "축토": "얼어 있는 겨울 흙 기운",
    "인목": "이른 봄 솟아나는 나무 기운",
    "묘목": "한봄 무성한 풀·나무 기운",
    "진토": "봄비 머금은 촉촉한 흙 기운",
    "사화": "초여름 달아오르는 불 기운",
    "오화": "한여름 가장 뜨거운 불 기운",
    "미토": "늦여름 메마른 흙 기운",
    "유금": "가을 단단히 여문 쇠 기운",
    "술토": "늦가을 건조한 흙 기운",
    "해수": "초겨울 차가운 물 기운",
    # 명식 구조
    "천간": "겉으로 드러나는 기운",
    "지지": "속에서 받쳐 주는 기운",
    "지장간": "속에 숨어 있는 기운",
    "일간": "나 자신을 나타내는 기운",
    "일주": "나와 배우자 자리를 함께 보여 주는 기둥",
    "월령": "태어난 계절의 기운",
    # 12운성
    "장생": "새로 태어나 자라는 단계",
    "목욕": "서툴지만 꾸미고 드러내는 단계",
    "관대": "자신감을 갖추고 사회에 나서는 단계",
    "건록": "자리를 잡고 스스로 서는 단계",
    "임관": "자리를 잡고 스스로 서는 단계",
    "제왕": "기운이 가장 왕성한 단계",
    # 강약·용신·격
    "신강": "내 기운이 강한 편",
    "신약": "내 기운이 약한 편",
    "중화": "내 기운이 고르게 균형 잡힌 편",
    "용신": "가장 도움이 되는 기운",
    "희신": "도움을 보태는 기운",
    "기신": "부담이 되는 기운",
    "격국": "명식의 큰 틀",
    "외격": "한쪽 기운으로 크게 쏠린 특별한 틀",
    "종격": "강한 기운을 따라가는 특별한 틀",
    # 관계
    "육합": "두 기운이 손잡는 끌림",
    "삼합": "세 기운이 한 방향으로 모이는 결속",
    "반합": "같은 방향으로 모이려는 약한 결속",
    "원진": "이유 없이 서로 거슬리는 기운",
    "귀문": "예민하게 신경이 곤두서는 기운",
    "공망": "비어 있어 힘이 덜 실리는 자리",
    # 신살
    "도화살": "사람의 눈길을 끄는 매력·인기",
    "역마살": "이동·변화가 잦은 활동성",
    "화개살": "예술성·종교성, 혼자 깊이 파고드는 기질",
    "홍염살": "짙은 개인적 매력",
    "천을귀인": "어려울 때 돕는 사람이 나타나는 복",
    "양인살": "강한 추진력과 고집",
    "고신살": "혼자 있는 시간이 많아지는 기운",
    "과숙살": "혼자 있는 시간이 많아지는 기운",
    "백호살": "강렬한 기운, 급하게 일이 벌어지는 기운",
    "괴강살": "강한 주관과 결단력",
    "고란살": "인연이 외로울 수 있다는 기운",
    "음양차착살": "가족 관계가 엇갈리기 쉽다는 기운",
}

# Glossed but never counted: they are also everyday words.
_AMBIGUOUS = frozenset(
    {"인성", "지지", "관대", "신약", "정화", "해수", "계수", "장생", "제왕", "자수", "사화", "중화",
     "목욕", "묘목", "일주", "임관"}
)  # fmt: skip
# Counted only when not the start of an ordinary word.
_NOT_FOLLOWED_BY = {
    "상관": r"\s*(?:없|있|하|않|이\s*없|이\s*있|은\s*없|도\s*없)",
    "비견": r"\s*(?:되|돼|된|됨|될|하|할|한)",
    "식상": r"(?:하|해|한|했|함)",
    "편재": r"(?:되|돼|된|됨)",
}


def _pattern() -> re.Pattern[str]:
    terms = sorted((t for t in PLAIN_TERMS if t not in _AMBIGUOUS and len(t) > 1), key=len)
    parts = [
        re.escape(t) + (f"(?!{_NOT_FOLLOWED_BY[t]})" if t in _NOT_FOLLOWED_BY else "")
        for t in reversed(terms)
    ]
    return re.compile("|".join(parts))


_JARGON = _pattern()


def jargon_terms(text: str) -> list[str]:
    """Counted terms in `text`, in order of appearance (longest match first)."""
    return [m.group(0) for m in _JARGON.finditer(text)]


def jargon_count(text: str) -> int:
    return len(jargon_terms(text))


def jargon_limit(text: str) -> int:
    """How many counted terms a section of this length may use (one per 300 chars, min 1)."""
    return max(1, len(text) // 300)
