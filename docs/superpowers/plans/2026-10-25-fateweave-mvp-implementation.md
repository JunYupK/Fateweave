# Fateweave MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 개인 결혼사주와 커플 결혼운·궁합을 Claude 일반 채팅에서 분석하고, 결정론적 근거를 확인한 최초 리포트를 불변 보관하여 Claude/ChatGPT 양쪽에서 재사용할 수 있는 개인용 Fateweave를 구축한다.

**Architecture:** OCI 단일 VM 안에 기존 서비스와 독립된 Fateweave 컨테이너 및 PostgreSQL 전용 DB를 운영한다. `prepare_analysis`가 규칙 기반 계산/근거 스냅샷을 만들고, Claude가 구조화된 리포트를 작성해 `finalize_report`로 전달하며, 서버가 계산 주장·참조 근거·상태·멱등성을 검증한 후 불변 리포트로 저장한다. 공식 MCP Python SDK v2의 Streamable HTTP로 Claude 일반 채팅과 연결하고, ChatGPT에는 Markdown export를 수동 전달한다.

**Tech Stack:** Python 3.12, uv + `uv.lock`, `mcp==2.3.0` (공식 v2 `MCPServer`), FastAPI, Pydantic v2, SQLAlchemy 2 async + asyncpg, Alembic, PostgreSQL, `korean-saju==0.3.0`, `korean-lunar-calendar==0.4.0`, pytest/pytest-asyncio/httpx, Docker Compose, Nginx/HTTPS.

**Spec:** `docs/superpowers/specs/2026-10-25-fateweave-design.md`

## Global Constraints

- 프로젝트명 `Fateweave`; Python package `fateweave`; 별도 프런트엔드 및 별도 LLM API 호출 없음.
- 일반 Claude 채팅의 **원격** MCP가 MVP 주 인터페이스; Claude Code 의존 금지. ChatGPT 직접 호출은 MVP 대상 아님.
- 개인 결혼사주와 **커플 3영역(결혼 적합성/인연·성사운/공통 유리 시기)** 모두 구현. 예전 O/X 판정 금지.
- 출생시간 선택 입력; 모르면 `hour_pillar=None` 및 유효한 근거만 노출. 모호한 경계에서 확정 서술 금지.
- 전통 명리학 관법의 해석임을 명시. 실제 결혼 성사 가능성을 검증된 확률로 표현하거나 제3자 의사를 예측한다고 주장하지 않음.
- 구조화된 계산 주장은 스냅샷과 대조; 해석적 판단은 계산적 진실로 오인하지 않게 별도 `interpretation` 타입으로 표시.
- 최초 기준 보고서와 정정 버전은 불변 레코드. 저장 성공 응답이 없으면 사용자에게 저장 완료 안내 금지.
- ORM·API·MCP 코드가 기존 OCI 서비스의 소스·DB 사용자·DB·로그·배포에 접근하지 않게 격리.
- 최초 배포: 한국 출생/`Asia/Seoul`을 기본 경로로 지원. 다른 시간대나 출생지 경도 미지정은 검증된 지원 범위 안에서만 계산하고 불확실성을 명시; 조용한 임의 확정 금지.
- 명리학 라이브러리 및 MCP 패키지의 **정확한 버전은 lockfile에 고정**하고 계산정책 버전 `manse-v1`, 근거규칙 버전 `rules-v1`, 리포트 스키마 `report-v1` 기록.
- 작업 방식: 각 Task는 실패하는 테스트 → 실패 확인 → 최소 구현 → 통과 확인 → 커밋. 기존 리포/OCI 서비스는 절대 덮어쓰지 않는다.

## Review Focus

아래 다섯 가지 입력/장애 위험은 반드시 각 소유 Task의 회귀 테스트에 포함한다.

1. **출생시간 미상 + 입춘/절기/야자시 경계:** 불확실한 연·월·일주를 단정하지 않고 `missing_data`/`warnings`에 이유 표시 → Task 3.
2. **음력 윤달 잘못 지정 또는 달력 변환 범위 밖:** 조용한 음력→양력 대체 없이 명시적 입력 오류 → Task 2.
3. **잘못된 명리값·존재하지 않는 evidence ID가 포함된 Claude 결과:** 검증 실패 후 기준 리포트 미생성 → Task 8.
4. **동일 finalize 요청 중복/동시 호출 및 네트워크 재시도:** 한 번만 확정하고 동일 응답을 돌려줌. 다른 본문으로 같은 멱등키를 재사용하면 충돌 → Task 9.
5. **외부 비인증 접근·토큰 로그 누출·기존 DB 자원 오염:** MCP 호출 차단, 개인정보 비로그, 전용 DB/계정만 접근 → Task 11, Task 12.

---

## Repository Map (새 저장소 `fateweave/`의 루트 기준)

