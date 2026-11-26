# General Report (`general`) and Plain-Language Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third analysis mode `general` (종합 사주 리포트) with new evidence for temperament, career and family, and make every report (individual, couple, general) use plain Korean instead of myeongri jargon, enforced by validation from rules-v6.

**Architecture:** A plain-language lexicon (`domain/plain.py`) feeds the writing guide and a per-section jargon counter in validation. A new `domain/general.py` defines six evidence rules and `build_general_evidence`, built through a shared evidence builder extracted from `rules.py`. The `general` mode is threaded through models, storage (Alembic 0002), the analysis service, the report renderer and the MCP server, with its own sections and validation rules.

**Tech Stack:** Python 3.12, uv, pydantic, SQLAlchemy async + Alembic, PostgreSQL, korean-saju 0.3.0, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-26-general-saju-report-design.md`

## Global Constraints

- `RULE_VERSION = "rules-v6"`. New style checks (`JARGON_HEAVY`, hanja 1%) and every `general` rule apply only when the run's rule_version is rules-v6 or later; rules-v5 and earlier runs keep their current checks.
- Jargon limit: per section, counted terms ≤ `max(1, len(text) // 300)`; above it → `JARGON_HEAVY`. Not counted: 오행 names 목·화·토·금·수, "사주", "대운"; claims' `computed_values` and `statement`; the individual `evidence_explanation` section.
- Hanja limit for rules-v6+: 1% of a section (sections ≥ 100 chars), code `HANJA_HEAVY`; rules-v2..v5 keep 5%.
- Individual and couple evidence catalogs keep identical IDs and operands (only `source_ref` version strings change).
- No real birth data in tests; synthetic charts only. Never put the connector key in code, tests, logs or commits (CLAUDE.md).
- Probability ban, evidence-ID checks and the couple score/year checks stay as they are.
- Run before each commit: `uv run ruff check .` and `TEST_DATABASE_URL=... uv run pytest -q tests` (unit-only tasks may run `tests/unit`).

## Review Focus

1. Ordinary Korean words that contain a term ("상관없이", "지지해 주는", "인성이 좋다", "관대하다", "정화", "비견된다") must not count as jargon — test in Task 1.
2. An analysis prepared under rules-v5 and finalized after deploy must validate with the old rules (no `JARGON_HEAVY`, 5% hanja) — test in Task 2.
3. Hour-unknown chart in `general`: nothing says a relative or group is "없음" when the hour could hold it, and the hour palace is `unknown` — tests in Tasks 3 and 4.
4. PARTIAL (boundary) chart: new general rules that depend on a differing pillar carry `BOUNDARY_ASSUMPTION` like existing rules — test in Task 6.
5. A health disclaimer sentence that itself mentions 진단/치료/질환 ("질환을 진단하거나 치료하는 내용이 아니다") must not trigger `HEALTH_MEDICAL_CLAIM` — test in Task 8.

---

## PR 1 — Plain-language rules for all reports

### Task 1: Plain-language lexicon and jargon counter

**Files:**
- Create: `src/fateweave/domain/plain.py`
- Test: `tests/unit/test_plain.py`

**Interfaces:**
- Produces: `PLAIN_TERMS: dict[str, str]` (hangul term → plain gloss), `jargon_terms(text: str) -> list[str]` (matched terms in order), `jargon_count(text: str) -> int`, `jargon_limit(text: str) -> int` (= `max(1, len(text) // 300)`).

- [ ] **Step 1: Write the failing tests**

```python
from fateweave.domain.plain import PLAIN_TERMS, jargon_count, jargon_limit, jargon_terms

def test_lexicon_covers_required_families():
    for term in ["비견", "겁재", "식신", "상관", "편재", "정재", "편관", "정관", "편인", "정인",
                 "비겁", "식상", "재성", "관성", "인성",
                 "갑목", "을목", "병화", "정화", "무토", "기토", "경금", "신금", "임수", "계수",
                 "자수", "축토", "인목", "묘목", "진토", "사화", "오화", "미토", "유금", "술토", "해수",
                 "천간", "지지", "지장간", "장생", "관대", "건록", "제왕",
                 "신강", "신약", "용신", "희신", "기신", "격국", "외격", "종격",
                 "육합", "삼합", "원진", "귀문", "도화살", "역마살", "화개살", "천을귀인"]:
        assert term in PLAIN_TERMS and PLAIN_TERMS[term]
    assert PLAIN_TERMS["상관"] == "틀을 깨는 표현력·말솜씨"
    assert PLAIN_TERMS["편관"] == "압박을 견디는 추진력·책임감"
    assert PLAIN_TERMS["무토"] == "큰 산 같은 묵직한 흙 기운"
    assert all(not any("一" <= ch <= "鿿" for ch in v) for v in PLAIN_TERMS.values())

def test_jargon_sentence_counts_each_term():
    assert jargon_terms("천간 무토가 상관이라 지지 자수가 편관이라") == ["천간", "무토", "상관", "편관"]

def test_ordinary_words_are_not_jargon():
    text = "상관없이 잘 지낸다. 지지해 주는 사람, 인성이 좋다, 관대하다, 마음을 정화한다, 비견된다, 해수욕, 자수했다"
    assert jargon_count(text) == 0

def test_limit_is_one_per_300_chars_minimum_one():
    assert jargon_limit("가" * 50) == 1
    assert jargon_limit("가" * 1000) == 3
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_plain.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `plain.py`.**
  - `PLAIN_TERMS` covers the families above plus 12운성 multi-syllable names, 중화, 반합·충·형·파·해 phrases as multi-syllable keys ("충살" not needed), and the 12 신살 names in `depth.SINSAL_KO`. Gloss copy is the implementer's, except the three pinned above.
  - Counting uses one regex alternation, longest term first.
  - Terms in `_AMBIGUOUS = {"인성", "지지", "관대", "신약", "정화", "해수", "계수", "장생", "제왕", "자수", "사화", "중화"}` are glossed but never counted.
  - "상관" counts only when not followed by 없·있·하·이 없·이 있. "비견" counts only when not followed by 되·하·할.
  - Single-syllable keys are never counted.
  - "자수" and "지지" in the test sentence are ambiguous and not counted; that is intended.

- [ ] **Step 4: Run** the same command → PASS.

- [ ] **Step 5: Commit** `feat(plain): plain-language lexicon and jargon counter`.

### Task 2: rules-v6 style rules and validation for all modes

**Files:**
- Modify: `src/fateweave/config.py` (RULE_VERSION), `src/fateweave/domain/guide.py`, `src/fateweave/domain/validation.py`, `src/fateweave/mcp/server.py` (WORKFLOW_KO bullet)
- Modify tests that pin "rules-v5": `tests/unit/test_config.py`, `tests/unit/test_rules.py`, `tests/integration/test_analysis.py`, `tests/integration/test_reports.py`
- Test: `tests/unit/test_plain_validation.py`

**Interfaces:**
- Consumes: `plain.PLAIN_TERMS`, `plain.jargon_terms`, `plain.jargon_limit`.
- Produces:
  - `guide.rule_version_number(version: str) -> int` (`"rules-v6"` → 6).
  - `guide.PLAIN_MAX_HANJA_RATIO = 0.01`.
  - `guide.JARGON_EXEMPT: dict[str, frozenset[str]] = {"individual": frozenset({"evidence_explanation"})}`.
  - `writing_guide(mode)["plain_terms"]` (dict copy of `PLAIN_TERMS`).

- [ ] **Step 1: Write the failing tests** (`test_plain_validation.py`). Build a rules-v6 individual run the way `tests/unit/test_validation.py::_prepared` does (synthetic 1990-01-01 16:30 male), with `rule_version="rules-v6"` and the full individual sections at min length.

```python
def test_jargon_heavy_section_rejected(run_v6):
    text = "천간 무토가 상관이라 말이 앞선다. " * 40  # ~3 terms per 18 chars
    assert codes(check(run_v6, {"personality": text})) == ["JARGON_HEAVY"]

def test_plain_section_passes(run_v6):
    text = "겉으로 드러나는 기운이 틀을 깨는 표현력과 말솜씨라서 말이 먼저 나간다. " * 20
    assert codes(check(run_v6, {"personality": text})) == []

def test_evidence_explanation_is_exempt(run_v6):
    text = "천간 무토가 상관, 지지 자수가 편관. " * 20
    assert codes(check(run_v6, {"evidence_explanation": text})) == []

def test_hanja_limit_is_one_percent(run_v6):
    text = "가" * 980 + "甲" * 20   # 2%
    assert "HANJA_HEAVY" in codes(check(run_v6, {"personality": text}))

def test_rules_v5_run_keeps_old_checks(run_v6):
    old = run_v6.model_copy(update={"rule_version": "rules-v5"})
    text = "천간 무토가 상관이라 말이 앞선다. " * 40
    assert codes(check(old, {"personality": text})) == []

def test_guide_carries_plain_terms():
    for mode in ("individual", "couple"):
        g = writing_guide(mode)
        assert g["plain_terms"]["상관"] == "틀을 깨는 표현력·말솜씨"
        assert any("plain_terms" in r for r in g["style_rules"])
```

`check(run, overrides)` replaces the named sections (keeping the others at min length) and returns `validate_report(...)`. The anchor claim is the SEWOON computed claim, as in `test_validation.py`.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_plain_validation.py -v` → FAIL.

- [ ] **Step 3: Implement.**
  - `config.RULE_VERSION = "rules-v6"`.
  - In `guide.STYLE_RULES`, replace the first rule (hangul notation examples) and the third rule ("명리 용어를 쓰면 바로 뒤에 … 풀어 준다") with:
    - "명리 용어는 쓰지 않고 writing_guide.plain_terms의 뜻으로 쓴다. '천간 무토가 상관이라'처럼 용어를 이어 붙이지 않는다. 꼭 필요하면 섹션당 한두 번, 쉬운 말 뒤 괄호로만. 섹션 300자당 1개를 넘으면 JARGON_HEAVY."
    - "본문에 한자를 쓰지 않는다(claim의 computed_values는 예외). 섹션 한자 1% 초과는 HANJA_HEAVY."
  - In `validation._check_depth(draft, rule_version)`:
    - Use the hanja ratio `PLAIN_MAX_HANJA_RATIO` when `rule_version_number(rule_version) >= 6`, else `MAX_HANJA_RATIO`.
    - From v6, add `JARGON_HEAVY` for every section not in `JARGON_EXEMPT.get(report_type, ())`. The message lists up to 5 found terms and their `PLAIN_TERMS` glosses; the path is `sections.<key>`.
  - WORKFLOW_KO: replace "본문은 한글로 쓴다 (예: 을미 일주, 정재, 도화살). 명리 용어는 일상 언어로 풀어 쓴다." with the plain-language rule, naming `plain_terms` and `JARGON_HEAVY`.
  - Bump "rules-v5" → "rules-v6" in the four test files listed.

- [ ] **Step 4: Run** `uv run ruff check . && TEST_DATABASE_URL=... uv run pytest -q tests` → all PASS (the integration filler text "전통 명리 해석 문장." contains no counted term).

- [ ] **Step 5: Commit** `feat(validation): rules-v6 plain-language style rules (JARGON_HEAVY, 1% hanja)`. Open PR 1.

## PR 2 — General evidence rules

### Task 3: Shared evidence builder and TEN_GOD_DISTRIBUTION

**Files:**
- Modify: `src/fateweave/domain/rules.py` (extract builder)
- Create: `src/fateweave/domain/general.py`
- Test: `tests/unit/test_general_evidence.py`

**Interfaces:**
- Produces:
  - `rules.build_evidence(chart, subject_key, rules: Mapping[str, Callable[[ChartSnapshot], list[_Draft]]], order: tuple[str, ...]) -> list[Evidence]`. `build_individual_evidence` becomes a call to it with `RULES, RULE_ORDER`.
  - `general.ten_god_distribution(chart) -> dict` with keys `known_positions: list[str]`, `groups: dict[group, {"surface": int, "hidden": float, "weight": float, "level": str, "ten_gods": dict[str, int]}]`, `dominant: list[str]`, `missing: list[str]`.
  - Level codes are `"none" | "weak" | "normal" | "strong" | "unconfirmed"`, with `LEVEL_KO = {"none": "없음", "weak": "약", "normal": "보통", "strong": "강", "unconfirmed": "확인 불가"}`.
  - `general.GROUP_ORDER = ("比劫", "食傷", "財星", "官星", "印星")`.

- [ ] **Step 1: Write the failing tests.** Use the zi chart (1990-03-12 10:30 male, 庚午 己卯 丙子 癸巳; same helper as `tests/unit/test_couple.py::chart`) and pure snapshots made with `model_copy(update={...pillars})`.

```python
def test_individual_catalog_unchanged(zi):
    assert [e.id for e in build_individual_evidence(zi, "self")] == [
        e.id for e in rules.build_evidence(zi, "self", rules.RULES, rules.RULE_ORDER)]

def test_distribution_known_hour(zi):
    d = ten_god_distribution(zi)
    assert {g: v["surface"] for g, v in d["groups"].items()} == {
        "比劫": 2, "食傷": 1, "財星": 1, "官星": 2, "印星": 1}
    assert {g: v["hidden"] for g, v in d["groups"].items()} == pytest.approx(
        {"比劫": 0.3, "食傷": 0.9, "財星": 0.6, "官星": 0.3, "印星": 0.3})
    assert {g: v["level"] for g, v in d["groups"].items()} == {
        "比劫": "normal", "食傷": "weak", "財星": "weak", "官星": "normal", "印星": "weak"}
    assert d["dominant"] == ["比劫", "官星"] and d["missing"] == []

def test_missing_group_is_none_with_hour_and_unconfirmed_without(zi):
    full = zi.model_copy(update={"year_pillar": "甲子", "month_pillar": "甲子",
                                 "day_pillar": "甲子", "hour_pillar": "甲子"})
    d = ten_god_distribution(full)
    assert d["missing"] == ["食傷", "財星", "官星"] and d["groups"]["食傷"]["level"] == "none"
    assert d["groups"]["比劫"]["level"] == "strong" and d["groups"]["印星"]["level"] == "strong"
    no_hour = full.model_copy(update={"hour_pillar": None})
    d2 = ten_god_distribution(no_hour)
    assert d2["missing"] == [] and d2["groups"]["食傷"]["level"] == "unconfirmed"
    assert d2["known_positions"] == ["year", "month", "day"]

def test_unknown_hour_scales_thresholds():
    # zi without hour (1990-03-12, time unknown): 庚午 己卯 丙子; weights 比劫/官星/印星 1.15,
    # 食傷 1.3, 財星 1.0; thresholds x5/7 (weak < 1.071, normal < 2.143).
    d = ten_god_distribution(chart("1990-03-12", None, "male"))
    assert {g: v["level"] for g, v in d["groups"].items()} == {
        "比劫": "normal", "食傷": "normal", "財星": "weak", "官星": "normal", "印星": "normal"}
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_general_evidence.py -v` → FAIL.

- [ ] **Step 3: Implement.**
  - **Surface:** the stems of the known non-day positions plus each known branch's 本氣. Ten gods come from `t.ten_god` and `t.branch_ten_god` on `chart.day_pillar[0]`.
  - **Hidden:** the 中氣 (0.6) and 餘氣 (0.3) of each known branch, from `t.hidden_stems`.
  - **Weight:** `surface + 0.5 * hidden`, rounded to 3 decimals.
  - **Level thresholds:** 0 → none, < 1.5 → weak, < 3 → normal, otherwise strong. Multiply the thresholds by `surface_total / 7`, where surface_total is 7 with the hour and 5 without.
  - **Zero weight without the hour:** `unconfirmed`, not none.
  - **Dominant:** groups with level strong. If none is strong, every group tied at the maximum weight, in `GROUP_ORDER`.
  - **Missing:** groups with level none.
  - **Rule:** `TEN_GOD_DISTRIBUTION`, kind rule_derived, `depends` = known positions.
    - text_ko, e.g. "십성 분포: 비겁(나와 같은 기운·자존감) 보통, 식상(표현력·재능 발산) 약, …". Each group gets its `PLAIN_TERMS` gloss.
    - The assumption names the thresholds as Fateweave design hypotheses.
  - **Scaffold in `general.py`:**
    - `GENERAL_RULES` dict and `GENERAL_RULE_ORDER`: the individual `RULE_ORDER` minus `MARRIAGE_TIMING_RULES = ("DAEWOON_FLOW", "YEAR_TIMING", "MONTH_TIMING", "LIFE_TIMING")`, plus the new rules appended in this order: TEN_GOD_DISTRIBUTION, PALACES, KINSHIP, APTITUDE_CUES, LUCK_FLOW, YEAR_FLOW.
    - Add each new rule to the dict as its task lands.
    - `build_general_evidence(chart, subject_key="self")` calls `rules.build_evidence(...)` with `GENERAL_RULES` and `GENERAL_RULE_ORDER`.

- [ ] **Step 4: Run** the test file and `tests/unit` → PASS.
- [ ] **Step 5: Commit** `feat(general): shared evidence builder and TEN_GOD_DISTRIBUTION`.

### Task 4: PALACES and KINSHIP

**Files:** Modify `src/fateweave/domain/general.py`; Test `tests/unit/test_general_evidence.py`

**Interfaces:**
- Produces:
  - `general.PALACE = {"year": "ancestry_youth", "month": "parents_siblings_society", "day": "self_spouse", "hour": "children_later_life"}` with `PALACE_KO`.
  - `general.KINSHIP_TABLE: dict[gender, dict[relative, tuple[ten_god, ...]]]`:
    - male: mother 正印, father 偏財, siblings 比肩·劫財, spouse 正財·偏財, son 偏官, daughter 正官
    - female: mother 正印, father 偏財, siblings 比肩·劫財, spouse 正官·偏官, son 傷官, daughter 食神
  - `RELATIVE_KO` gives the Korean names.
  - `general.kinship(chart) -> list[dict]`. Each entry is `{"relative", "ten_gods", "found": [{"position": "<pos>_<stem|branch|hidden>", "ten_god"}], "count": int, "status": "found" | "none" | "unconfirmed"}`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_palaces_known_and_unknown_hour(zi):
    items = by_rule(build_general_evidence(zi), "PALACES")
    assert [e.operands["palace"] for e in items] == [
        "ancestry_youth", "parents_siblings_society", "self_spouse", "children_later_life"]
    month = next(e for e in items if e.operands["position"] == "month")
    assert (month.operands["stem_ten_god"], month.operands["branch_ten_god"]) == ("傷官", "正印")
    no_hour = by_rule(build_general_evidence(chart("1990-03-12", None, "male")), "PALACES")
    assert no_hour[-1].operands == {"position": "hour", "palace": "children_later_life", "status": "unknown"}

def test_kinship_found_none_unconfirmed(zi):
    full = zi.model_copy(update={"year_pillar": "甲子", "month_pillar": "甲子",
                                 "day_pillar": "甲子", "hour_pillar": "甲子"})
    k = {e["relative"]: e for e in kinship(full)}
    assert k["mother"]["status"] == "found" and k["mother"]["count"] == 4
    assert k["father"]["status"] == "none"
    k2 = {e["relative"]: e for e in kinship(full.model_copy(update={"hour_pillar": None}))}
    assert k2["father"]["status"] == "unconfirmed" and k2["son"]["status"] == "unconfirmed"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
  - **PALACES:** one rule_derived item per known position, operands `{"position", "palace", "pillar", "stem_ten_god", "branch_ten_god", "stage"}`.
    - The day position has `stem_ten_god = None`, because it is the self.
    - `stage` comes from `t.twelve_stage`.
    - When the hour is unknown, add one item `{"position": "hour", "palace": "children_later_life", "status": "unknown"}` whose text says the hour is unknown and the palace is not read.
  - **KINSHIP:**
    - **Counting:** `count` is the number of surface hits. Hidden hits are listed in `found` with an `_hidden` position but not counted.
    - **Status:** with no hit at all, status is `none` when the hour is known and `unconfirmed` when it is not.
    - **Item:** one rule_derived item per relative, in table order.
    - **text_ko:** uses the plain gloss of the star. For unconfirmed relatives it says "시주 미상으로 확인 불가".
    - **Assumption:** names the father = 偏財 convention and the school difference.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(general): PALACES and KINSHIP evidence`.

### Task 5: APTITUDE_CUES

**Files:** Modify `src/fateweave/domain/general.py`; Test `tests/unit/test_general_evidence.py`

**Interfaces:**
- Consumes: `ten_god_distribution`, `depth.special_structures`, `depth.sinsal`, `GyeokgukCalculator` (via `depth.library_saju`).
- Produces:
  - `general.CATEGORY = {"比劫": "independent_competitive", "食傷": "expressive_technical", "財星": "business_management", "官星": "organization_public", "印星": "scholarly_educational"}`, with `CATEGORY_KO = {"독립·경쟁형", "표현·전문기술형", "사업·관리형", "조직·공직형", "학문·교육형"}` in the same order.
  - `general.aptitude(chart) -> dict` with keys `basis: "special_structure" | "gyeokguk" | "dominant"`, `groups: list[str]` (1–2), `categories: list[str]`, `gyeokguk: str | None`, `special_structure: str | None`, `alternative: dict | None` (same shape minus `alternative`), `sinsal: list[str]`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_aptitude_follows_gyeokguk_and_dominant(zi):
    a = aptitude(zi)
    assert a["basis"] == "gyeokguk" and a["gyeokguk"] == GyeokgukCalculator.determine(
        depth.library_saju(zi)).gyeokguk.hanja
    assert 1 <= len(a["groups"]) <= 2 and a["categories"] == [CATEGORY[g] for g in a["groups"]]

def test_aptitude_follows_special_structure(monkeypatch, zi):
    monkeypatch.setattr(depth, "special_structures", lambda c: {"checked": 16, "accepted": [
        {"type": "從財格", "name_ko": "종재격", "verdict": "GENUINE", "score": 80}]})
    a = aptitude(zi)
    assert (a["basis"], a["groups"], a["special_structure"]) == ("special_structure", ["財星"], "從財格")
    assert a["alternative"]["basis"] == "gyeokguk"

def test_aptitude_without_hour_uses_dominant():
    a = aptitude(chart("1990-03-12", None, "male"))
    assert a["basis"] == "dominant" and a["gyeokguk"] is None
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
  - **Group maps:**
    - `SPECIAL_GROUP`: 從旺格·從強格·曲直格·炎上格·稼穡格·從革格·潤下格 → 比劫; 從財格 → 財星; 從官殺格 → 官星; 從兒格 → 食傷. 合化 and 兩神成象 have no group.
    - `GYEOKGUK_GROUP`: 食神格·傷官格 → 食傷; 偏財格·正財格 → 財星; 偏官格·正官格 → 官星; 偏印格·正印格 → 印星; 建祿格·羊刃格 → 比劫. 地支合化格 has no group.
  - **Choosing the basis:**
    1. Take the highest-score accepted special structure that has a group. It becomes the basis, and the alternative is the gyeokguk/dominant result.
    2. Otherwise, if the hour is known and the gyeokguk maps to a group, use `unique([that group, *dominant])[:2]`.
    3. Otherwise use `dominant[:2]`.
  - **sinsal:** the names present from `("驛馬", "華蓋", "天乙貴人", "魁罡", "羊刃")`.
  - **Rule:** `APTITUDE_CUES` (rule_derived). The assumption says this is a school-dependent traditional classification.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(general): APTITUDE_CUES evidence`.

### Task 6: LUCK_FLOW, YEAR_FLOW and the full general catalog

**Files:** Modify `src/fateweave/domain/general.py`; Test `tests/unit/test_general_evidence.py`

**Interfaces:**
- Consumes: `timing.natal_relations(chart, pillar)`, `timing.daewoon_timeline(chart, year)`, `timing.DAEWOON_UNAVAILABLE`, `depth.favorable_elements(chart)`.
- Produces: `build_general_evidence(chart, subject_key="self") -> list[Evidence]`, sorted by `rules.sort_key(GENERAL_RULE_ORDER)`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_luck_and_year_flow(zi):
    ev = build_general_evidence(zi)
    luck = by_rule(ev, "LUCK_FLOW")
    assert len(luck) == len(zi.daewoon.entries)
    first = luck[0].operands
    assert set(first) >= {"index", "start_age", "end_age", "pillar", "stem_ten_god",
                          "branch_ten_god", "groups", "relations", "favorable_match"}
    assert first["end_age"] == first["start_age"] + 9
    years = by_rule(ev, "YEAR_FLOW")
    assert [e.operands["year"] for e in years] == [s.year for s in zi.sewoon]
    assert all("signal" not in e.operands and "rank" not in e.operands for e in years)

def test_general_catalog_has_no_marriage_timing(zi):
    codes = {e.rule_code for e in build_general_evidence(zi)}
    assert not codes & {"DAEWOON_FLOW", "YEAR_TIMING", "MONTH_TIMING", "LIFE_TIMING"}
    assert {"SPOUSE_PALACE", "SPOUSE_STAR", "TEN_GOD_DISTRIBUTION", "PALACES", "KINSHIP",
            "APTITUDE_CUES", "LUCK_FLOW", "YEAR_FLOW"} <= codes

def test_partial_chart_flags_boundary(zi):   # Review Focus 4
    alt = PillarAlternative(year_pillar="辛未", month_pillar=zi.month_pillar,
                            day_pillar=zi.day_pillar, hour_pillar=zi.hour_pillar,
                            reasons=["SOLAR_TERM"], local_windows=[])
    snap = zi.model_copy(update={"alternatives": [alt], "certainty": "PARTIAL"})
    ev = build_general_evidence(snap)
    for rule in ("TEN_GOD_DISTRIBUTION", "APTITUDE_CUES", "LUCK_FLOW"):
        assert rules.BOUNDARY_ASSUMPTION in by_rule(ev, rule)[0].assumptions
    year_palace = next(e for e in by_rule(ev, "PALACES") if e.operands["position"] == "year")
    day_palace = next(e for e in by_rule(ev, "PALACES") if e.operands["position"] == "day")
    assert rules.BOUNDARY_ASSUMPTION in year_palace.assumptions
    assert rules.BOUNDARY_ASSUMPTION not in day_palace.assumptions

def test_new_text_has_no_hanja(zi):
    for e in build_general_evidence(zi):
        if e.rule_code in GENERAL_NEW_RULES:
            assert not has_hanja(e.text_ko), e.text_ko
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
  - **LUCK_FLOW** (one item per daewoon entry, `depends` = known positions): operands `{"index", "start_age", "end_age", "pillar", "stem_ten_god", "branch_ten_god", "groups": [stem_group, branch_group], "relations", "favorable_match"}`.
    - `favorable_match` is the sorted elements of the pillar's stem and branch that are in `favorable_elements`.
    - The assumptions reuse `rules._daewoon_assumptions`.
  - **YEAR_FLOW** (one item per `chart.sewoon` entry): operands `{"year", "year_pillar", "stem_ten_god", "branch_ten_god", "groups", "relations", "daewoon", "daewoon_relations", "favorable_match"}`.
    - `daewoon_relations` lists `{"daewoon", "relation", "name"}`, from `t.pair_relations` (branches) and `t.stem_relations` (stems) between the year pillar and each available daewoon pillar.
  - Export `GENERAL_NEW_RULES` (the six new codes).
  - The text_ko of the six rules uses plain glosses, with no hanja (`hangul()` for pillars).
- [ ] **Step 4: Run** `uv run ruff check . && uv run pytest -q tests/unit` → PASS.
- [ ] **Step 5: Commit** `feat(general): LUCK_FLOW, YEAR_FLOW and build_general_evidence`. Open PR 2.

## PR 3 — The `general` mode

### Task 7: Mode `general` in models and storage (Alembic 0002)

**Files:**
- Create: `alembic/versions/0002_general_mode.py` (revision "0002", down_revision "0001")
- Modify: `src/fateweave/storage/tables.py:48`, `src/fateweave/models/facts.py:128`, `src/fateweave/models/reports.py:33`
- Test: `tests/integration/test_storage.py`

**Interfaces:**
- Produces: `Mode = Literal["individual", "couple", "general"]` in `models/facts.py`. Use it for `PreparedAnalysis.mode`, `ReportDraft.report_type` and every later Literal.

- [ ] **Step 1: Write the failing tests** in `test_storage.py`:
  - `test_mode_constraint_accepts_general_rejects_other`: inserting an `analysis_runs` row with mode `general` succeeds, and mode `other` raises `IntegrityError`. Use the same insert path as `test_update_run_status_and_list_reports`.
  - `test_migration_0002_round_trip`: on a fresh scratch database (create and drop it like `conftest.py`'s session fixture), run upgrade head, insert a general row, then downgrade to "0001". The downgrade raises. Delete the row; the downgrade now succeeds, and upgrade head succeeds again.
- [ ] **Step 2: Run** `TEST_DATABASE_URL=... uv run pytest tests/integration/test_storage.py -v` → FAIL.
- [ ] **Step 3: Implement.**
  - Upgrade: drop `ck_analysis_runs_mode` and recreate it as `mode IN ('individual','couple','general')`.
  - Downgrade: recreate the two-value constraint. It fails naturally while general rows exist.
  - Mirror the constraint in `tables.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(storage): allow analysis mode general (alembic 0002)`.

### Task 8: General sections, writing guide and validation

**Files:** Modify `src/fateweave/domain/guide.py`, `src/fateweave/domain/validation.py`; Test `tests/unit/test_general_validation.py`

**Interfaces:**
- Consumes: `build_general_evidence` (Task 6), `Mode` (Task 7).
- Produces:
  - `guide.GENERAL` sections, in order:

    | key | title | min | target |
    |---|---|---|---|
    | summary | 핵심 요약 | 300 | 600 |
    | temperament | 타고난 성향과 기질 | 1000 | 1800 |
    | career | 직업과 적성 | 1000 | 1800 |
    | wealth | 재물운 | 500 | 1000 |
    | health | 건강 체질 | 400 | 800 |
    | family_relations | 인간관계와 가족 | 1000 | 1800 |
    | life_flow | 대운으로 본 인생 흐름 | 800 | 1500 |
    | year_flow | 올해와 가까운 몇 년 | 600 | 1200 |

    The `covers` text is from spec §5.
  - `SECTIONS["general"] = GENERAL`, `TIMING_RULES["general"] = "LUCK_FLOW"`.
  - `GENERAL_REQUIRED_CITATIONS = (("TEN_GOD_DISTRIBUTION",), ("APTITUDE_CUES",), ("KINSHIP", "PALACES"), ("LUCK_FLOW",))`.
  - `GENERAL_STYLE_RULES` covers spec §7 general: strengthened sections go 기운 → 일상 → 장단점; the health disclaimer; marriage only one line pointing to the marriage report, with no marriage years; limits go in caveats.
  - `HEALTH_MEDICAL_TERMS` regex.

- [ ] **Step 1: Write the failing tests.** Build a rules-v6 general run from `build_general_evidence(zi)`, with `writing_guide("general")` and sections at min length using plain filler. The valid draft carries:
  - one interpretation claim per required rule: TEN_GOD_DISTRIBUTION, APTITUDE_CUES, KINSHIP, PALACES, LUCK_FLOW (each citing that rule's first item)
  - the anchor computed claim
  - `caveats=["전통 해석이며 출생 시각 경계에 따라 달라질 수 있다."]`
  - a health section containing "의학적 진단이 아니며 몸에 이상이 있으면 의료진과 상담하세요."

```python
# check(sections=..., drop_rule=..., caveats=..., health=..., health_extra=...) builds the valid
# draft, replaces/extends the named parts (drop_rule removes that rule's claim) and returns codes.
def test_valid_general_draft_passes(): assert codes(check()) == []
def test_required_sections(): assert required_sections("general", "rules-v6") == (
    "summary", "temperament", "career", "wealth", "health", "family_relations", "life_flow", "year_flow")
def test_short_strengthened_section(): assert codes(check(sections={"career": "짧다. " * 50})) == ["SECTION_TOO_SHORT"]
def test_missing_citation(): assert codes(check(drop_rule="APTITUDE_CUES")) == ["UNSUPPORTED_CLAIM"]
def test_kinship_or_palaces_satisfies(): assert codes(check(drop_rule="KINSHIP")) == []   # PALACES still cited
def test_missing_caveats(): assert codes(check(caveats=[])) == ["MISSING_CAVEATS"]
def test_health_disclaimer_missing(): assert codes(check(health="오행 기운이 치우쳐 쉽게 지친다. " * 30)) == ["HEALTH_DISCLAIMER_MISSING"]
def test_health_medical_claim(): assert codes(check(health_extra="고혈압을 조심하고 한약을 복용하면 좋다.")) == ["HEALTH_MEDICAL_CLAIM"]
def test_disclaimer_sentence_may_name_treatment():   # Review Focus 5
    assert codes(check(health_extra="이 내용은 질환을 진단하거나 치료하는 것이 아니다.")) == []
def test_guide_general():
    g = writing_guide("general")
    assert g["required_timing_rule"] == "LUCK_FLOW" and "plain_terms" in g
    assert g["required_citations"] == [list(x) for x in GENERAL_REQUIRED_CITATIONS]
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_general_validation.py -v` → FAIL.
- [ ] **Step 3: Implement.** In `validate_report`, when `run.mode == "general"` and the rule version is ≥ 6:
  - **Citations:** for each citation group, require at least one claim citing evidence of one of its rule codes (any kind); otherwise `UNSUPPORTED_CLAIM` (path "claims").
  - **Caveats:** if every caveat is blank → `MISSING_CAVEATS` (path "caveats").
  - **Health disclaimer:** `health` must contain both `진단` and one of `의료|병원|전문의`; otherwise `HEALTH_DISCLAIMER_MISSING`.
  - **Medical claims:** split `health` into sentences the same way `_check_candidate_years` does. Skip sentences containing `진단`. Any other sentence matching `HEALTH_MEDICAL_TERMS` → `HEALTH_MEDICAL_CLAIM`. The terms are 고혈압, 저혈압, 당뇨, 우울증, 불면증, 갑상선, 디스크, 관절염, 위염, 간염, 폐렴, 천식, 비염, 아토피, 치매, 뇌졸중, 심근경색, 협심증, 종양, 질환, 처방, 복용, 수술, 약물, 한약, 영양제.
  - `section_labels()` picks up the new titles automatically. The keys don't collide, apart from the shared summary.
- [ ] **Step 4: Run** → PASS, plus `tests/unit`.
- [ ] **Step 5: Commit** `feat(guide): general sections, writing guide and validation rules`.

### Task 9: Service, reports and MCP for `general`

**Files:** Modify `src/fateweave/services/analysis.py`, `src/fateweave/domain/assessments.py` (`scoring_versions`), `src/fateweave/services/reports.py`, `src/fateweave/mcp/server.py`; Test `tests/integration/test_analysis.py`, `tests/integration/test_e2e_flow.py`, `tests/integration/helpers.py`, `tests/integration/test_mcp.py`

**Interfaces:**
- Consumes: `build_general_evidence`, `Mode`, `SECTIONS["general"]`, `GENERAL_REQUIRED_CITATIONS`.
- Produces:
  - `prepare_analysis("general", [profile])` → facts keyed `self`, the general catalog, `assessments == {}`, `scoring_versions == {}`.
  - The title is "종합 사주 리포트".
  - `list_reports(mode="general")` filters general reports.

- [ ] **Step 1: Write the failing tests.**
  - `test_prepare_general_persists_one_participant`: mode general with 1 profile.
    - The catalog has no marriage-timing rules and includes `TEN_GOD_DISTRIBUTION`.
    - `scoring_versions == {}`, and the run row mode is `general`.
    - Two profiles → `INVALID_INPUT`.
  - `test_general_complete_without_external_llm` in `test_e2e_flow.py`:
    - `run_deterministic_e2e(engine, "general", [profile])` finalizes.
    - Markdown starts with "# 종합 사주 리포트", and the section headings follow the §5 order.
  - `helpers.valid_draft` adds, for general runs: one claim per `GENERAL_REQUIRED_CITATIONS` group, a caveat, and the health disclaimer sentence in `health`.
  - `test_mcp.py`:
    - the prepare tool schema accepts mode `general`
    - `list_reports` accepts mode `general`
    - the server instructions contain "general 필수 sections" and the cross-offer sentence "종합 사주"
- [ ] **Step 2: Run** `TEST_DATABASE_URL=... uv run pytest tests/integration -q` → FAIL.
- [ ] **Step 3: Implement.**
  - **analysis.py:**
    - `_EXPECTED_PROFILES["general"] = 1`.
    - Use keys `["self"]` for modes other than couple.
    - The general branch calls `build_general_evidence(charts[0], "self")`.
  - **`scoring_versions(mode)`:** returns `{}` for general.
  - **reports.py:** add `_TITLES["general"] = "종합 사주 리포트"` and accept general in `list_reports`.
  - **server.py:** use `Mode` in both Literals. In WORKFLOW_KO:
    - Add the `general` required sections line.
    - Add a general bullet: plain-language strengthened sections, required citations, caveats, the health disclaimer, no marriage years.
    - In step 4, add: "individual 리포트가 FINALIZED되면, 같은 생년월일로 종합 사주(mode `general`)도 볼지 사용자에게 한 번 제안한다."
- [ ] **Step 4: Run** `uv run ruff check . && TEST_DATABASE_URL=... uv run pytest -q tests` → all PASS.
- [ ] **Step 5: Commit** `feat(general): general mode through service, reports and MCP`.

### Task 10: Docs and release check

**Files:** Modify `README.md` (rules section: rules-v6, the general mode, plain-language rules), `docs/superpowers/specs/2026-11-26-general-saju-report-design.md` (status: 구현 완료 after merge).

- [ ] **Step 1:** Update the README rules section, and add a "종합 사주 (general)" bullet listing the eight sections and the new evidence.
- [ ] **Step 2: Run** `uv run ruff check . && TEST_DATABASE_URL=... uv run pytest -q tests` → PASS.
- [ ] **Step 3: Commit** `docs: general report and plain-language rules`. Open PR 3. After merge, confirm that the Deploy run shows "alembic upgrade" with no error and that "connector URL ok" is logged.
