# EventMind

**EventMind** — production-grade, **аккаунт-центричная мультиканальная** система
агрегации IT-мероприятий и персональных рекомендаций. Пользователь заводит
**аккаунт**, к которому привязаны каналы доставки (email, Telegram, in-app);
система собирает события из разных источников, нормализует их LLM'ом, строит
персональную ленту two-stage-рекомендером и доставляет дайджест по включённым
каналам. Интерфейсы — адаптивный веб (Next.js) и Telegram-бот, оба поверх
единого REST API.

Архитектура — **гексагональная** (ports & adapters), async сверху донизу,
границы слоёв проверяются `import-linter` в CI.

> **v2.** Проект перестроен с нуля по контракту [`docs/REBUILD_PROMPT.md`](docs/REBUILD_PROMPT.md).
> Код **v1** (Telegram-центричный, sync-FastAPI + APScheduler) сохранён в отдельной
> ветке [`v1-main`](https://github.com/EgorBelov/event_mind/tree/v1-main) — из него
> портирована доменная логика (математика рекомендера, LLM-промпты, парсеры
> источников, канонизация, фильтры, eval). Архитектура v1 **не** наследуется.
>
> Живой архитектурный документ — [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Содержание

1. [Возможности](#возможности)
2. [Архитектура](#архитектура)
   - [Гексагональные слои](#гексагональные-слои)
   - [Процессы и хранилища](#процессы-и-хранилища)
   - [Поток данных: регистрация](#поток-данных-регистрация-транзакционный-outbox)
3. [Структура монорепо](#структура-монорепо)
4. [Стек](#стек)
5. [Модель данных](#модель-данных)
6. [Рекомендер](#рекомендер-two-stage)
7. [REST API](#rest-api-обзор)
8. [Быстрый старт](#быстрый-старт-docker-compose)
9. [Локальная разработка](#локальная-разработка)
10. [Проверки и тесты](#проверки-и-тесты)
11. [Offline-eval](#offline-eval-рекомендера)
12. [Деплой (k8s/Helm)](#деплой-k8shelm)
13. [Наблюдаемость и безопасность](#наблюдаемость-и-безопасность)
14. [Статус milestone'ов](#статус-milestoneов)

---

## Возможности

- **Аккаунт-центричная модель.** Идентичность — аккаунт (email); Telegram —
  привязанный канал, а не первичный ключ. Развязка от Telegram — ключевое отличие
  от v1.
- **Аутентификация.** Email+пароль (argon2, JWT в httpOnly-cookie, верификация
  email и сброс пароля через транзакционный outbox), **Google OAuth**
  (`POST /auth/google`), привязка Telegram deep-link-токеном.
- **Ingestion.** Реестр источников (**habr / rss / kudago**) → `raw_events` →
  LLM-нормализация (structured output, enum-валидация, строгие ISO-даты) →
  `events`. Идемпотентность по `source+url`, ретраи, DLQ, батчинг.
- **Two-stage рекомендер.** pgvector kNN-кандидаты → взвешенный ансамбль
  скореров → MMR-rerank + series anti-flood. Online-обучение по фидбеку
  (Bayesian-Thompson + прогрев user-эмбеддинга + инвалидация кэша).
- **NL-поиск.** Фраза обычного языка → LLM извлекает `SearchFilters` →
  канонизация → строгий проход → relax-fallback (поэтапно снимает фильтры).
- **Мультиканальная доставка.** Единый порт `NotificationChannel`
  (email SMTP / Telegram Bot API / in-app), дайджест по расписанию
  (cron → очередь → рассылка по включённым+verified каналам, гейтинг
  предпочтений и тихих часов), in-app инбокс, unsubscribe по подписанному токену.
- **Клиенты.** Next.js-веб (лента · NL-поиск · карточка · инбокс · настройки) и
  Telegram-бот (лента · feedback · поиск) — оба тонкие клиенты поверх API.

## Архитектура

### Гексагональные слои

Правило зависимостей: `interfaces → application → domain`; `infrastructure`
реализует порты `application`; `domain` наружу не импортирует ничего
(фреймворки/I-O). Каждый источник / скорер / провайдер / канал — за интерфейсом,
регистрируется в реестре.

```
                          ВХОДНЫЕ АДАПТЕРЫ (interfaces)
        ┌──────────────┬───────────────┬──────────────┬──────────────┐
        │  api         │  bot          │  worker      │  cli         │
        │  (FastAPI)   │  (aiogram 3)  │  (arq)       │  (seed)      │
        └──────┬───────┴───────┬───────┴──────┬───────┴──────────────┘
               │  вызывают use-cases           │
               ▼                               ▼
     ╔══════════════════════════════════════════════════════════════╗
     ║                     application                                ║
     ║   use-cases (RegisterUser, GetRecommendations, SendUserDigest, ║
     ║   NlSearch, LoadSource, NormalizeRawEvents, …)                 ║
     ║   + ПОРТЫ (Protocol): repositories, UnitOfWork, Cache,         ║
     ║     TaskQueue, LLMGateway, EmbeddingProvider, EventSource,     ║
     ║     NotificationChannel, GoogleTokenVerifier, …                ║
     ╚════════════════════════════╤═════════════════════╤════════════╝
              реализуют порты      │                     │  использует
                                   ▼                     ▼
     ┌──────────────────────────────────────┐  ╔═══════════════════════╗
     │           infrastructure             │  ║        domain         ║
     │  async-SQLAlchemy-репозитории + UoW  │  ║  чистые сущности/VO   ║
     │  + transactional outbox              │  ║  доменные сервисы:    ║
     │  LLM-цепочка (Gemini→Groq, breaker)  │  ║  • математика         ║
     │  EmbeddingProvider (MiniLM-384)      │  ║    рекомендера        ║
     │  arq TaskQueue · Redis Cache         │  ║  • таксономия/города  ║
     │  NotificationChannel: SMTP/TG/in-app │  ║  • series_slug        ║
     │  HTTP-парсеры источников · телеметрия │  ║  Без I/O, без ORM.    ║
     └──────────────────┬───────────────────┘  ╚═══════════════════════╝
                        ▼
          PostgreSQL + pgvector (HNSW)   ·   Redis   ·   SMTP   ·   LLM API
```

### Процессы и хранилища

Каждый процесс — отдельный контейнер, stateless, реплицируемый. Единый
backend-образ обслуживает `api`/`worker`/`bot` (команда различает роль).

```
   Web (Next.js)                         Telegram-бот (aiogram)
      │  /bff/[...] прокси                    │  BotApiClient
      │  httpOnly-cookie same-site            │  X-API-Key (внутренний)
      ▼                                       ▼
  ┌───────────────────────── api (FastAPI, async) ─────────────────────────┐
  │  /api/v1  ·  JWT-cookie  ·  CORS  ·  /health /ready  ·  /metrics        │
  └───────┬───────────────────────────────────────────────────┬───────────┘
          │ читает/пишет                     enqueue │          │ pub метрики
          ▼                                          ▼          ▼
   ┌──────────────┐   transactional outbox    ┌───────────┐   Prometheus
   │ PostgreSQL   │◀────────────────────────▶ │  Redis    │   → Grafana
   │  + pgvector  │                           │  очередь  │   + alerts
   │  (HNSW-kNN)  │                           │  + кэш    │
   └──────▲───────┘                           └─────┬─────┘
          │ читает/пишет                            │ потребляет очередь + cron
          │                                         ▼
          │                          ┌──────────────────────────────┐
          └──────────────────────────│  worker (arq)                │
                                     │  process_outbox · ingest ·   │
                                     │  normalize · send_digest ·   │
                                     │  cron: schedule_digests      │
                                     └──────────────────────────────┘
```

Планировщик отдельным процессом не нужен — arq **cron встроен в worker** и
дедуплицируется между репликами через Redis-lock.

### Поток данных: регистрация (транзакционный outbox)

Надёжная публикация доменных событий: агрегат и событие пишутся в БД **одной
транзакцией**, релей в очередь — отдельно, поэтому письмо не теряется при сбоях.

```
POST /api/v1/auth/register  →  RegisterUser (application)
  └─ UnitOfWork (ОДНА транзакция):
        users.add + channels.add(email) + preferences.add + tokens.add
        add_event(UserRegistered{verification_token})  ──► строка в outbox
        commit                          (агрегаты + событие атомарно)
  └─ TaskQueue.enqueue("process_outbox")  ──► Redis/arq
worker: process_outbox → OutboxProcessor
  └─ handler(user.registered) → Jinja2EmailRenderer → SmtpEmailChannel → письмо
     (dev: перехват Mailhog;  prod: Yandex/Mail.ru SMTP)
```

## Структура монорепо

```
backend/                       Python 3.12 · uv · гексагон
  src/eventmind/
    domain/                    чистые сущности/VO/доменные сервисы (без I/O)
      accounts/  events/  recommender/  notifications/
    application/               use-cases + порты (Protocol)
      accounts/ ingestion/ recommender/ notifications/ search/ ports/ outbox/
    infrastructure/            адаптеры портов
      db/ (репо+UoW+outbox)  llm/  embedding/  sources/  notifications/
      cache/  queue/  security/  telemetry/
    interfaces/                входные адаптеры
      api/ (роутеры+DI)  bot/ (aiogram)  worker/ (arq)  cli/ (seed)
    config.py                  pydantic-settings + fail-fast validate (exit 78)
  eval/                        offline-eval harness (вне src/ — tooling)
  alembic/                     async-миграции 0001–0005 (pgvector + HNSW)
  tests/  unit/ (155)  integration/ (31, testcontainers)
web/                           Next.js 14 (App Router, standalone) + BFF-прокси
deploy/
  docker-compose.yml           dev-стек
  helm/eventmind/              prod: Deployments + HPA + PDB + Ingress + hooks
  prometheus/ (alerts)  grafana/ (дашборды)  loadtest/ (k6)
docs/REBUILD_PROMPT.md         контракт перестройки
ARCHITECTURE.md   CLAUDE.md   Makefile   .env.example
```

## Стек

| Область | Технологии |
|---|---|
| API | FastAPI (async), Uvicorn/Gunicorn, Pydantic v2 |
| БД | PostgreSQL 16 + **pgvector** (HNSW), SQLAlchemy 2.0 async + asyncpg, Alembic |
| Очередь/кэш | **arq** + Redis (очередь, кэш, локи, rate-limit) |
| Auth | argon2-cffi, PyJWT (httpOnly-cookie), Google OAuth (tokeninfo) |
| LLM | LLM Gateway: langchain-core/-google-genai/-groq (Gemini→Groq70b→Groq8b) |
| Эмбеддинги | sentence-transformers MiniLM-384 (extra `ml`, ленивый импорт) |
| Email | aiosmtplib + Jinja2 (Mailhog dev / Yandex·Mail.ru prod) |
| Источники | beautifulsoup4 / lxml / feedparser |
| Бот | aiogram 3 (extra `bot`) |
| Веб | Next.js 14 (App Router, standalone), TypeScript |
| Наблюдаемость | structlog (JSON) + OpenTelemetry + prometheus-client |
| Качество | ruff · mypy(strict) · import-linter · pytest (+ pytest-asyncio, testcontainers) |

## Модель данных

Единая консистентная схема, `vector(384)` + HNSW-индексы под hot-path с день 1
(миграции `0001`–`0005`):

- **`users`** — аккаунт: email (unique), `password_hash` (argon2, nullable для
  OAuth), `email_verified`, `is_active`, `oauth_provider/sub`, `city`,
  `preferred_format`, `embedding vector(384)`.
- **`user_channels`** — `{type: email|telegram, address, verified, enabled}`.
- **`notification_preferences`** — частота дайджеста, каналы, тихие часы.
- **`one_time_tokens`** — верификация email / сброс пароля / привязка Telegram
  (хранится хеш, TTL, одноразовость).
- **`outbox`** — надёжная публикация доменных событий.
- **`topics` · `events` · `raw_events` · `event_topics`** — каталог: `events`
  с `embedding vector(384)` (HNSW), `start_at timestamptz` + строка `date`,
  `series_slug` (индекс), `quality_score`/`hype_score`.
- **`interactions` · `user_topic_stats`** — фидбек и Bayesian-статистики
  (α/β по темам) для online-обучения.
- **`notifications`** — in-app инбокс + лог доставки.

## Рекомендер (two-stage)

**Стадия 1 — кандидаты** (`PgvectorCandidateGenerator`): kNN по user-эмбеддингу
на HNSW среди upcoming-событий; **cold-start** (нет эмбеддинга/стат) — свежие
качественные события. Это ограничивает скоринг top-N кандидатами, а не всей
таблицей.

**Стадия 2 — ранжирование** (`HybridRanker`): взвешенная сумма компонентов, все в
try/except (сбой одного не рушит выдачу):

| Компонент | Парадигма | Вес | Где |
|---|---|---|---|
| rule | rule-based (темы/город/формат) | 0.5 | `domain/recommender/scoring.py` |
| cosine | content-based (эмбеддинги) | 10.0 | `scoring.py` |
| bayesian | Thompson sampling (Beta) | 5.0 | `domain/recommender/bayesian.py` |
| quality | LLM-оценка 1–10 | 0.5 | `events.quality_score` |
| hype | LLM-оценка 1–10 | 0.3 | `events.hype_score` |
| freshness | exp-decay по дате | 2.0 | `scoring.py` |
| skill_gap / bandit / gnn | заделы под флагами | 3.0 / 2.0 / 3.0 | `weights.py` |

Поверх — **MMR-rerank** (λ=0.7) + **series anti-flood** (из одинаковых
`series_slug` остаётся ближайший к now). Cold-start bayesian=0 (без стат не льём
Thompson-шум — ранжируем по контенту/качеству/свежести; exploration включается с
первым фидбеком).

**Online-обучение** (`RecordInteraction`): like/save/dislike → обновление
Bayesian-стат + прогрев user-эмбеддинга + инвалидация кэша. Hot-path
`GET /recommendations` — read-only, из Redis-кэша (TTL 15 мин).

## REST API (обзор)

`/api/v1`, JWT в httpOnly-cookie. Полная спецификация — `/docs` (OpenAPI).

| Группа | Эндпоинты |
|---|---|
| auth | `POST /auth/{register,login,logout,refresh,verify-email,password-reset,password-reset/confirm,google}` |
| users | `GET/PATCH /users/me` · `GET/PATCH /users/me/preferences` |
| channels | `POST /channels/telegram/{link-token,confirm}` |
| events | `GET /events/nl-search` · `GET /events/{id}` |
| recommendations | `GET /recommendations` · `POST /interactions` |
| notifications | `GET /notifications` · `POST /notifications/{id}/read` · `GET /notifications/unsubscribe` |
| ingestion | `POST /ingestion/{load-source,load-all,normalize}` · `GET /ingestion/status` |
| bot (internal) | `GET /bot/{status,recommendations}` · `POST /bot/interactions` (X-API-Key) |
| ops | `/health` · `/ready` · `/metrics` · `POST /admin/llm/{status,reprobe}` |

## Быстрый старт (docker compose)

Нужен Docker. Из корня:

```bash
cp .env.example .env      # опц.: GOOGLE_API_KEY/GROQ_API_KEY, BOT_TOKEN, SMTP, ...
make up                   # pg + redis + api + web + worker + prometheus + grafana + mailhog
```

| Сервис | URL |
|---|---|
| API (health) | http://localhost:8000/health |
| Web | http://localhost:3000 |
| Grafana | http://localhost:3001 (admin/admin) |
| Prometheus | http://localhost:9090 |
| Mailhog (dev-письма) | http://localhost:8025 |

Telegram-бот — отдельный профиль: `docker compose --profile bot up` при заданном
`BOT_TOKEN`. `make down` — остановить (данные в volume'ах сохраняются).

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
cd web && npm install && npm run dev    # http://localhost:3000
```

Переменные окружения — в [`.env.example`](.env.example) с комментариями. Каждый
процесс на старте делает **fail-fast-валидацию** конфига (выход с кодом 78 при
отсутствии required-полей под свой контекст).

## Проверки и тесты

```bash
make lint          # ruff
make typecheck     # mypy (strict) по src + eval
make imports       # import-linter — границы гексагональных слоёв
make test-unit     # 155 unit-тестов (чистый домен/use-cases/скореры на фейках)
make test-integration   # 31 integration через testcontainers (нужен Docker)
```

CI (GitHub Actions) прогоняет то же на `pgvector/pgvector:pg16`, плюс web
`typecheck`/`lint`/`build`, offline-eval-смоук и сборку образов. Unit —
детерминизм (`seed=42`), без внешних сервисов; integration — репозитории/
pgvector/очередь/outbox/каналы/SMTP↔Mailhog.

## Offline-eval рекомендера

Воспроизводимый (seed=42) leave-one-out против **чистой математики**
`domain/recommender` + `HybridRanker` — без БД/LLM/torch:

```bash
make eval                                     # печать таблицы метрик
cd backend && uv run python -m eval.run --json /tmp/eval.json
```

Метрики **Recall@k / nDCG@k / MAP** + catalog-coverage + intra-list diversity по
абляциям весов (`rule-only` / `content-only` / `bayesian-only` / `full` /
`full-no-MMR`) — видно вклад компонентов и trade-off MMR (точность ↔
разнообразие).

## Деплой (k8s/Helm)

Чарт — [`deploy/helm/eventmind`](deploy/helm/eventmind):

```bash
helm upgrade --install eventmind deploy/helm/eventmind -f values.prod.yaml
```

Deployment'ы `api`/`worker`/`web` (+opt `bot`) из единого backend-образа,
ConfigMap + Secret, liveness/readiness-probes, **HPA** (api/web по CPU; worker по
CPU + опц. external-metric длины очереди arq), **PDB** для api, миграции —
**Helm-hook Job** (`alembic upgrade head` pre-install/pre-upgrade), Ingress
(`/api`,`/metrics` → api; остальное → web). Postgres(pgvector) и Redis — внешние
(managed) через Secret; секреты в проде подставлять из секрет-менеджера.

Нагрузочный смоук хот-путей (нужен [k6](https://k6.io)):

```bash
make load-test BASE_URL=http://localhost:8000   # deploy/loadtest/k6-smoke.js
```

## Наблюдаемость и безопасность

- **Логи** — structlog JSON с request-id/trace-id; одна строка на запрос с
  таймингом; 4xx → WARNING без traceback, 5xx → ERROR.
- **Трейсинг** — OpenTelemetry (HTTP → app → БД → LLM, корреляция api↔worker).
- **Метрики** — `/metrics` (Prometheus): HTTP latency/RPS, вызовы/токены/latency
  LLM по провайдеру, доставки по каналам. Grafana-дашборды
  ([`deploy/grafana`](deploy/grafana)) + alert-rules
  ([`deploy/prometheus/alerts.yml`](deploy/prometheus/alerts.yml): ApiDown,
  5xx>5%, p95>1.5s, LLM error/breaker, сбои доставки).
- **Отказоустойчивость** — сбой LLM/источника/скорера/канала не роняет запрос
  (деградация + circuit-breaker + per-provider cooldown); идемпотентные джобы,
  ретраи, DLQ, graceful shutdown с дренажом очереди.
- **Безопасность** — JWT (httpOnly-cookie) + внутренний API-key
  (`hmac.compare_digest`), prompt-safety (sanitize + границы user-text перед LLM),
  верификация email/каналов перед рассылкой, unsubscribe-ссылки, whitelisted
  health/docs, секреты вне репозитория.

## Статус milestone'ов

Все milestone'ы контракта закрыты (M0–M8):

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