```text
pyproject.toml                 # 의존성/pytest/ruff 설정
uv.lock                        # 정확한 버전 고정
README.md                      # 요구사항/로컬 구동/안전한 사용법
.env.example                   # 값 없는 환경 변수 이름만
src/fateweave/
  config.py                    # 환경과 비밀값
  api.py                       # FastAPI + MCP ASGI 결합, /healthz
  models/inputs.py             # birth profile 입력 모델, calendar enum
  models/facts.py              # ChartSnapshot, Evidence, PreparedAnalysis
  models/reports.py            # ReportDraft, Claim, validation DTO
  domain/calendar.py           # 양음력 변환/입력 정책
  domain/manse.py              # 한국 만세력 어댑터
  domain/rules.py              # 개인 분석 rule/evidence 카탈로그
  domain/couple.py             # 커플 상호관계/공통 시기 evidence
  domain/validation.py         # 구조화된 보고서 검증
  services/analysis.py         # prepare/application flow
  services/reports.py          # finalize/list/get/alternatives
  storage/db.py                # AsyncSession 팩토리
  storage/tables.py            # 프로필/분석/보고서/대안 테이블
  storage/repository.py        # DB 쿼리/트랜잭션
  mcp/server.py                # 다섯 MCP 도구 및 안내 prompt
  mcp/auth.py                  # 외부 요청 인증/로그 필터
  admin.py                     # 로컬 전용 purge/maintenance CLI
alembic.ini
alembic/env.py
alembic/versions/0001_initial.py
tests/unit/test_config.py
tests/unit/test_calendar.py
tests/unit/test_manse.py
tests/unit/test_rules.py
tests/unit/test_couple.py
tests/unit/test_validation.py
tests/integration/test_storage.py
tests/integration/test_analysis.py
tests/integration/test_reports.py
tests/integration/test_mcp.py
tests/integration/test_security.py
tests/fixtures/verified_manse_cases.json  # 검증 근거·출처 기록
deploy/Dockerfile
deploy/compose.fateweave.yaml
deploy/nginx-fateweave.conf
deploy/postgres-init.sql       # 별도 DB/최소권한 role 템플릿
deploy/backup.sh
deploy/restore-check.sh
scripts/acceptance.md         # Claude 일반 채팅 실제 점검
```

**공통 타입 계약:** `BirthProfileInput` / `NormalizedBirth`(입력), `ChartSnapshot`(만세력), `Evidence`(검증 가능한 근거), `PreparedAnalysis`(분석 준비), `ReportDraft`(구조화 초안), `ValidationResult`(검증), `ReportView`(조회)를 Pydantic `BaseModel`로 정의한다. 외부 데이터에서 `gender_for_daewoon`은 전통 명리학 순역 대운 관법용 `male|female` 값으로만 쓰며 인격이나 성 정체성을 추론하는 근거로 사용하지 않는다. 공개 UUID를 DB 소유권 인증의 대체물로 사용하지 않는다.

## Milestone 1 — 신뢰 가능한 계산·근거 엔진

### Task 1: Fateweave 실행 기반 및 환경 설정

**Files:** Create `pyproject.toml`, `uv.lock`, `.env.example`, `src/fateweave/__init__.py`, `src/fateweave/config.py`, `src/fateweave/api.py`, `tests/unit/test_config.py`, `README.md`.

**Interfaces:**
- Produces `get_settings() -> Settings` (`DATABASE_URL`, `FATEWEAVE_MCP_KEY`, `PUBLIC_HOST`, `MANSE_POLICY_VERSION='manse-v1'`, `RULE_VERSION='rules-v1'`).
- Produces `app: FastAPI`, initially `GET /healthz -> {"status":"ok","service":"fateweave"}`. Credentials never appear in health response or `repr(Settings)`.

- [ ] **Step 1: Write failing tests** `test_healthz_is_app_scoped`, `test_required_secret_is_rejected_when_missing`, `test_settings_repr_hides_key` with `TestClient(app).get('/healthz').json()=={'status':'ok','service':'fateweave'}` and secret masking assertions.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/unit/test_config.py -v` → fail (missing app/settings).
- [ ] **Step 3: Implement** Python 3.12 + pinned MCP 2.3.0 and korean-saju 0.3.0; resolve all deps into `uv.lock`; Pydantic Settings and minimal FastAPI app; README dev instructions; `.env.example` has *no actual secrets*.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/unit/test_config.py -v` → all pass; `uv run ruff check .` → pass.
- [ ] **Step 5: Commit:** `git add pyproject.toml uv.lock .env.example README.md src/fateweave tests/unit/test_config.py && git commit -m "chore: bootstrap fateweave app"`.

### Task 2: Birth 입력 검증과 한국 음양력 변환

**Files:** Create `src/fateweave/models/inputs.py`, `src/fateweave/domain/calendar.py`, `tests/unit/test_calendar.py`.

