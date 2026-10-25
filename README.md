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
5. **Data retention:** report and profile data are kept until deleted via the admin CLI. Run it with the owner role:
   `docker compose -p fateweave -f deploy/compose.fateweave.yaml run --rm -e FATEWEAVE_DATABASE_URL fateweave-api python -m fateweave.admin purge-profile --profile-id UUID [--confirm]`
   (dry run without `--confirm`).
6. **Backups:** `deploy/backup.sh` (needs `BACKUP_DIR`, optional `KEEP_DAYS`, default 14; credentials via `PGPASSFILE`/env)
   writes a `600` custom-format dump. It is not installed in cron; suggested daily entry:
   `15 3 * * * BACKUP_DIR=/var/backups/fateweave PGHOST=127.0.0.1 PGUSER=fateweave_owner PGPASSFILE=/etc/fateweave/pgpass /opt/fateweave/deploy/backup.sh`.
   Verify dumps with `deploy/restore-check.sh <dump>` (restores into a disposable DB, prints row counts only, drops it).
7. **Rollback:** app only: `git checkout <previous-tag>`, rebuild and `up -d`. Failed deploy: `docker compose -p fateweave -f deploy/compose.fateweave.yaml down`
   (other services are untouched; remove the Nginx vhost and reload to unpublish). Schema: migrations are forward-compatible
   in 0001; to revert a bad migration, restore the pre-deploy dump (take `backup.sh` before every migration) rather than
   running `alembic downgrade` on live data.

## ChatGPT handoff

Reports are generated and saved from a Claude chat through the remote MCP connector. To continue in ChatGPT (or any other assistant), call `get_report` with `format='markdown'` and paste the whole Markdown into the other chat, then ask follow-up questions about it. The Markdown carries `report_id`/`version`, the rule/manse versions, the `structured_fact_validation` scope badge and an evidence appendix, so every cited evidence ID can be looked up in the same document. Only structured computed claims are machine-checked; interpretations are traditional myeongri readings, not verified probabilities. Pasting a report shares it with that service, so do it only for reports you are comfortable sharing. The manual end-to-end checklist (real Claude chat plus ChatGPT handoff) is section C of `scripts/acceptance.md` and is pending manual (R4).
