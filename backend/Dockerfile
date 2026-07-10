# EventMind v2 backend — multi-stage образ на uv.
# Один образ обслуживает все процессы (api/worker/scheduler/bot) — команда
# задаётся в compose/k8s. Слои зависимостей кэшируются отдельно от кода.

# ── builder: ставим зависимости в /app/.venv ─────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Сначала только манифесты — кэш слоя зависимостей не инвалидируется кодом.
# `--extra bot` кладёт aiogram в общий образ (bot-процесс лёгкий); `ml` (torch)
# намеренно НЕ ставим — эмбеддинги грузятся в отдельном ml-образе.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra bot

# Теперь код проекта и его установка.
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra bot

# ── runtime: только venv + код, без uv ──────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --from=builder --chown=app:app /app/alembic /app/alembic
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini

USER app
EXPOSE 8000
# Дефолтная команда — API; worker/scheduler/bot переопределяют command в compose.
CMD ["uvicorn", "eventmind.interfaces.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
