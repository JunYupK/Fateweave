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
