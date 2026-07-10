# EventMind v2 — backend

Гексагональный модульный монолит (ports & adapters) на Python 3.12 + FastAPI
(async), SQLAlchemy 2.0 async + pgvector, Redis + arq, structlog + OpenTelemetry
+ Prometheus. Управление зависимостями — [uv](https://docs.astral.sh/uv/).

## Слои

```
src/eventmind/
├─ domain/          # чистые сущности/VO/доменные сервисы, без I/O
├─ application/     # use-case'ы + порты (репозитории, шины, gateway'и, каналы)
├─ infrastructure/  # адаптеры портов: async-SQLAlchemy, Redis, LLM, каналы, телеметрия
└─ interfaces/      # входные адаптеры: FastAPI (api), aiogram (bot), arq (worker), scheduler
```

Правило зависимостей: `interfaces → application → domain`; `infrastructure`
реализует порты `application`; `domain` наружу не импортирует (проверяет
import-linter).

## Разработка

```bash
uv sync --extra dev          # установить зависимости в .venv
uv run pytest                # unit-тесты (integration требуют Docker)
uv run ruff check .          # линт
uv run mypy src              # строгая типизация
uv run lint-imports          # границы слоёв
uv run alembic upgrade head  # миграции (нужен Postgres+pgvector)
uv run uvicorn eventmind.interfaces.api.main:app --reload
```

Полный dev-стек (Postgres+Redis+api+web+prometheus+grafana+mailhog) — через
`make up` из корня репозитория. См. `../ARCHITECTURE.md`.
