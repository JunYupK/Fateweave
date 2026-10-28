# Fateweave

Remote MCP server for marriage saju and couple compatibility reports.
결혼 사주 및 커플 궁합 리포트를 제공하는 원격 MCP 서버.

## Dev / 개발

```bash
uv sync                      # install deps / 의존성 설치
cp .env.example .env         # fill in values / 값 채우기
uv run pytest -q             # tests / 테스트
uv run ruff check .          # lint
uv run uvicorn fateweave.api:app --reload   # run app / 앱 실행
```

Env vars / 환경변수: `FATEWEAVE_DATABASE_URL`, `FATEWEAVE_MCP_KEY`, `FATEWEAVE_PUBLIC_HOST`.

## 계산 정책 manse-v1 / Calculation policy

- KST 표준 자오선 135°E. 출생지 경도 보정 `KST + (경도 − 135) × 4분` (서울 126.9784°E = −32.09분). 균시차는 적용하지 않는다(지방평균태양시).
- 야자시 분리 (`yaja_si_separated=True`): 23:00–24:00(보정 시각)은 당일 일주.
- 예: 1990-01-01 09:00 서울 → 08:27:55 → **壬辰시**. 서울의 辰/巳 경계는 09:32:05 KST(09:35 → 癸巳). korean-saju README 예제의 癸巳는 보정 전 값이다(라이브러리 0.3.0 코드는 보정을 적용함).
- 출생시간 미상: `hour_pillar = null`이며 임의 시각을 확정 결과로 저장하지 않는다. 그 날짜 전체를 검토해 자정·절기 경계로 연·월·일주가 달라질 수 있으면 `PARTIAL` + 대안 명식 + `BOUNDARY_REVIEW_REQUIRED` 경고를 낸다.
- 독립 검증 근거와 출처: `tests/fixtures/verified_manse_cases.json`.

## 해석 규칙 rules-v2 / Interpretation rules

- 근거(evidence)의 `operands`는 한자(검증·ID용), `text_ko`는 한글. claim의 `computed_values`는 한자·한글 표기 모두 허용.
- 개인: 사주 네 기둥·십성·지장간·12운성(화토동법), 배우자궁·배우자성(남 재성, 여 관성), 표면/지장간 오행, 신강약(korean-saju 10점제, 시 미상이면 아는 8점을 10점으로 환산), 억부·조후 용신 *후보*, 지지 합충형파해·원진·귀문, 천간합충, 신살(도화·역마·화개·홍염·천을귀인·양인·고신·과숙·백호·괴강·고란·음양차착), 공망, 격국.
- 결혼 시기(`domain/timing.py`): `DAEWOON_FLOW`(대운별 십성·원국 관계·단서), `YEAR_TIMING`(연도별 단서·주의·순위), `MONTH_TIMING`(상위 3개 연도의 월별 단서). 단서는 배우자성, 일간합, 배우자궁 육합·삼합, 도화·홍염, 대운 배우자성 등 전통 규칙에 이름을 붙인 것이며 예측이 아니다. 순위는 핵심 단서 개수 순서일 뿐 가능성이 아니다.
- 커플: 일간 오행 관계, 서로의 배우자성 여부, 오행 보완, `COUPLE_TIMING`(연도별 두 사람 단서와 공동 순위), 대운 겹침.
- 리포트(`domain/guide.py`): 섹션별 다룰 내용과 최소 분량을 `prepare_analysis` 응답의 `writing_guide`로 내려주고, 검증에서 `SECTION_TOO_SHORT`·`HANJA_HEAVY`(섹션 한자 5% 초과)·timing claim 누락을 거절한다. rules-v1로 준비된 분석은 기존 8개(커플 6개) 섹션 규칙을 그대로 쓴다.
- 신살표는 학파별 이견이 있는 경우 한국 만세력 앱에서 흔한 쪽을 쓰고 assumptions에 이견을 적는다 (예: 홍염 乙→午, 괴강에서 戊辰 제외). korean-saju 0.3.0의 신살 모듈은 원진·귀문을 같은 표로 계산하는 문제가 있어 쓰지 않는다.

## Running integration tests

Storage tests need a disposable PostgreSQL. They read `TEST_DATABASE_URL` only (never `FATEWEAVE_DATABASE_URL`) and skip when it is unset. Each session creates and drops its own `fateweave_test_<random>` database via Alembic.

```bash
docker run -d --rm --name fateweave-test-pg -e POSTGRES_PASSWORD=test \
  -p 127.0.0.1:55432:5432 postgres:16-alpine
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@127.0.0.1:55432/postgres
uv run pytest tests/integration -v
docker stop fateweave-test-pg
```