**Interfaces:**
- `BirthProfileInput(alias: str | None, birth_date: date, calendar: Literal['solar','lunar'], leap_month: bool=False, birth_time: time | None=None, gender_for_daewoon: Literal['male','female'], timezone: Literal['Asia/Seoul']='Asia/Seoul', longitude: float | None=None)`.
- `normalize_birth(profile: BirthProfileInput) -> NormalizedBirth`: includes Gregorian date, original input, `assumptions: list[str]`, `birth_time: time | None`, optional longitude. `leap_month=True` only with lunar input.
- `BirthInputError(code: str, message: str)` returns `INVALID_LUNAR_DATE`, `UNSUPPORTED_DATE`, or `UNSUPPORTED_TIMEZONE` distinctly.

- [ ] **Step 1: Write failing tests** `test_known_leap_conversion` (`2017-05-01` lunar 윤5월→`2017-06-24` Gregorian), `test_invalid_leap_rejected`, `test_lunar_out_of_range_rejected` (year 2051), `test_time_unknown_kept_null`, `test_non_seoul_timezone_rejected` (MVP restriction), `test_solar_with_leap_flag_rejected`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/unit/test_calendar.py -v` → fail.
- [ ] **Step 3: Implement** offline `korean_lunar_calendar.KoreanLunarCalendar.setLunarDate(...)` (`False` ⇒ rejection); canonical date and explicit original calendar flags. No silent fallback to solar.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/unit/test_calendar.py -v` → pass.
- [ ] **Step 5: Commit:** `git add src/fateweave/models/inputs.py src/fateweave/domain/calendar.py tests/unit/test_calendar.py && git commit -m "feat: validate and normalize birth inputs"`.

### Task 3: 만세력 어댑터 및 경계조건 검증

**Files:** Create `src/fateweave/models/facts.py`, `src/fateweave/domain/manse.py`, `tests/unit/test_manse.py`, `tests/fixtures/verified_manse_cases.json`.

**Interfaces:**
- `compute_chart(birth: NormalizedBirth) -> ChartSnapshot`: `year/month/day/hour_pillar`, `ten_gods`, `daewoon`, `sewoon`, `policy_version`, `library_version`, `assumptions`, `warnings`, `alternatives`, `certainty: CONFIRMED|PARTIAL`.
- 출생시간 미상인 경우 **명식 계산의 내부 기준시각으로만** 정오를 사용할 수 있으나 `birth_time` 또는 `hour_pillar`에 정오를 채우는 일은 금지. 같은 날짜의 절기·일주 경계 후보를 검토하고 불확실하면 `PARTIAL` 및 대안 명식을 돌려준다.
- **manse-v1 시각 보정 원칙(R1 확정):** KST 표준 자오선 135°, 출생지 경도 보정 `(경도−135)×4분` 적용, 균시차 미적용(지방평균태양시), `yaja_si_separated=True`. 출생시간 미상이면 `hour_pillar=null`이며 임의 시각을 확정 결과로 저장하지 않는다.
- `korean-saju==0.3.0` + `yaja_si_separated=True` + 기본 미지정 경도 `126.9784`(서울 가정임을 warnings에 기록). 월주 절기 기준/입춘 기준, UTC/KST 변환 규약 버전 고정. 범위 밖 절기 fallback은 출생 시각이 절입 ±24h에 걸리면 `PARTIAL`/`BOUNDARY_REVIEW_REQUIRED`로 처리.

- [ ] **Step 1: Write failing tests** `test_known_1990_case` (1990-01-01 09:00 서울 ⇒ 己巳/丙子/丙寅/壬辰 — manse-v1 경도 보정 적용; 2026-10-25 R1 검증에서 기존 癸巳는 미보정 값이자 korean-saju README 예제와 동일한 오기로 확인되어 정정. 09:35 서울 ⇒ 癸巳. 독립 참조 및 출처를 fixture에 기록), `test_yaja_toggle_boundary` (1994-04-28 23:40 서울에서 default 갑신일; 대조 관법 을유일), `test_unknown_hour_no_hour_pillar`, `test_unknown_hour_on_solar_term_boundary_partial`, `test_nonbundled_solar_term_warns`, `test_facts_hash_stable`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/unit/test_manse.py -v` → fail.
- [ ] **Step 3: Implement** pure adapter calling `Saju.from_birth(...)`/`SajuAnalysis`; keep computed `ChartSnapshot` explicit. If oracle fixture does not match package, **do not massage expected values**; stop acceptance for this task and document/root-cause library or policy mismatch. Never silently use 12:00 as actual birth time.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/unit/test_manse.py -v` → pass, with reviewed independent fixtures; if blocked, mark Task blocked rather than committing unverified engine.
- [ ] **Step 5: Commit:** `git add src/fateweave/models/facts.py src/fateweave/domain/manse.py tests/unit/test_manse.py tests/fixtures/verified_manse_cases.json && git commit -m "feat: compute and qualify manse snapshots"`.

### Task 4: 개인 명리학 Evidence 카탈로그

