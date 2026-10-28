# Build from the repo root:  docker build -f deploy/Dockerfile -t fateweave-api .
FROM python:3.12-slim AS builder
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
RUN pip install --no-cache-dir uv==0.6.10
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Dependencies only, exactly as pinned in uv.lock. The app itself runs from src/ via PYTHONPATH.
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/src
RUN groupadd --system --gid 10001 fateweave \
    && useradd --system --uid 10001 --gid fateweave --no-create-home --shell /usr/sbin/nologin fateweave
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini pyproject.toml uv.lock ./
# Readable by the runtime user whatever the build host's file modes were.
RUN chmod -R a+rX /app/src /app/alembic /app/alembic.ini
USER fateweave
EXPOSE 8080
CMD ["python", "-m", "fateweave"]