Migrations: `FATEWEAVE_DATABASE_URL=postgresql+asyncpg://... uv run alembic upgrade head` (or `alembic -x url=...`).
URL precedence: a programmatic `config.attributes["url"]` (tests), then `-x url=...`, then `FATEWEAVE_DATABASE_URL`.
An explicit `-x url` always wins over an exported `FATEWEAVE_DATABASE_URL`, so `alembic -x url=<scratch> downgrade base`
never touches the database in your environment.

## Deployment (existing OCI VM) / 배포

Files live in `deploy/`; live acceptance checks are in `scripts/acceptance.md`. Fateweave runs as one
container (`fateweave-api`, compose project `fateweave`) next to existing services. It uses the
existing PostgreSQL instance (no Postgres service in compose), no shared Docker networks, and
publishes only `127.0.0.1:8080`; host Nginx terminates TLS.

1. **Database (DBA, once):** `psql -X -v ON_ERROR_STOP=1 -v owner_pw=... -v app_pw=... -d postgres -f deploy/postgres-init.sql`
   creates `fateweave_owner` (migrations + admin purge) and `fateweave_app` (runtime, DML only; no DELETE,
   and no UPDATE on `report_versions`/`alternative_interpretations`). Run it again after the first migration.
   The immutability triggers can be bypassed by any role that can `SET fateweave.maintenance`, so the missing
   UPDATE/DELETE grants are what protect report records from the app role.
2. **Secrets:** create `/etc/fateweave/fateweave.env` (root:root, mode 600, never committed) with the names in
   `.env.example`. `FATEWEAVE_DATABASE_URL` uses the `fateweave_app` role; if PostgreSQL is on the VM host use
   `host.docker.internal` as its host (compose maps it with `host-gateway`). Set `FATEWEAVE_ENV_FILE` to use another path.
   Do not paste `docker compose config` output anywhere: it inlines the env file. Validate with `config -q`.
3. **Build and migrate** (migrations use the owner URL, passed from your shell environment, not argv):
   ```bash
   export FATEWEAVE_DATABASE_URL='postgresql+asyncpg://fateweave_owner:...@host.docker.internal:5432/fateweave'
   docker compose -p fateweave -f deploy/compose.fateweave.yaml build
   docker compose -p fateweave -f deploy/compose.fateweave.yaml run --rm -e FATEWEAVE_DATABASE_URL fateweave-api alembic upgrade head
   unset FATEWEAVE_DATABASE_URL
   docker compose -p fateweave -f deploy/compose.fateweave.yaml up -d
   ```
4. **Nginx:** render `deploy/nginx-fateweave.conf` with `envsubst '${FATEWEAVE_PUBLIC_HOST}'`, set real certificate paths
   (reuse an existing cert only if its SANs cover the host), `nginx -t && nginx -s reload`. The vhost logs without
   request headers, proxies exactly `/mcp` and `/healthz` (no `/mcp/` redirect), and 404s everything else. uvicorn trusts `X-Forwarded-*` only from
   `FATEWEAVE_FORWARDED_ALLOW_IPS` (compose sets the Docker bridge range; default outside Docker is `127.0.0.1`).
5. **Data retention:** report and profile data are kept until deleted via the admin CLI. `prepare_analysis`
   stores the birth input immediately, so a PREPARED (or VALIDATION_FAILED) run that is never finalized keeps its
   participants' birth data until you purge it. Run the CLI with the owner role (`ADMIN` below stands for
   `docker compose -p fateweave -f deploy/compose.fateweave.yaml run --rm -e FATEWEAVE_DATABASE_URL fateweave-api python -m fateweave.admin`):
   1. `ADMIN list-profiles [--limit N]` prints `id  alias  created_at  runs=N`, newest first (no birth data).
   2. `ADMIN purge-profile --profile-id UUID` (dry run: impact counts and any co-participant that would be orphaned),
      then add `--confirm`. Every run naming the profile (couples included) and those runs' reports and
      alternatives are deleted. Co-participant profiles left with no remaining runs are reported as "orphaned" and
      kept; add `--include-orphans` to purge them in the same transaction.
   3. To delete everything behind one report: `ADMIN purge-report --report-id UUID [--confirm] [--include-orphans]`
      resolves the report's run to its participant profiles and purges each of them (dry run without `--confirm`).
   Each purge writes a JSON audit line (`fateweave.audit`: action, ids, counts, timestamp; no birth data or aliases).