**Files:** Create `src/fateweave/domain/rules.py`, `tests/unit/test_rules.py`.

**Interfaces:**
- `build_individual_evidence(chart: ChartSnapshot, subject_key: str) -> list[Evidence]`.
- `Evidence(id: str, kind: Literal['computed','rule_derived','interpretation_cue'], rule_code: str, operands: dict, text_ko: str, source_ref: str | None, assumptions: list[str])`.
- 고정 ID 규칙 `E-{subject_key}-{rule_code}-{sha256(canonical_operands)[:8]}`; 룰 `rules-v1`과 처리 순서로 stable results. 십성·배우자궁·합충·조후·용신 등은 **라이브러리가 실제 제공하는 계산값만** 확정 facts로; 학파별 평가 차이는 `interpretation_cue`로 표시.

- [ ] **Step 1: Write failing tests** `test_fact_reference_is_stable`, `test_missing_hour_excludes_hour_evidence`, `test_unavailable_yongsin_not_fabricated`, `test_evidence_sources_are_identified`, `test_rule_order_does_not_change_digest`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/unit/test_rules.py -v` → fail.
- [ ] **Step 3: Implement** named rule dispatch table (rule codes `PILLARS`, `TEN_GODS`, `SPOUSE_PALACE`, `ELEMENTS`, `BRANCH_RELATIONS`, `GYEOKGUK`, `YONGSIN`, `JOHU`, `DAEWOON`, `SEWOON`), `source_ref` maps to policy/rule docs, sorted deterministic evidence catalog; skip any unsupported calculation instead of conjecture.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/unit/test_rules.py -v` → pass.
- [ ] **Step 5: Commit:** `git add src/fateweave/domain/rules.py tests/unit/test_rules.py && git commit -m "feat: build verifiable individual evidence"`.

### Task 5: 커플 명리 관계와 양쪽 결혼 시기 근거

**Files:** Create `src/fateweave/domain/couple.py`, `tests/unit/test_couple.py`.

**Interfaces:**
- `build_couple_evidence(a: ChartSnapshot, b: ChartSnapshot, start_year: int, years: int=10) -> list[Evidence]`.
- 두 명식 사이 일간 천간합, 일지 합·충·형·해, 각각의 개인 증거, 대운·세운 교차 해석을 기록한다. 후보 연도는 실제 탐색 범위 내 기계적 조건 충족 여부만 표시하며 최종 결혼 시기를 결정하지 않는다. `relationship_outcome_probability` 필드 없음.

- [ ] **Step 1: Write failing tests** `test_symmetrical_couple_relation_facts`, `test_couple_year_candidates_inside_window`, `test_zero_overlap_does_not_invent_year`, `test_unknown_hour_no_hour_pair_claims`, `test_no_ox_or_probability_field`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/unit/test_couple.py -v` → fail.
- [ ] **Step 3: Implement** 합·충 등 lookup tables + 순서 무관한 pair evidence + 양쪽 `ChartSnapshot` 연결. 산술 점수나 '결혼 보장' 규칙은 추가하지 않는다.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/unit/test_couple.py -v` → pass.
- [ ] **Step 5: Commit:** `git add src/fateweave/domain/couple.py tests/unit/test_couple.py && git commit -m "feat: derive couple compatibility evidence"`.

## Milestone 2 — 분석 및 기준 리포트 저장

### Task 6: 독립 PostgreSQL 스키마·리포지토리

**Files:** Create `src/fateweave/storage/db.py`, `src/fateweave/storage/tables.py`, `src/fateweave/storage/repository.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`, `tests/integration/test_storage.py`.

**Interfaces:**
- `get_session() -> AsyncIterator[AsyncSession]`.
- `AnalysisRepository(session: AsyncSession)` defines `create_run(...) -> UUID`, `get_run(id: UUID) -> RunRow|None`, `add_report_version(...) -> ReportRow`, `get_report(id, version) -> ReportRow|None`, `list_reports(limit, mode)`, `add_alternative(...)`, `purge_profile_and_dependents(id)`.
- Tables: `birth_profiles`, `analysis_runs`, `report_versions`, `alternative_interpretations`. Uniques: `(analysis_id, idempotency_key)`, `(report_id, version)`; version append-only (DB permissions or triggers forbid silent UPDATE/DELETE except maintenance purge).

