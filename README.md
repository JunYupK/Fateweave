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