6. **Backups:** `deploy/backup.sh` (needs `BACKUP_DIR`, optional `KEEP_DAYS`, default 14; credentials via `PGPASSFILE`/env)
   writes a `600` custom-format dump. It is not installed in cron; suggested daily entry:
   `15 3 * * * BACKUP_DIR=/var/backups/fateweave PGHOST=127.0.0.1 PGUSER=fateweave_owner PGPASSFILE=/etc/fateweave/pgpass /opt/fateweave/deploy/backup.sh`.
   Verify dumps with `deploy/restore-check.sh <dump>` (restores into a disposable DB, prints row counts only, drops it).
   `restore-check.sh` creates and drops a database, so run it as a role with CREATEDB (a DBA role or superuser),
   not `fateweave_owner` (which has no CREATEDB).
   **Encryption at rest** relies on OCI block-volume encryption (database files and dumps on the VM); Fateweave adds no
   column-level encryption. Copy backups off-host only to encrypted storage (e.g. an encrypted OCI Object Storage bucket
   or an encrypted volume), never to unencrypted media.
7. **MCP key rotation:** generate a new key, e.g. `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`
   (never put the key itself on a command line or in shell history); edit `/etc/fateweave/fateweave.env` (as root, keep mode
   600) and replace the `FATEWEAVE_MCP_KEY=` value; restart so the container reads the env file again:
   `docker compose -p fateweave -f deploy/compose.fateweave.yaml up -d --force-recreate`; then update the
   `X-Fateweave-Key` header value in the Claude connector settings. The old key stops working as soon as the container
   is recreated; check with the no-key/old-key `401` and new-key `tools/list` items in `scripts/acceptance.md`.
8. **Rollback:** app only: `git checkout <previous-tag>`, rebuild and `up -d`. Failed deploy: `docker compose -p fateweave -f deploy/compose.fateweave.yaml down`
   (other services are untouched; remove the Nginx vhost and reload to unpublish). Schema: migrations are forward-compatible
   in 0001; to revert a bad migration, restore the pre-deploy dump (take `backup.sh` before every migration) rather than
   running `alembic downgrade` on live data.

## CI/CD

- **CI** (`.github/workflows/ci.yml`, every push and PR): `ruff check`, shellcheck on `deploy/*.sh`,
  unit tests, integration tests against a PostgreSQL 16 service container (`TEST_DATABASE_URL`),
  Docker image build + import smoke test, and `compose config -q` with a dummy env file.
- **CD** (`.github/workflows/deploy.yml`): after CI succeeds on a push to `master`, or by hand
  (Actions → Deploy → Run workflow, optional commit sha). It SSHes to the VM and runs
  `sudo /opt/fateweave/deploy/deploy.sh <sha>`, which refuses commits not on `origin/master`, builds,
  takes a backup, migrates with the owner URL, restarts, waits for a healthy container, and rebuilds
  the previous commit if the health check fails (schema is not rolled back).
- **One-time setup:**
  1. VM: the repo checked out at `/opt/fateweave` (a read-only deploy key if the repo is private); a
     deploy user allowed `sudo /opt/fateweave/deploy/deploy.sh *` without a password;
     `/etc/fateweave/deploy.env` (root, mode 600) with the owner `FATEWEAVE_DATABASE_URL` and the
     backup variables (`BACKUP_DIR`, `PGHOST`, `PGUSER`, `PGPASSFILE`). See the header of `deploy/deploy.sh`.
  2. GitHub: an environment named `production` (add required reviewers to approve each deploy) with
     secrets `OCI_SSH_HOST`, `OCI_SSH_USER`, `OCI_SSH_KEY`, `OCI_SSH_KNOWN_HOSTS`
     (`ssh-keyscan -t ed25519 <host>`, verified once by hand). Until they exist the deploy job is
     skipped with a notice.

## ChatGPT handoff

Reports are generated and saved from a Claude chat through the remote MCP connector. To continue in ChatGPT (or any other assistant), call `get_report` with `format='markdown'` and paste the whole Markdown into the other chat, then ask follow-up questions about it. The Markdown carries `report_id`/`version`, the rule/manse versions, the `structured_fact_validation` scope badge and an evidence appendix, so every cited evidence ID can be looked up in the same document. Only structured computed claims are machine-checked; interpretations are traditional myeongri readings, not verified probabilities. Pasting a report shares it with that service, so do it only for reports you are comfortable sharing. The manual end-to-end checklist (real Claude chat plus ChatGPT handoff) is section C of `scripts/acceptance.md` and is pending manual (R4).