- [ ] **Step 1: Write failing integration tests** `test_migration_creates_four_tables`, `test_unique_report_version`, `test_immutable_versions`, `test_separate_database_role_denied_cross_database`, `test_transaction_rollback_keeps_prepared`. Use dedicated disposable Postgres `TEST_DATABASE_URL`; do not connect to production or Flight Friend DB.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/integration/test_storage.py -v` → fail, isolated Postgres required.
- [ ] **Step 3: Implement** SQLAlchemy 2 async models / Alembic initial migration, JSONB for snapshots and report sections, FK + indexes, immutable policy and repository; `created_at` UTC timestamps. Database bootstrap SQL itself belongs to Task 12.
- [ ] **Step 4: Verify GREEN:** `uv run alembic upgrade head && uv run pytest tests/integration/test_storage.py -v` using test DB → pass.
- [ ] **Step 5: Commit:** `git add src/fateweave/storage alembic.ini alembic tests/integration/test_storage.py && git commit -m "feat: persist immutable analysis and report records"`.

### Task 7: `prepare_analysis` 서비스 상태 머신

**Files:** Create `src/fateweave/services/analysis.py`, `tests/integration/test_analysis.py`.

**Interfaces:**
- `async prepare_analysis(mode: Literal['individual','couple'], profiles: list[BirthProfileInput], horizon_years: int=10) -> PreparedAnalysis`.
- `PreparedAnalysis(analysis_id: UUID, mode, facts, evidence_catalog, missing_data, policy_version, rule_version, status='PREPARED')`.
- 개인 정확히 1인, 커플 정확히 2인; `horizon_years` 1..30; `PreparedAnalysis` 생성과 DB 스냅샷 저장을 단일 트랜잭션으로 수행.

- [ ] **Step 1: Write failing tests** `test_prepare_individual_persists_snapshot`, `test_prepare_couple_persists_two_participants`, `test_invalid_profile_count_fails_without_insert`, `test_missing_hour_returns_limitation`, `test_recomputed_facts_same_policy_are_deterministic`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/integration/test_analysis.py -v` → fail.
- [ ] **Step 3: Implement** input normalization → chart → evidence → snapshot hash → `PREPARED` 저장, error names `INVALID_INPUT`, `CALCULATION_UNCERTAIN`, `STORAGE_UNAVAILABLE`. `analysis_id` newly minted UUID, display `evidence_catalog` stable IDs.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/integration/test_analysis.py -v` → pass.
- [ ] **Step 5: Commit:** `git add src/fateweave/services/analysis.py tests/integration/test_analysis.py && git commit -m "feat: prepare individual and couple analyses"`.

### Task 8: 보고서 스키마와 계산 근거 검증

**Files:** Create `src/fateweave/models/reports.py`, `src/fateweave/domain/validation.py`, `tests/unit/test_validation.py`.

**Interfaces:**
- `Claim(kind: Literal['computed','interpretation'], rule_code: str, evidence_ids: list[str], computed_values: dict[str,str|int|float]|None, statement: str)`.
- `ReportDraft(schema_version='report-v1', report_type: Literal['individual','couple'], sections: dict[str,str], claims: list[Claim], caveats: list[str], generated_by: str, prompt_version: str)`. `sections` 전체 본문 최대 40,000자(초과 시 `REPORT_TOO_LARGE`); 일반 리포트는 섹션별 충분한 서술을 권장하되 임의 요약으로 축약하지 않는다.
- Required individual sections: `summary, personality, relationship_style, spouse_profile, married_life, marriage_timing, evidence_explanation, limitations`; couple: `summary, marital_compatibility, relationship_potential, marriage_timing, evidence_explanation, limitations`.
- `validate_report(draft: ReportDraft, run: PreparedAnalysis) -> ValidationResult(valid: bool, errors: list[ValidationError])`. `computed_values` keys/values must match normalized evidence operands (where machine-verifiable). `interpretation` may cite rule cues but never impersonate `computed` facts. Generated Markdown free text alone cannot be exhaustively validated—tool contract makes key computations structured.

- [ ] **Step 1: Write failing tests** `test_rejects_unknown_evidence_id`, `test_rejects_wrong_year_or_stem`, `test_rejects_missing_section`, `test_rejects_wrong_report_type`, `test_accepts_alternative_school_as_interpretation`, `test_rejects_computed_claim_without_values`, `test_rejects_unsupported_marriage_probability_phrase` (예: '결혼 확률 82%' 문구 거절), `test_rejects_report_over_40000_chars`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/unit/test_validation.py -v` → fail.
- [ ] **Step 3: Implement** strict Pydantic schema, deterministic evidence reference comparison, human-readable validation error codes (`UNKNOWN_EVIDENCE`, `FACT_MISMATCH`, `MISSING_SECTION`, `UNSUPPORTED_CLAIM`). Explicit regex-based guard rejects unsupported probability expressions such as `결혼 확률\s*\d+(?:\.\d+)?%` and `결혼 가능성\s*\d+(?:\.\d+)?%` (other prose checks remain best-effort); over-limit body returns `REPORT_TOO_LARGE`. Avoid pretending full prose can be perfectly fact-checked.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/unit/test_validation.py -v` → pass.
- [ ] **Step 5: Commit:** `git add src/fateweave/models/reports.py src/fateweave/domain/validation.py tests/unit/test_validation.py && git commit -m "feat: validate structured canonical report drafts"`.

### Task 9: `finalize_report` 원자성·멱등성·수정본 처리

**Files:** Create `src/fateweave/services/reports.py`, `tests/integration/test_reports.py`.

**Interfaces:**
- `async finalize_report(analysis_id: UUID, draft: ReportDraft, idempotency_key: str) -> FinalizeResult`.
- Results: success `{report_id, version=1, status='FINALIZED', validation_errors=[]}`, or `{status='VALIDATION_FAILED', validation_errors}`. Already-finalized different draft returns `REPORT_CONFLICT`; same key + identical SHA256 payload returns same `report_id/version`; same key + different hash returns `IDEMPOTENCY_CONFLICT`.
- A failed validation persists attempt metadata/status but no finalized report; next corrected attempt can succeed on the same prepared run. Transaction locks run row (`SELECT FOR UPDATE`), unique DB key blocks races.

- [ ] **Step 1: Write failing tests** `test_success_creates_version_one`, `test_failed_validation_has_no_final_report`, `test_retry_with_corrected_draft_succeeds`, `test_same_key_replay_returns_existing_report`, `test_same_key_different_payload_conflicts`, `test_parallel_finalize_single_winner`, `test_service_storage_failure_never_returns_finalized`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/integration/test_reports.py -v` → fail.
- [ ] **Step 3: Implement** versioned canonical JSON+Markdown formatter (stable section order, source IDs), validate-before-transaction, atomic unique insertion/status and retry semantics. Persist original evaluation output/error codes without logging report text.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/integration/test_reports.py -v` → pass, including concurrent test.
- [ ] **Step 5: Commit:** `git add src/fateweave/services/reports.py tests/integration/test_reports.py && git commit -m "feat: finalize canonical reports atomically"`.

### Task 10: 조회·대안 해석·정정 버전·관리용 삭제

**Files:** Modify `src/fateweave/services/reports.py`, `src/fateweave/storage/repository.py`, `tests/integration/test_reports.py`; Create `src/fateweave/admin.py`.

**Interfaces:**
- `async get_report(report_id: UUID, version: int|None=None, format: Literal['markdown','json']='markdown') -> ReportView` (문서 본문+evidence digest+policy 버전 포함).
- `async list_reports(mode: Literal['individual','couple']|None=None, limit: int=20) -> list[ReportSummary]` (max 50).
- `async add_alternative_interpretation(report_id: UUID, school: str, content: str, evidence_refs: list[str]) -> AlternativeView`.
- `async create_correction(report_id: UUID, corrected: ReportDraft, reason: str) -> ReportView` 는 **관리용** 경로로만; 같은 `report_id`에서 `max(version)+1`을 새 레코드로 추가하고 직전 버전/정정 사유/검증 결과를 유지하며 기존 버전과 내용 모두 남음.
- `python -m fateweave.admin purge-profile --profile-id UUID --confirm` 는 서버 내부 CLI로만 제공; 관련 보고서/대안/프로필 정리, 사전 영향 건수 확인 및 감사 이벤트(PII 제외). 원격 MCP 삭제 도구 없음.

- [ ] **Step 1: Write failing tests** `test_get_markdown_includes_versions_and_caveats`, `test_list_filters_and_limits`, `test_alternative_does_not_modify_canonical`, `test_invalid_evidence_for_alternative_rejected`, `test_correction_preserves_previous_version`, `test_purge_removes_dependent_personal_data_only`, `test_not_found_is_not_an_empty_report`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/integration/test_reports.py -v` → fail.
- [ ] **Step 3: Implement** Markdown export and alternative addition using saved evidence catalog, append-only correction, CLI admin purging plus DB deletion policy. Keep all direct DB operations behind repository.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/integration/test_reports.py -v` → pass.
- [ ] **Step 5: Commit:** `git add src/fateweave/services/reports.py src/fateweave/storage/repository.py src/fateweave/admin.py tests/integration/test_reports.py && git commit -m "feat: retrieve versions and record alternative interpretations"`.

## Milestone 3 — Claude 연결·운영·사용자 인수

### Task 11: 원격 MCP 도구 공개 및 개인용 인증

**Files:** Create `src/fateweave/mcp/server.py`, `src/fateweave/mcp/auth.py`, `tests/integration/test_mcp.py`, `tests/integration/test_security.py`; Modify `src/fateweave/api.py`.

**Interfaces:**
- `create_mcp_server(services: ServiceContainer) -> MCPServer`; `create_app() -> FastAPI` mounts MCP Streamable HTTP at `/mcp`, `GET /healthz` remains non-sensitive.
- Tool names/signatures (Pydantic input/output permitted): `prepare_analysis(mode, profiles, horizon_years=10)`, `finalize_report(analysis_id, draft, idempotency_key)`, `get_report(report_id, version=None, format='markdown')`, `list_reports(mode=None, limit=20)`, `add_alternative_interpretation(report_id, school, content, evidence_refs)`.
- All `/mcp` methods (POST/GET/DELETE session) require `X-Fateweave-Key` matching server secret via constant-time comparison; no query-param credentials. Host/Origin allowlist with MCP SDK v2 `TransportSecuritySettings`, allowed public host explicitly. `GET /healthz` has no DB secrets and does not reveal record counts.
- Claude-facing instructions/prompts emphasize: **call prepare → write full draft with evidence IDs → call finalize → only claim saved after `FINALIZED`**. For later messages call `get_report`; if draft invalid, fix and retry. Tool annotations accurately designate read-only tools.

- [ ] **Step 1: Write failing tests** `test_tools_list_exposes_exact_five_tools`, `test_authenticated_prepare_finalize_get_end_to_end`, `test_missing_or_wrong_key_denied`, `test_secrets_and_birthdates_absent_from_access_logs`, `test_nonlisted_host_denied`, `test_direct_app_port_not_public_in_test_config`, `test_stopped_after_prepare_is_not_saved`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/integration/test_mcp.py tests/integration/test_security.py -v` → fail.
- [ ] **Step 3: Implement** official MCP 2.3.0 `from mcp.server import MCPServer` (do **not** use old v1 `mcp.server.fastmcp`), `streamable_http_app(...)` under FastAPI/Starlette with a **single** `/mcp` route (avoid accidental `/mcp/mcp`), lifespan startup, auth middleware before calls, ASGI client integration tests.
- [ ] **Step 4: Verify GREEN:** `uv run pytest tests/integration/test_mcp.py tests/integration/test_security.py -v` → pass; in-memory client/HTTP tool list and call both pass.
- [ ] **Step 5: Commit:** `git add src/fateweave/mcp src/fateweave/api.py tests/integration/test_mcp.py tests/integration/test_security.py && git commit -m "feat: expose authenticated remote MCP tools"`.

