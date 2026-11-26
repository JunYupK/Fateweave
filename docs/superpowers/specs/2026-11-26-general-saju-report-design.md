# 종합 사주 리포트 (mode `general`) 설계

작성 2026-11-26. 상태: 초안 (사용자 승인 전).

## 1. 의도

결혼 사주를 보러 온 사람이 같은 생년월일로 **종합 사주**(타고난 성향, 일, 돈, 건강, 가족, 인생 흐름)도
함께 받아보게 한다. 결혼 리포트가 주인공이고 종합 리포트는 덧붙여 보는 전체 그림이다. 사용자는
성향·직업·인간관계에 특히 관심이 많으므로 이 세 섹션을 가장 깊고 길게 쓴다.

## 2. 목표 / 비목표 / 반목표

목표
- 새 분석 종류 `general`: profile 1개, 결혼 리포트와 **별도의 분석·리포트**로 저장한다.
- 기존 흐름 그대로: `prepare_analysis` → Claude가 근거로만 draft 작성 → `finalize_report` 검증 → 저장.
- 성향·직업·인간관계를 받칠 새 근거(십성 분포, 궁위, 육친, 적성 단서)와 결혼과 무관한 운의 흐름 근거.

비목표
- 직업·재물 등 주제별 연도 신호 점수나 "이직하기 좋은 해 1순위" 같은 연도 순위 (흐름 중심으로 결정).
- 결혼 리포트(`individual`)·궁합 리포트(`couple`)의 섹션·검증 규칙 변경.
- 커플용 종합 리포트.

반목표 (동작해도 실패로 본다)
- 근거와 무관한 일반 운세 문구(누구에게나 맞는 말)로 채워진 리포트.
- 건강 섹션이 질병 진단·의학적 조언처럼 읽히는 것.
- 한자투성이, 확률·단정 표현.

## 3. 제약

- 기존 계약 유지: 근거 ID·operands 검증, 한자 5% 미만, 확률 표현 금지, 저장본 불변, 과거 리포트는 자기
  버전 그대로.
- MCP 도구 5개는 그대로(`mode`·`report_type`·`list_reports`의 허용 값에 `general`만 추가).
- 공개 저장소: 테스트에 실제 생년월일을 쓰지 않는다. 커넥터 키 관련 CLAUDE.md 규칙 유지.

## 4. 접근 방식 (선택: A)

| | 방식 | 장단점 |
|---|---|---|
| **A (선택)** | 별도 `general` 분석·리포트 | 결혼 리포트를 건드리지 않고 종합 리포트가 자기 섹션·분량을 가진다. 분석 종류 추가에 DB 마이그레이션 1개. |
| B | 결혼 리포트에 종합 섹션 추가 | 호출 1번이지만 한 번에 쓸 분량이 너무 커지고 결혼만 원하는 사람에게도 강제된다. |
| C | 분석 1번 + 리포트 2개 | "분석 하나에 리포트 하나"로 중복 저장을 막는 현재 규칙을 바꿔야 해 A보다 비싸다. |

시기 표현은 **흐름 중심**(대운 10년 구간과 가까운 몇 년을 십성·원국 관계로 풀이, 점수·순위 없음)으로
결정했다. 주제별 연도 점수는 반응을 보고 후속 작업으로 판단한다.

## 5. 섹션 (사용자 결정 + 분량은 설계 제안)

개운법·근거 설명·한계 섹션은 두지 않는다(사용자 결정). 근거 설명은 Markdown의 인용 근거 부록이
대신하고, 한계는 `caveats`가 대신한다(§7).

