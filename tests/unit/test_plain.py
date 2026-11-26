"""rules-v6 plain-language lexicon and jargon counter."""

from fateweave.domain.depth import SINSAL_KO
from fateweave.domain.glossary import has_hanja
from fateweave.domain.plain import PLAIN_TERMS, jargon_count, jargon_limit, jargon_terms

REQUIRED = [
    *"비견 겁재 식신 상관 편재 정재 편관 정관 편인 정인".split(),
    *"비겁 식상 재성 관성 인성".split(),
    *"갑목 을목 병화 정화 무토 기토 경금 신금 임수 계수".split(),
    *"자수 축토 인목 묘목 진토 사화 오화 미토 유금 술토 해수".split(),
    *"천간 지지 지장간 장생 관대 건록 제왕".split(),
    *"신강 신약 용신 희신 기신 격국 외격 종격".split(),
    *"육합 삼합 원진 귀문 도화살 역마살 화개살 천을귀인".split(),
]


def test_lexicon_covers_required_families():
    for term in [*REQUIRED, *SINSAL_KO.values()]:
        assert PLAIN_TERMS.get(term), term
    assert PLAIN_TERMS["상관"] == "틀을 깨는 표현력·말솜씨"
    assert PLAIN_TERMS["편관"] == "압박을 견디는 추진력·책임감"
    assert PLAIN_TERMS["무토"] == "큰 산 같은 묵직한 흙 기운"
    assert not any(has_hanja(v) for v in PLAIN_TERMS.values())


def test_jargon_sentence_counts_each_term():
    text = "천간 무토가 상관이라 지지 자수가 편관이라"
    assert jargon_terms(text) == ["천간", "무토", "상관", "편관"]
    assert jargon_count(text) == 4


def test_ordinary_words_are_not_jargon():
    text = (
        "상관없이 잘 지낸다. 상관이 없다. 지지해 주는 사람, 인성이 좋다, 관대하다, "
        "마음을 정화한다, 비견된다, 해수욕, 자수했다, 장생하길, 제왕처럼"
    )
    assert jargon_terms(text) == []


def test_longest_term_wins():
    assert jargon_terms("지장간에 숨은 기운, 천을귀인") == ["지장간", "천을귀인"]


def test_limit_is_one_per_300_chars_minimum_one():
    assert jargon_limit("가" * 50) == 1
    assert jargon_limit("가" * 1000) == 3


def test_common_phrases_are_not_jargon():  # final review: false hits in plain prose
    text = (
        "강한 편인데 꼼꼼한 편인 사람, 예민한 편인지, 결혼 예정인 두 사람, 중요한 결정인 만큼, "
        "일정인데, 가정인 만큼, 관성처럼 굳어, 상관관계, 일주일간, 3일간, 일간지, 재성장, "
        "자기신뢰, 감정관리, 비겁하다"
    )
    assert jargon_terms(text) == []


def test_real_uses_still_count():
    assert jargon_terms("편인이 강해 정인과 함께 정재운이 오고 (상관) 일간 기준") == [
        "편인",
        "정인",
        "정재",
        "상관",
        "일간",
    ]