### Task 12: OCI 배포·격리·백업/복원 절차

**Files:** Create `deploy/Dockerfile`, `deploy/compose.fateweave.yaml`, `deploy/nginx-fateweave.conf`, `deploy/postgres-init.sql`, `deploy/backup.sh`, `deploy/restore-check.sh`; Modify `.env.example`, `README.md`; Create `scripts/acceptance.md`.

**Interfaces:**
- OCI runtime names `fateweave-api` (container/compose project), environment `FATEWEAVE_DATABASE_URL`, `FATEWEAVE_MCP_KEY`, `FATEWEAVE_PUBLIC_HOST`. Compose app binds **127.0.0.1 only** behind existing Nginx; private PostgreSQL service reachable via network only. `fateweave` DB role has no rights to other project databases.
- Nginx TLS vhost `FATEWEAVE_PUBLIC_HOST` placeholder (do not invent actual domain); `/mcp` proxy sends original Host, forwards custom auth header, sets suitable timeouts/body size, and permits MCP Streamable HTTP. `/healthz` no PII. TLS certificates reused only if hostname coverage is valid.
- `backup.sh` writes a restricted-permission logical dump of Fateweave DB; `restore-check.sh` restores to a disposable *Fateweave test DB*, verifies table counts without displaying birth data. Daily backup scheduling/rotation defaults are documented, not silently installed to existing cron.

