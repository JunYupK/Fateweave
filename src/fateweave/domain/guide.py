"""Report section guide (rules-v2): what each section covers, its minimum length, style rules.

The section set follows the structure of the Korean commercial marriage-saju readings this
project benchmarks (타고난 결혼운 → 결혼 상대로서 나의 장단점 → 배우자상 → 결혼 시기와 주의
시기 → 결혼 생활 → 개운법), mapped onto rules-v2 evidence. `min_chars` is enforced by the
validator; `target_chars` is guidance only.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from fateweave.domain.plain import PLAIN_TERMS


class Section(NamedTuple):
    key: str
    title: str
    min_chars: int
    target_chars: int
    covers: str


INDIVIDUAL: tuple[Section, ...] = (
    Section(
        "summary",
        "핵심 요약",
        300,
        600,
        "명식 한 줄 소개, 결혼운의 큰 그림, 가장 유력한 결혼 시기 2~3개(연도)와 핵심 주의점.",
    ),
    Section(
        "personality",
        "타고난 성향",
        600,
        1200,
        "일주(일간·일지)의 성격, 오행 분포(표면·지장간), 신강/신약과 그 근거, 12운성으로 본 "
        "기질, 격국이 있으면 격국. 일상에서 드러나는 모습으로 풀어 쓴다.",
    ),
    Section(
        "relationship_style",
        "연애 성향과 매력",
        600,
        1200,
        "연애할 때의 태도·표현 방식·갈등 패턴, 도화·홍염·화개 등 신살로 본 매력 포인트, "
        "끌리는 사람과 잘 맞는 사람의 차이.",
    ),
    Section(
        "marriage_aptitude",
        "타고난 결혼운과 결혼 상대로서의 장단점",
        500,
        1000,
        "배우자성(남 재성, 여 관성)의 유무·위치·혼잡, 배우자궁의 합충, 고신·과숙·고란 등 "
        "결혼 관련 신살, 공망. 결혼 상대로서 나의 장점과 단점을 구체적으로.",
    ),
    Section(
        "spouse_profile",
        "배우자상",
        600,
        1200,
        "배우자궁 십성·지장간·12운성과 배우자성으로 본 배우자의 성격, 직업 성향, 첫인상·분위기, "
        "경제관, 나와의 관계 역학. 끌리는 상대와 실제로 잘 사는 상대를 구분.",
    ),
    Section(
        "married_life",
        "결혼 생활",
        500,
        1000,
        "결혼 후 생활 방식, 역할 분담, 갈등이 생기는 지점과 푸는 법, 양가(시가·처가) 관계, "
        "가정의 분위기.",
    ),
    Section(
        "marriage_timing",
        "결혼 시기",
        1200,
        2500,
        "1) 대운 흐름(DAEWOON_FLOW)으로 인연이 강해지는 10년 구간, 2) YEAR_TIMING으로 "
        "연도별 표(연도·간지·신호 점수·단서·주의)를 만들고 신호 점수 순위 상위 연도를 근거와 "
        "함께 설명, 3) MONTH_TIMING으로 상위 연도의 유력 월, 4) LIFE_TIMING으로 20~50세 "
        "대운별 상위 연도를 제시. 신호가 높은 해와 낮은 해를 비교하고, 확률이나 단정 대신 "
        "'전통적으로 인연이 움직이는 시기'로 쓴다. 신호 점수는 확률이 아니다.",
    ),
    Section(
        "caution_periods",
        "주의 시기와 피해야 할 인연",
        400,
        800,
        "배우자궁 충·형·원진, 경쟁·견제 십성이 오는 해·월, 그때 흔한 갈등 양상, 피하면 좋은 "
        "인연 유형.",
    ),
    Section(
        "advice",
        "개운법과 조언",
        400,
        800,
        "희용 후보 오행(억부·조후)을 생활에 쓰는 법(색·방향·활동·사람), 연애·결혼 준비에서 "
        "실천할 점.",
    ),
    Section(
        "evidence_explanation",
        "근거 설명",
        200,
        500,
        "리포트가 기대고 있는 계산값과 해석 관법을 정리.",
    ),
    Section(
        "limitations",
        "한계",
        150,
        400,
        "출생 시각·경계·학파 차이 등 이 리포트의 제약. 전통 해석이며 예측이 아님을 한 번만.",
    ),
)

COUPLE: tuple[Section, ...] = (
    Section(
        "summary",
        "핵심 요약",
        300,
        600,
        "두 사람 명식 소개, 궁합 지수(COMPAT_SCORE)와 등급, 궁합의 큰 그림(끌림·보완·마찰), "
        "공통 유리 시기 후보 상위 연도와 핵심 조언.",
    ),
    Section(
        "personality_match",
        "성향 궁합",
        600,
        1200,
        "두 일간의 오행 관계(상생·상극·비화), 각자의 신강/신약과 기질, 오행 보완 관계 "
        "(COUPLE_ELEMENT_COMPLEMENT), 대화·생활 리듬이 맞는 점과 다른 점.",
    ),
    Section(
        "marital_compatibility",
        "부부 궁합",
        700,
        1400,
        "궁합 지수(COMPAT_SCORE)와 네 영역 점수(COMPAT_COMPONENT: 일간 관계·배우자궁·오행 "
        "보완·전체 명식 조화)를 표로 제시하고, 영역마다 점수를 만든 근거를 풀어 쓴다. "
        "배우자궁(일지)끼리의 관계, 서로가 상대의 배우자성인지(COUPLE_SPOUSE_STAR_MATCH), "
        "천간합·육합 등 끌림 요소, 띠(연지) 관계. 결혼 후 어떤 부부가 되는지.",
    ),
    Section(
        "conflict_points",
        "갈등 포인트와 해법",
        500,
        1000,
        "충·형·원진·귀문 등 마찰 관계가 실제로 드러나는 상황과, 두 사람이 할 수 있는 해법.",
    ),
    Section(
        "relationship_potential",
        "인연의 흐름",
        500,
        1000,
        "두 사람의 대운이 겹치는 흐름(COUPLE_LUCK_OVERLAP)으로 본 관계의 단계별 변화.",
    ),
    Section(
        "marriage_timing",
        "결혼 시기",
        1200,
        2500,
        "COUPLE_TIMING으로 연도별 표(연도·간지·A 신호·B 신호·단서·주의)를 만들고, "
        "COUPLE_TIMING_OVERLAP의 공통 후보만 '두 사람 모두에게 유리한 해'로 제시하며 낮은 쪽 "
        "신호가 높은 순서로 설명한다. 후보가 없으면 없다고 쓰고 결혼 적기를 지어내지 않는다. "
        "COUPLE_LIFE_TIMING으로 20~50세 구간의 공통 후보를, 각자의 MONTH_TIMING에서 겹치는 "
        "유력 월을 덧붙인다.",
    ),
    Section(
        "advice",
        "관계 조언",
        400,
        800,
        "서로 보완해 줄 수 있는 점, 주의 시기를 넘기는 법, 결혼 준비에서 실천할 점.",
    ),
    Section(
        "evidence_explanation",
        "근거 설명",
        200,
        500,
        "리포트가 기대고 있는 계산값과 해석 관법을 정리.",
    ),
    Section(
        "limitations",
        "한계",
        150,
        400,
        "출생 시각·경계·학파 차이 등 이 리포트의 제약. 전통 해석이며 예측이 아님을 한 번만.",
    ),
)

GENERAL: tuple[Section, ...] = (
    Section(
        "summary",
        "핵심 요약",
        300,
        600,
        "명식 한 줄(쉬운 말로), 성향·직업·관계의 핵심, 인생 흐름의 큰 그림, 도움이 되는 기운 한 "
        "줄, 연애·결혼의 핵심 한 줄.",
    ),
    Section(
        "temperament",
        "타고난 성향과 기질",
        1000,
        1800,
        "일간 오행, 일주, 기운 분포(TEN_GOD_DISTRIBUTION: 많은 기운·없는 기운, 겉과 속), "
        "12운성, 신강약 종합 판정, 격국·외격. 일상에서 드러나는 모습, 장점과 약점, 스트레스 받을 "
        "때의 모습.",
    ),
    Section(
        "career",
        "직업과 적성",
        1000,
        1800,
        "적성 단서(APTITUDE_CUES)의 전통 분류(조직형/전문기술형/사업형/학문·교육형/독립·경쟁형), "
        "맞는 일하는 방식과 피하면 좋은 환경, 10년 운(LUCK_FLOW)으로 본 일의 전환기.",
    ),
    Section(
        "wealth",
        "재물운",
        500,
        1000,
        "재성의 유무·위치·강약, 재물이 흐르는 방식, 돈을 다루는 성향.",
    ),
    Section(
        "health",
        "건강 체질",
        400,
        800,
        "오행 과다·부족으로 본 전통 체질론. 오행과 장부의 전통 대응(목=간·담, 화=심장·소장, "
        "토=위·비장, 금=폐·대장, 수=신장·방광)을 쓸 수 있다. 병명·치료·약 이름은 쓰지 않고, "
        "의학적 진단이 아니며 이상이 있으면 의료진과 상담하라는 문장을 반드시 넣는다.",
    ),
    Section(
        "family_relations",
        "인간관계와 가족",
        1000,
        1800,
        "궁위(PALACES: 연주=조상·어린 시절, 월주=부모·형제·사회, 일주=나·배우자, 시주=자녀·말년)와 "
        "그 자리의 기운, 육친(KINSHIP)의 위치와 강약, 기둥끼리의 합충을 가족 자리로 읽기, 친구·"
        "동료 관계는 비겁 분포로.",
    ),
    Section(
        "love_marriage",
        "연애와 결혼",
        600,
        1200,
        "연애할 때의 성향과 매력(SINSAL의 도화·홍염 등), 잘 맞는 배우자(SPOUSE_PALACE·SPOUSE_STAR·"
        "KINSHIP의 배우자), 인연이 강해지는 10년 구간(LUCK_FLOW의 spouse_star). 결혼 시기 연도는 "
        "쓰지 않고, 자세한 시기와 배우자상은 결혼 리포트에서 볼 수 있다고 한 줄로 잇는다.",
    ),
    Section(
        "life_flow",
        "대운으로 본 인생 흐름",
        800,
        1500,
        "LUCK_FLOW로 10년 구간별로 일·관계·재물 중 무엇이 부각되는지와 전환기.",
    ),
    Section(
        "year_flow",
        "올해와 가까운 몇 년",
        600,
        1200,
        "YEAR_FLOW로 연도별 기운, 타고난 기둥과의 관계, 그때의 10년 운과의 관계. "
        "순위·점수·확률 없음.",
    ),
)

SECTIONS: dict[str, tuple[Section, ...]] = {
    "individual": INDIVIDUAL,
    "couple": COUPLE,
    "general": GENERAL,
}

# Required sections of rules-v1 analyses (prepared before rules-v2); no minimum length.
LEGACY_REQUIRED: dict[str, tuple[str, ...]] = {
    "individual": (
        "summary",
        "personality",
        "relationship_style",
        "spouse_profile",
        "married_life",
        "marriage_timing",
        "evidence_explanation",
        "limitations",
    ),
    "couple": (
        "summary",
        "marital_compatibility",
        "relationship_potential",
        "marriage_timing",
        "evidence_explanation",
        "limitations",
    ),
}
TIMING_RULES = {"individual": "YEAR_TIMING", "couple": "COUPLE_TIMING", "general": "LUCK_FLOW"}
# general: each group needs at least one claim citing evidence of one of its rules.
GENERAL_REQUIRED_CITATIONS: tuple[tuple[str, ...], ...] = (
    ("TEN_GOD_DISTRIBUTION",),
    ("APTITUDE_CUES",),
    ("KINSHIP", "PALACES"),
    ("LUCK_FLOW",),
    ("SPOUSE_PALACE", "SPOUSE_STAR"),
)
SCORE_RULE = "COMPAT_SCORE"
MAX_HANJA_RATIO = 0.05  # per section, hanja characters / all characters (rules-v2..v5)
PLAIN_MAX_HANJA_RATIO = 0.01  # rules-v6+
PLAIN_RULE_VERSION = 6  # first rule version with the plain-language checks
# Sections exempt from JARGON_HEAVY: they exist to list the evidence the report relies on.
JARGON_EXEMPT: dict[str, frozenset[str]] = {
    "individual": frozenset({"evidence_explanation"}),
    "couple": frozenset({"evidence_explanation"}),
}

STYLE_RULES: tuple[str, ...] = (
    "명리 용어는 쓰지 않고 writing_guide.plain_terms의 뜻으로 쓴다. '천간 무토가 상관이라'처럼 "
    "용어를 이어 붙이지 않는다. 꼭 필요하면 섹션당 한두 번, 쉬운 말 뒤 괄호로만. 섹션 300자당 "
    "1개를 넘으면 JARGON_HEAVY로 거절된다.",
    "본문에 한자를 쓰지 않는다(claim의 computed_values는 예외). 섹션 한자 1% 초과는 HANJA_HEAVY.",
    "evidence의 text_ko는 이미 한글이다. operands의 한자 값은 claims의 computed_values에만 쓰며, "
    "computed_values에는 한자나 한글 표기 모두 허용된다.",
    "단정·확률·O/X 대신 '전통적으로 ~로 본다', '~한 경향으로 읽힌다'처럼 해석임을 드러내되, "
    "같은 면책 문구를 섹션마다 반복하지 않는다.",
    "학파마다 다른 판단(신강약, 용신, 조후, 격국)은 근거의 방법론을 밝히고, 다른 관법이면 "
    "어떻게 달라지는지 한두 문장 덧붙인다.",
    "신강약은 STRENGTH의 종합(consensus) 판정을 기준으로 쓴다. 두 관법(라이브러리 10점제, "
    "통근·월령 반영)이 갈리면 둘 다 소개하고, 억부 용신과 시기 해석은 종합 판정을 따른다.",
    "SPECIAL_STRUCTURE에 성립한 외격이 없으면 정격으로 해석하고 종격·화기격 해석을 하지 않는다. "
    "외격이 성립하면 억부 용신과 방향이 달라질 수 있음을 함께 쓴다.",
    "HOUR_BOUNDARY_NEAR 경고가 있으면 시주가 대안 시주일 수 있으므로, 시주에 기대는 해석"
    "(시지 신살, 시주 십성 등)은 대안 시주에서는 어떻게 달라지는지도 짧게 덧붙인다.",
)

# individual and couple only (general has no marriage-timing evidence and no limitations section).
MARRIAGE_STYLE_RULES: tuple[str, ...] = (
    "면책·한계 문구는 limitations 섹션에 한 번만 쓴다.",
    "결혼 시기는 연도와 월까지 구체적으로 쓰고, 각 연도·월마다 어떤 단서(배우자성, 배우자궁 합 "
    "등)가 근거인지 밝힌다. 표(마크다운)를 써도 된다.",
)

COUPLE_STYLE_RULES: tuple[str, ...] = (
    "궁합 지수는 Fateweave 규칙표로 계산한 해석 지수(0~100)이지 결혼 확률·성사 가능성이 아니다. "
    "'궁합 지수 N점'처럼 쓰고 숫자는 서버 값(COMPAT_SCORE·COMPAT_COMPONENT)을 그대로 옮긴다. "
    "다른 숫자를 쓰면 SCORE_MISMATCH로 거절된다.",
    "COMPAT_SCORE에 score_range가 있으면 대안 명식 범위로 함께 쓰고, status가 PARTIAL이거나 "
    "영역이 REDUCED_SCOPE이면 무엇이 빠졌는지(assessments.compatibility.excluded) 한 번 밝힌다.",
    "'공통 유리 시기', '최적의 해', '결혼 적기'로 제시하는 연도는 COUPLE_TIMING_OVERLAP·"
    "COUPLE_LIFE_TIMING의 후보 연도만 쓴다. 후보가 아닌 해를 그렇게 쓰면 TIMING_NOT_CANDIDATE로 "
    "거절된다. 후보가 아닌 해를 언급할 때는 '공통 후보 아님'처럼 분명히 구분한다.",
)

GENERAL_STYLE_RULES: tuple[str, ...] = (
    "성향·직업·인간관계 섹션은 근거마다 '어떤 기운이 있는지 → 일상에서 어떻게 드러나는지 → "
    "장점과 약점'까지 쓴다. 누구에게나 맞는 일반론으로 채우지 않는다.",
    "건강은 전통 체질론일 뿐 진단이 아니다. health 섹션에 '의학적 진단이 아니며 이상이 있으면 "
    "의료진과 상담'이라는 문장을 넣고(없으면 HEALTH_DISCLAIMER_MISSING), 병명·약·복용·처방 같은 "
    "말은 쓰지 않는다(HEALTH_MEDICAL_CLAIM).",
    "연애와 결혼은 love_marriage 섹션에서 성향·매력·맞는 배우자·인연이 강해지는 10년 구간까지 "
    "쓴다. 결혼 시기 연도는 쓰지 않고 자세한 시기와 배우자상은 결혼 리포트를 권한다.",
    "출생 시각 미상·경계·전통 해석이라는 한계는 caveats에 한 번 쓴다(비어 있으면 MISSING_CAVEATS). "
    "'확인 불가'로 표시된 기운·가족 자리는 없다고 단정하지 않는다.",
    "TEN_GOD_DISTRIBUTION, APTITUDE_CUES, KINSHIP 또는 PALACES, LUCK_FLOW, SPOUSE_PALACE 또는 "
    "SPOUSE_STAR를 각각 인용하는 claim이 최소 1개씩 필요하다.",
)


def rule_version_number(version: str) -> int:
    """'rules-v6' -> 6."""
    return int(version.rsplit("-v", 1)[1])


def required_sections(mode: str, rule_version: str) -> tuple[str, ...]:
    if rule_version == "rules-v1":
        return LEGACY_REQUIRED[mode]
    return tuple(s.key for s in SECTIONS[mode])


def section_labels() -> dict[str, str]:
    labels = {s.key: s.title for sections in SECTIONS.values() for s in sections}
    labels["relationship_potential"] = "인연의 흐름"
    return labels


def writing_guide(mode: str) -> dict[str, Any]:
    """The guide returned with every rules-v2 prepare_analysis result."""
    sections = SECTIONS[mode]
    couple = mode == "couple"
    extra = {
        "individual": MARRIAGE_STYLE_RULES,
        "couple": (*MARRIAGE_STYLE_RULES, *COUPLE_STYLE_RULES),
        "general": GENERAL_STYLE_RULES,
    }[mode]
    guide: dict[str, Any] = {
        "sections": [s._asdict() for s in sections],
        "style_rules": [*STYLE_RULES, *extra],
        "minimum_total_chars": sum(s.min_chars for s in sections),
        "target_total_chars": sum(s.target_chars for s in sections),
        "required_timing_rule": TIMING_RULES[mode],
        "plain_terms": dict(PLAIN_TERMS),
        "claims": (
            "핵심 계산값(일주, 배우자궁, 신강약, 상위 연도 등)은 computed claim으로, 해석은 "
            f"interpretation claim으로 남긴다. {TIMING_RULES[mode]} evidence를 인용하는 claim이 "
            "최소 1개 필요하다."
            + (
                f" {SCORE_RULE} evidence를 인용하고 computed_values에 score를 적은 computed "
                "claim도 1개 필요하다."
                if couple
                else ""
            )
        ),
    }
    if couple:
        guide["required_score_rule"] = SCORE_RULE
    if mode == "general":
        guide["required_citations"] = [list(x) for x in GENERAL_REQUIRED_CITATIONS]
    return guide
