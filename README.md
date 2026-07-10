# EventMind

**EventMind** — production-grade, **аккаунт-центричная мультиканальная** система
агрегации IT-мероприятий и персональных рекомендаций. Гексагональная архитектура
(ports & adapters), async сверху донизу: FastAPI-бэкенд, Next.js-веб-клиент,
Telegram-бот (aiogram 3), очередь arq поверх Redis, PostgreSQL + pgvector, LLM
за gateway'ем и two-stage-рекомендер.

> **v2.** Проект перестроен с нуля по контракту [`docs/REBUILD_PROMPT.md`].
> Код v1 (Telegram-центричный, sync-FastAPI/APScheduler) перенесён в
> [`legacy/`](legacy/) как read-only справочник, откуда портирована доменная
> логика (математика рекомендера, LLM-промпты, парсеры источников, канонизация,
> фильтры, eval). Архитектура v1 **не** наследуется.
>
> Живой архитектурный документ — [`ARCHITECTURE.md`](ARCHITECTURE.md).
> Трекер milestone'ов и заметки для сессий — [`CLAUDE.md`](CLAUDE.md).

---

## Содержание

1. [Возможности](#возможности)
2. [Архитектура](#архитектура)
3. [Структура монорепо](#структура-монорепо)
4. [Стек](#стек)
5. [Быстрый старт (docker compose)](#быстрый-старт-docker-compose)
6. [Локальная разработка](#локальная-разработка)
7. [Проверки и тесты](#проверки-и-тесты)
8. [Offline-eval рекомендера](#offline-eval-рекомендера)
9. [Деплой (k8s/Helm)](#деплой-k8shelm)
10. [Наблюдаемость](#наблюдаемость)
11. [Статус milestone'ов](#статус-milestoneов)

---

## Возможности

- **Аккаунт-центричная модель.** Идентичность — аккаунт (email), к которому
  привязаны каналы доставки (email, Telegram, in-app). Telegram — вторичный
  клиент, а не первичный ключ.
- **Аутентификация.** Email+пароль (argon2, JWT в httpOnly-cookie, верификация
  email и сброс пароля через транзакционный outbox), **Google OAuth**, привязка
  Telegram deep-link'ом.
- **Ingestion.** Реестр источников (habr / rss / kudago) → `raw_events` →
  LLM-нормализация (structured output, enum-валидация, строгие ISO-даты) →
  `events` с идемпотентностью, ретраями и DLQ.
- **Two-stage рекомендер.** Кандидаты через pgvector kNN → взвешенный ансамбль
  скореров (rule, cosine, bayesian-Thompson, quality, hype, freshness; заделы
  skill_gap/bandit/gnn под флагами) → MMR-rerank + series anti-flood.
  Online-обучение по фидбеку (Bayesian + прогрев эмбеддинга + инвалидация кэша).
- **NL-поиск.** Фраза обычного языка → LLM извлекает `SearchFilters` →
  канонизация → строгий проход → relax-fallback.
- **Мультиканальная доставка.** Единый порт `NotificationChannel`
  (email SMTP / Telegram Bot API / in-app), дайджест (scheduler cron → queue →
  рассылка по включённым+verified каналам, гейтинг prefs/тихих часов),
  in-app инбокс, unsubscribe по подписанному токену.
- **Клиенты.** Next.js-веб (лента, поиск, карточка, инбокс, настройки) и
  Telegram-бот поверх API.

## Архитектура

Гексагональные слои, правило зависимостей `interfaces → application → domain`;
`infrastructure` реализует порты `application`; `domain` наружу не импортирует.
Границы проверяет **import-linter** в CI.

```
domain          — чистые сущности/VO/доменные сервисы (математика скоринга, таксономия). Без I/O.
application     — use-cases + порты (repos, uow, queue, cache, llm, channels, sources, oauth).
infrastructure  — async-SQLAlchemy-репо, LLM-цепочка, embeddings, arq, Redis-cache, outbox-relay,
                  NotificationChannel'ы, HTTP-клиенты источников, телеметрия.
interfaces      — FastAPI-роутеры + DI, aiogram-хендлеры (bot), arq-worker (queue+cron), CLI.
```

**Процессы** (каждый — отдельный контейнер, stateless, реплицируемый):
`api` (FastAPI) · `worker` (arq: очередь + cron) · `web` (Next.js) · `bot`
(aiogram, опц.). Хранилища: **PostgreSQL 16 + pgvector** (HNSW) и **Redis**
(очередь, кэш, локи). Надёжная публикация доменных событий — **транзакционный
outbox**.

## Структура монорепо

```
backend/    Python 3.12, uv, гексагон: src/eventmind/{domain,application,infrastructure,interfaces}
            eval/ — offline-eval harness (вне src/, tooling)
web/        Next.js 14 (App Router, standalone) — веб-клиент + BFF-прокси
deploy/     docker-compose (dev), helm/ (prod), prometheus/, grafana/, loadtest/ (k6)
legacy/     весь v1 (read-only справочник для портирования)
docs/REBUILD_PROMPT.md   контракт перестройки
ARCHITECTURE.md          живой документ (слои, процессы, обоснования, статус)
CLAUDE.md                трекер milestone'ов + заметки для будущих сессий
Makefile                 up/test/lint/typecheck/imports/migrate/seed/eval/load-test
```

## Стек

- **Backend:** Python 3.12, uv, FastAPI (async), SQLAlchemy 2.0 async + asyncpg +
  pgvector, Alembic, Pydantic v2, arq + Redis, argon2 + PyJWT, aiosmtplib + Jinja2,
  langchain-core/-google-genai/-groq (LLM Gateway), sentence-transformers (extra
  `ml`, ленивый импорт), beautifulsoup4/lxml/feedparser (парсеры), aiogram 3
  (extra `bot`), structlog + OpenTelemetry + prometheus-client.
- **Web:** Next.js 14 (App Router, standalone), TypeScript.
- **Качество:** ruff + mypy(strict) + import-linter + pytest (unit +
  integration через testcontainers) — блокирующие в CI.

## Быстрый старт (docker compose)

Нужен Docker. Из корня репозитория:

```bash
cp .env.example .env      # ключи по желанию: GOOGLE_API_KEY/GROQ_API_KEY, BOT_TOKEN, ...
make up                   # pg + redis + api + web + worker + prometheus + grafana + mailhog
```

| Сервис | URL |
|---|---|
| API (health) | http://localhost:8000/health |
| Web | http://localhost:3000 |
| Grafana | http://localhost:3001 (admin/admin) |
| Prometheus | http://localhost:9090 |
| Mailhog (dev-письма) | http://localhost:8025 |

Telegram-бот выключен по умолчанию (профиль compose): `docker compose
--profile bot up` при заданном `BOT_TOKEN`. `make down` — остановить.

## Локальная разработка

**Backend** (uv):

```bash
cd backend
uv sync --extra dev            # (+ --extra bot для бота, --extra ml для эмбеддингов)
uv run alembic upgrade head    # применить миграции к БД из DATABASE_URL
uv run uvicorn eventmind.interfaces.api.main:app --reload
```

**Web** (Node 20+):

```bash
cd web
npm install
npm run dev                    # http://localhost:3000 (BFF-прокси ходит в API_BASE_URL)
```

Ключевые переменные окружения — в [`.env.example`](.env.example) с комментариями
(БД/Redis, LLM-ключи, SMTP, JWT/`API_SHARED_SECRET`, Google OAuth, Telegram).
Каждый процесс на старте делает **fail-fast-валидацию** конфига (выход с кодом 78).

## Проверки и тесты

Из корня — через Makefile (`make help` — список):

```bash
make lint         # ruff
make typecheck    # mypy (strict) по src + eval
make imports      # import-linter — границы гексагональных слоёв
make test-unit    # unit-тесты (чистый домен/use-cases/скореры на фейках)
make test-integration   # integration через testcontainers (нужен Docker)
```

CI (GitHub Actions) прогоняет то же на `pgvector/pgvector:pg16`, плюс
web `typecheck`/`lint`/`build`, offline-eval-смоук и сборку образов.

## Offline-eval рекомендера

Воспроизводимый (seed=42) leave-one-out против **чистой математики**
`domain/recommender` + `HybridRanker` — без БД/LLM/torch:

```bash
make eval                        # печать таблицы метрик
cd backend && uv run python -m eval.run --json /tmp/eval.json
```

Метрики Recall@k / nDCG@k / MAP + catalog-coverage + intra-list diversity по
абляциям весов (`rule-only` / `content-only` / `bayesian-only` / `full` /
`full-no-MMR`) — видно вклад компонентов и trade-off MMR (точность ↔
разнообразие).

## Деплой (k8s/Helm)

Helm-чарт — [`deploy/helm/eventmind`](deploy/helm/eventmind). Deployment'ы
`api`/`worker`/`web` (+opt `bot`) из единого backend-образа (команда различает
роль), ConfigMap + Secret, liveness/readiness-probes, **HPA** (api/web по CPU;
worker по CPU + опц. external-metric длины очереди arq), **PDB** для api,
миграции — **Helm-hook Job** (`alembic upgrade head` pre-install/pre-upgrade),
Ingress (`/api`,`/metrics` → api; остальное → web).

```bash
helm upgrade --install eventmind deploy/helm/eventmind -f values.prod.yaml
```

Postgres(pgvector) и Redis — внешние (managed) через Secret; секреты в проде
подставлять из секрет-менеджера, не из `values.yaml`. Отдельный scheduler не
нужен — arq cron встроен в worker и дедуплицируется через Redis.

Нагрузочный смоук хот-путей (нужен установленный [k6](https://k6.io)):

```bash
make load-test BASE_URL=http://localhost:8000   # deploy/loadtest/k6-smoke.js
```

## Наблюдаемость

- **Логи:** structlog JSON с request-id/trace-id.
- **Трейсинг:** OpenTelemetry (HTTP → app → БД → LLM).
- **Метрики:** `/metrics` (Prometheus) — HTTP latency/RPS, вызовы/токены/latency
  LLM по провайдеру, доставки по каналам. Grafana-дашборды
  ([`deploy/grafana`](deploy/grafana)) + alert-rules
  ([`deploy/prometheus/alerts.yml`](deploy/prometheus/alerts.yml): ApiDown,
  5xx>5%, p95>1.5s, LLM error/breaker, сбои доставки).

## Статус milestone'ов

Все milestone'ы контракта [`docs/REBUILD_PROMPT.md`] закрыты (M0–M8):

| | Milestone | Суть |
|---|---|---|
| M0 | Скелет + инфра | гексагон, compose, CI, OTel, первая миграция (pgvector) |
| M1 | Аккаунты + auth | JWT httpOnly, UoW + транзакционный outbox, SMTP |
| M2 | LLM Gateway | цепочка Gemini→Groq (breaker/cooldown) + EmbeddingProvider |
| M3 | Ingestion | habr/rss/kudago, LLM-нормализация, идемпотентность/DLQ |
| M4 | Рекомендер | two-stage, чистая математика, online-обучение, кэш |
| M5 | Мультиканальность | email/telegram/in-app за портом, дайджест cron→queue |
| M6 | Веб-клиент | Next.js + BFF-прокси, NL-поиск, профиль, Google OAuth |
| M7 | Telegram-бот | aiogram поверх API (чистый HTTP-клиент) |
| M8 | Прод + eval | k8s/Helm+HPA, дашборды/алерты, load-test, offline-eval |

Подробности каждого — в [`ARCHITECTURE.md`](ARCHITECTURE.md).

[`docs/REBUILD_PROMPT.md`]: docs/REBUILD_PROMPT.md