- [ ] **Step 1: Write deployment acceptance checks** in `scripts/acceptance.md`: `docker compose -p fateweave -f deploy/compose.fateweave.yaml config`, `curl` health and unauthorized MCP (expect `401`), token-authorized MCP probe via client, role privilege SQL, daily dump and isolated restore; failing config first.
- [ ] **Step 2: Verify RED:** `docker compose -p fateweave -f deploy/compose.fateweave.yaml config` → fails (file absent).
- [ ] **Step 3: Implement** non-root Docker image, resource limits/healthcheck, isolated compose, dedicated DB role/schema rights, proxy and secret mounting via environment/secret file, structured PII-redacted logs, backup scripts and rollback instructions. Check OCI resource headroom and existing Nginx/Compose setup before enabling new container.
- [ ] **Step 4: Verify GREEN:** compose config validated; isolated Postgres restore smoke test; live health `200`, unauth MCP `401`, authorized tools/list reachable; Flight Friend continues unchanged. Verify no secrets in `docker compose config` output checked into logs.
- [ ] **Step 5: Commit:** `git add deploy README.md .env.example scripts/acceptance.md && git commit -m "ops: deploy fateweave alongside existing OCI services"` (no real `.env`, certs, dumps or secrets committed).

### Task 13: Claude 일반 채팅 실제 인수 및 ChatGPT handoff

**Files:** Modify `scripts/acceptance.md`, `README.md`; Add `tests/integration/test_e2e_flow.py` (non-LLM simulated path).

**Interfaces:**
- Test helper `run_deterministic_e2e(mode: Literal['individual','couple'], prepared_births: list[BirthProfileInput]) -> report_id` exercises `prepare → valid fake structured draft → finalize → get` without LLM API. Real Claude run is a human-in-the-loop acceptance checklist, not a pretend automated test.
- Accept in actual Claude chat: configure custom remote connector `Fateweave` URL `https://<actual-host>/mcp`, request header `X-Fateweave-Key`; enable tool for conversation; analyze at least one individual case and one couple case; verify saved `report_id/version` via `get_report`; paste Markdown output into ChatGPT and ask evidence-based follow-up.