| key | 제목 | min | target | 다룰 내용 / 주 근거 |
|---|---|---|---|---|
| `summary` | 핵심 요약 | 300 | 600 | 명식 한 줄, 성향·직업·관계의 핵심, 인생 흐름의 큰 그림, 희용 후보 오행 한 줄, 결혼은 "결혼 리포트 참고" 한 줄 |
| `temperament` | 타고난 성향과 기질 | 1000 | 1800 | **강화.** 일간 오행, 일주, 십성 분포(많은 기운·없는 기운, 표면과 지장간 구분), 12운성, 신강약 종합 판정, 격국·외격. 일상에서 드러나는 모습, 장점과 약점, 스트레스 받을 때의 모습 |
| `career` | 직업과 적성 | 1000 | 1800 | **강화.** 적성 단서(격국, 강한 십성 무리, 역마·화개·천을귀인·괴강 등), 전통 분류(조직형/전문기술형/사업형/학문·교육형/독립·경쟁형), 맞는 일하는 방식과 피하면 좋은 환경, 대운상 일의 전환기 |
| `wealth` | 재물운 | 500 | 1000 | 재성의 유무·위치·강약, 식상생재 등 재물 흐름, 돈을 다루는 성향 |
| `health` | 건강 체질 | 400 | 800 | 오행 과다·부족으로 본 전통 체질론. 의학적 진단이 아니며 이상이 있으면 의료진 상담이라고 명시 |
| `family_relations` | 인간관계와 가족 | 1000 | 1800 | **강화.** 궁위(연주=조상·어린 시절, 월주=부모·형제·사회, 일주=나·배우자, 시주=자녀·말년)와 그 자리의 십성·12운성, 육친 별(어머니·아버지·형제·배우자·자녀)의 위치와 강약, 기둥 간 합충(BRANCH_RELATIONS·STEM_RELATIONS의 위치를 궁위로 읽음), 친구·동료는 비겁 분포 |
| `life_flow` | 대운으로 본 인생 흐름 | 800 | 1500 | LUCK_FLOW로 10년 구간별 주제(일·관계·재물 중 무엇이 부각되는지)와 전환기 |
| `year_flow` | 올해와 가까운 몇 년 | 600 | 1200 | YEAR_FLOW로 horizon 연도별 십성·원국 관계·대운과의 관계를 풀이. 순위·점수·확률 없음 |

합계 최소 5,600자 (결혼 리포트 최소 6,550자보다 짧게, 강화 섹션 3개가 절반 이상).

## 6. 근거 (evidence)

### 6.1 general 카탈로그 구성

`build_general_evidence(chart, "self")` = 개인 규칙 중 결혼 시기 전용(`DAEWOON_FLOW`, `YEAR_TIMING`,
`MONTH_TIMING`, `LIFE_TIMING`)을 **뺀** 나머지 + 아래 새 규칙. `SPOUSE_PALACE`·`SPOUSE_STAR`는 가족
섹션과 결혼 한 줄 언급을 위해 남긴다. 개인·커플 카탈로그는 바뀌지 않는다(버전 문자열 제외).

### 6.2 새 규칙

모든 새 규칙은 시 미상이면 시주를 참조하지 않고, PARTIAL 명식에서 대안 명식에 따라 달라지는 기둥에
기대면 기존 `BOUNDARY_ASSUMPTION`을 붙인다(기존 규칙과 같은 방식).

1. **TEN_GOD_DISTRIBUTION** (rule_derived, 1개)
   - 다섯 무리(비겁·식상·재성·관성·인성)별: `surface`(천간 + 지지 본기, 일간 자신 제외), `hidden`(지장간
     가중합: 본기 1.0, 중기 0.6, 여기 0.3 — 본기는 surface에 이미 셌으므로 hidden에는 중기·여기만),
     `weight = surface + 0.5 × hidden`, `level`(없음: weight 0 / 약: < 1.5 / 보통: < 3 / 강: ≥ 3),
     그리고 무리 안 십성별 개수.
   - `dominant`(level 강, 없으면 weight 최댓값 무리), `missing`(level 없음).
   - text_ko 예: "십성 분포: 식상 강(표면 3), 인성 없음, …". 임계값은 Fateweave 설계 가설로 assumptions에 적는다.
2. **PALACES** (rule_derived, 기둥당 1개)
   - operands: position, 궁위 의미 코드(ancestry_youth / parents_siblings_society / self_spouse /
     children_later_life), pillar, 천간 십성, 지지 본기 십성, 12운성.
   - text_ko 예: "월주(부모·형제·사회 자리) 기묘: 천간 정인, 지지 편재, 12운성 …".
3. **KINSHIP** (rule_derived, 육친별 1개)
   - 성별에 따른 전통 육친표. 남: 어머니=정인, 아버지=편재, 형제=비견·겁재, 아내=정재(편재 보조),
     아들=편관, 딸=정관. 여: 어머니=정인, 아버지=편재, 형제자매=비견·겁재, 남편=정관(편관 보조),
     아들=상관, 딸=식신.
   - operands: relative, ten_gods, 발견 위치 목록(표면/지장간, 기둥), 개수, 해당 무리 level.
   - 학파 차이를 assumptions에 적는다(예: 아버지를 편재로 보는 관법 기준).
4. **APTITUDE_CUES** (rule_derived, 1개)
   - 입력: 격국(있으면), TEN_GOD_DISTRIBUTION의 dominant 무리, 관련 신살(역마·화개·천을귀인·괴강·양인·
     문창은 있으면; 현재 신살표에 없는 것은 추가하지 않고 있는 것만).
   - 전통 분류표: 비겁=독립·경쟁형, 식상=표현·전문기술형, 재성=사업·관리형, 관성=조직·공직형,
     인성=학문·교육형. 격국의 무리와 dominant 무리에서 분류 1~2개.
   - 학파 의존 해석임을 assumptions에 적는다. 단정이 아니라 "전통적으로 ~에 맞는다고 본다".
