"""Report section guide (rules-v2): what each section covers, its minimum length, style rules.

The section set follows the structure of the Korean commercial marriage-saju readings this
project benchmarks (타고난 결혼운 → 결혼 상대로서 나의 장단점 → 배우자상 → 결혼 시기와 주의
시기 → 결혼 생활 → 개운법), mapped onto rules-v2 evidence. `min_chars` is enforced by the
validator; `target_chars` is guidance only.
"""

from __future__ import annotations

from typing import Any, NamedTuple


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
        "연도별 표(연도·간지·단서·주의)를 만들고 순위 상위 연도를 근거와 함께 설명, "
        "3) MONTH_TIMING으로 상위 연도의 유력 월을 제시. 단서가 많은 해와 적은 해를 비교하고, "
        "확률이나 단정 대신 '전통적으로 인연이 움직이는 시기'로 쓴다.",
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
        "두 사람 명식 소개, 궁합의 큰 그림(끌림·보완·마찰), 공동 순위 상위 연도와 핵심 조언.",
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
        "COUPLE_TIMING으로 연도별 표(연도·간지·A 단서·B 단서·주의)를 만들고, 공동 순위 "
        "상위 연도와 그 이유, 각자의 MONTH_TIMING에서 겹치는 유력 월을 제시.",
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

SECTIONS: dict[str, tuple[Section, ...]] = {"individual": INDIVIDUAL, "couple": COUPLE}

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
TIMING_RULES = {"individual": "YEAR_TIMING", "couple": "COUPLE_TIMING"}
MAX_HANJA_RATIO = 0.05  # per section, hanja characters / all characters

STYLE_RULES: tuple[str, ...] = (
    "본문은 한글로 쓴다. 간지·십성·오행·신살은 한글 표기(예: 을미 일주, 정재, 목·화, 도화살)로 "
    "쓰고, 한자는 꼭 필요할 때 첫 언급에만 괄호로 붙인다. 섹션마다 한자는 전체 글자의 5% 미만.",
    "evidence의 text_ko는 이미 한글이다. operands의 한자 값은 claims의 computed_values에만 쓰며, "
    "computed_values에는 한자나 한글 표기 모두 허용된다.",
    "명리 용어를 쓰면 바로 뒤에 일상 언어로 의미를 풀어 준다 (예: '편재(활동적이고 현실 감각이 "
    "있는 배우자 기운)').",
    "단정·확률·O/X 대신 '전통적으로 ~로 본다', '~한 경향으로 읽힌다'처럼 해석임을 드러내되, "
    "같은 면책 문구를 섹션마다 반복하지 않는다 (limitations에 한 번).",
    "결혼 시기는 연도와 월까지 구체적으로 쓰고, 각 연도·월마다 어떤 단서(배우자성, 배우자궁 합 "
    "등)가 근거인지 밝힌다. 표(마크다운)를 써도 된다.",
    "학파마다 다른 판단(신강약, 용신, 조후, 격국)은 근거의 방법론을 밝히고, 다른 관법이면 "
    "어떻게 달라지는지 한두 문장 덧붙인다.",
)


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
    return {
        "sections": [s._asdict() for s in sections],
        "style_rules": list(STYLE_RULES),
        "minimum_total_chars": sum(s.min_chars for s in sections),
        "target_total_chars": sum(s.target_chars for s in sections),
        "required_timing_rule": TIMING_RULES[mode],
        "claims": (
            "핵심 계산값(일주, 배우자궁, 신강약, 상위 연도 등)은 computed claim으로, 해석은 "
            f"interpretation claim으로 남긴다. {TIMING_RULES[mode]} evidence를 인용하는 claim이 "
            "최소 1개 필요하다."
        ),
    }