- [ ] **Step 1: Write failing tests** `test_individual_complete_without_external_llm`, `test_couple_complete_without_external_llm`, `test_invalid_report_leaves_prepared_state`, `test_chatgpt_export_has_no_broken_evidence_refs`.
- [ ] **Step 2: Verify RED:** `uv run pytest tests/integration/test_e2e_flow.py -v` → fail.
- [ ] **Step 3: Implement** deterministic fake-draft fixture and acceptance docs; do **not** embed user birth data or authentic reports in repo/CI.
- [ ] **Step 4: Verify GREEN:** `uv run pytest -q` and `uv run ruff check .` → all pass; manual Claude connector / separate ChatGPT handoff tests passed by user. If actual Claude connection cannot be tested in this execution environment, mark external E2E **pending**, not passed.
- [ ] **Step 5: Commit:** `git add tests/integration/test_e2e_flow.py scripts/acceptance.md README.md && git commit -m "test: verify fateweave end-to-end report workflow"`.

## Release Gates (명시적 확인 후 완료 처리)

**R1 — Calculation** (Task 1–5): `pytest tests/unit` green, independent known cases/경계 입력 승인, 출생시간 미상에서 어떠한 시주도 확정하지 않음.

**R2 — Report** (Task 6–10): PostgreSQL 격리 및 테스트 DB, `prepare → finalize → get` 성공, 오류·재시도·동시성·버전 정정 검증, Markdown 내보내기.

**R3 — Remote MCP** (Task 11): 모든 다섯 도구 호출과 인증 성공; 근거 없이 저장 성공 주장하지 않는 안내/상태 제어.

**R4 — OCI / Live** (Task 12–13): 독립 배포/로그/백업/복원 확인, 실제 Claude 일반 채팅에서 리포트 두 종류 각각 생성 확인, ChatGPT 수동 handoff 확인. **실제 계정/OCI 자격증명 접근이 없는 실행자는 R4를 '수동 검증 대기'로 남긴다.**

## Key Design Risks and Decisions Locked for Execution

- `korean-saju==0.3.0`은 기능이 풍부하지만 소규모 오픈소스다. 테스트로 정확성이 확인되지 않으면 범위를 정직하게 제한하거나 해당 Task를 차단한다. AI가 계산을 대신하지 못한다.
- 출생시간 미상·절기·출생지 가정은 **계산의 불확실성**이므로 Claude가 관법으로 '해결'했다고 주장해서는 안 된다.
- `ReportDraft`의 구조화된 facts만 기계적으로 대조할 수 있다. 본문 전체가 완벽하게 검증되었다고 표시하지 않으며, 검증 badge/metadata에는 `structured_fact_validation`이라고 명시한다.
- 부부 궁합을 객관적 OX 판정·결혼 확률로 제공하지 않는다. 연도별 결과는 전통 관법의 해석이다.
- Claude가 `finalize_report`를 호출하지 않으면 `PREPARED` 그대로 둔다. 세션 중단 복구 시 다시 조회/제출, 자동 완료나 은밀한 저장 금지.
- 보존 정책 MVP 기본값: 사용자가 관리자 CLI로 삭제할 때까지. 과거 데이터의 자동 장기 수집/외부 공유 없음. 배포 시 이 기본값을 README에 명시하고 필요하면 사용자 승인 후 변경.
- 새로운 개발자/에이전트가 실제 서버와 저장소 구조를 모르면 Task 12에서 기존 자원·도메인·포트부터 검사; 존재한다고 가정해 작업하지 않는다.

## Technology References Checked (2026-10-25)

- Claude custom Remote MCP and fixed request headers: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Official MCP Python SDK v2 / Streamable HTTP / host allowlist: https://py.sdk.modelcontextprotocol.io/run/ and https://py.sdk.modelcontextprotocol.io/run/deploy/
- Korean saju calculation library: https://github.com/glee1228/korean_saju
- Korean lunar calendar conversion: https://pypi.org/project/korean-lunar-calendar/

## Execution Handoff

- 이 문서는 **코드 구현 계획**이며 아직 서비스를 구현하거나 서버에 배포한 것이 아니다.
- 사용자의 계획 검토/승인 후 `superpowers:subagent-driven-development` 또는 `superpowers:executing-plans`로 작업한다.
- 추천 실행 방식: **Subagent-driven**, 특히 만세력 경계조건·정형 검증·불변 DB/멱등성은 각각 독립 코드 리뷰 가치가 크기 때문이다. 해당 서브에이전트 실행이 불가능한 환경에서는 native execution + 별도의 리뷰/테스트 게이트로 전환한다.