5. **LUCK_FLOW** (rule_derived, 대운당 1개)
   - operands: index, start_age, pillar, 천간·지지 십성과 무리, 원국과의 관계(`timing.natal_relations`
     재사용), 대운 오행이 억부 종합 판정의 희용 후보와 겹치는지(`favorable_match`).
   - 결혼 단서·점수 없음. text_ko는 "대운 3 (27~36세) 무인: 천간 편재, 지지 비견 … 희용 오행과 겹침".
6. **YEAR_FLOW** (rule_derived, horizon 연도당 1개)
   - operands: year, year_pillar, 천간·지지 십성과 무리, 원국과의 관계, 그해 대운 pillar(전환기면 둘),
     세운-대운 합충, `favorable_match`.
   - 순위·점수 없음.

## 7. 작성 가이드와 검증

- `writing_guide("general")`: §5 섹션표, 공통 문체 규칙(한글, 용어 풀이, 해석임을 드러내되 반복 금지)과
  general 전용 규칙(아래), `required_timing_rule: "LUCK_FLOW"`.
- general 전용 문체 규칙
  - 성향·직업·관계 섹션은 근거마다 "어떤 기운이 → 일상에서 어떻게 드러나는지 → 장단점"까지 쓴다.
  - 건강은 전통 체질론일 뿐 진단이 아님을 그 섹션 안에 한 번 쓴다.
  - 결혼은 요약에 한 줄만, 결혼 시기 연도는 쓰지 않는다(카탈로그에 결혼 시기 근거가 없다).
  - 출생 시각 미상·경계·전통 해석이라는 한계는 `caveats`에 한 번 쓴다.
- 검증(`validate_report`, general일 때)
  - 필수 섹션 §5, `SECTION_TOO_SHORT`, `HANJA_HEAVY`, 확률 표현 금지: 기존과 같다.
  - computed claim 1개 이상(기존).
  - 강화 섹션 근거 인용: `TEN_GOD_DISTRIBUTION`, `APTITUDE_CUES`, `KINSHIP`(또는 `PALACES`), `LUCK_FLOW`를
    각각 인용하는 claim이 1개 이상(kind 무관). 없으면 `UNSUPPORTED_CLAIM`.
  - `caveats`가 비어 있으면 `MISSING_CAVEATS`.
  - 궁합 점수·공통 후보 연도 검사는 couple 전용 그대로.

## 8. 저장·버전·MCP

- DB: Alembic 0002 — `ck_analysis_runs_mode`를 `('individual','couple','general')`로 교체(다운그레이드는
  general 행이 있으면 실패하게 둔다). `report_versions.report_type`은 제약이 없어 변경 없음.
- 모델: `PreparedAnalysis.mode`, `ReportDraft.report_type`, `list_reports(mode)`, MCP `prepare_analysis`
  `mode`에 `general` 추가. general의 subject key는 `self`, 프로필 1개.
- `RULE_VERSION` rules-v6. `scoring_versions`는 general에서 빈 값(점수 없음).
- Markdown 제목 "종합 사주 리포트". 섹션 라벨은 key가 모드 간에 겹치지 않게 새 key를 쓴다(`summary` 제외).
- MCP 안내(WORKFLOW_KO): general 필수 섹션과 규칙 추가, 그리고 **결혼 리포트(individual)가
  FINALIZED되면 같은 생년월일로 종합 사주도 볼지 사용자에게 한 번 제안**한다는 문장(교차 제안이 이
  기능의 목적).

## 9. 테스트

- 단위: 새 규칙 6개를 가상 명식(기존 테스트 명식 재사용)으로 값까지 고정, 시 미상·PARTIAL 처리,
  general 카탈로그에 결혼 시기 규칙이 없음, 개인·커플 카탈로그 불변(ID 동일, 버전 문자열 제외).
- 검증: 필수 근거 인용 누락, caveats 누락, 짧은 강화 섹션 거절.
- 통합: general prepare → finalize → get(Markdown 제목·섹션 순서), 마이그레이션 up/down, list_reports 필터.

## 10. 빌더에게 맡기는 것

- 텍스트 문구(text_ko)와 근거 operands의 세부 필드 이름.
- 새 규칙 코드 위치(`domain/rules.py`에 둘지 `domain/general.py`로 뺄지).
- 단계 나누기와 PR 단위(권장: 1) 새 근거 규칙, 2) general 모드·가이드·검증·마이그레이션·MCP).
