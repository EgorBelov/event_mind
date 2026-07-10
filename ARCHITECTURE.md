# EventMind v2 — архитектура

> Живой документ. Обновляется на каждом milestone. Статус: **M4 (Рекомендер)**.

EventMind собирает IT-события из внешних источников, нормализует их через LLM
и рекомендует пользователям, доставляя выдачу по выбранным каналам. v2 —
production-grade, **account-центричная** (не Telegram-bound) и
**мультиканальная** система. Обоснование каждого решения — ниже; принцип:
тяжёлый компонент вводится, только если решает конкретную проблему
масштабирования/надёжности.

## Две независимые оси

Ключ к развязке от Telegram — разделять **интерфейсы** и **каналы доставки**:

- **Интерактивные клиенты** (пользователь сам листает): веб-приложение
  (Next.js, основной) и Telegram-бот (вторичный). Оба ходят в один `/api/v1`.
- **Каналы доставки** (система сама пушит): порт `NotificationChannel` —
  email (SMTP: Mailhog в dev, Yandex/Mail.ru в prod), Telegram, in-app;
  web-push закладывается в модель на будущее.

## Гексагональные слои (ports & adapters)

```
┌──────────────────────────────────────────────────────────────────┐
│ interfaces/   FastAPI-api · aiogram-bot · arq-worker · scheduler   │  входные адаптеры
├──────────────────────────────────────────────────────────────────┤
│ infrastructure/  async-SQLAlchemy-репо · Redis/arq · LLM Gateway   │  реализации портов
│                  EmbeddingProvider · NotificationChannel · OTel     │
├──────────────────────────────────────────────────────────────────┤
│ application/   use-case'ы + порты (repos, UoW, gateway, каналы)     │  оркестрация
├──────────────────────────────────────────────────────────────────┤
│ domain/        чистые сущности, VO, доменные сервисы (без I/O)      │  ядро
└──────────────────────────────────────────────────────────────────┘
```

**Правило зависимостей:** `interfaces → application → domain`;
`infrastructure` реализует порты `application`; `domain` наружу не импортирует
(ни фреймворки, ни другие слои). Это машинно проверяется **import-linter**'ом
в CI (`backend/pyproject.toml → [tool.importlinter]`), а не только на ревью.

Почему гексагон: тезис-ядро (рекомендер, LLM-нормализация) должно тестироваться
детерминированно и переживать смену транспортов (веб/бот/worker) и провайдеров
(Gemini/Groq, SMTP/Resend, arq/Celery) без переписывания бизнес-логики.

## Процессы (каждый — отдельный контейнер, stateless, реплицируемый)

| Процесс | Технология | Роль | Появится |
|---|---|---|---|
| **api** | FastAPI (async) | `/api/v1`, JWT-auth, оркестрация use-case'ов | M0 (каркас) |
| **web** | Next.js (SSR/PWA) | основной интерфейс | M0 (каркас) → M6 |
| **worker** | arq | ingestion, LLM-нормализация, backfill, пересчёт кандидатов, рассылка | M3 |
| **scheduler** | arq cron + Redis-lock | периодические задачи → очередь | M5 |
| **bot** | aiogram 3 | вторичный клиент поверх API | M7 |

Stateless: всё состояние — в Postgres/Redis, ни одного module-dict (боль v1).
Это даёт горизонтальное масштабирование и переживание рестартов.

## Хранилища и почему именно они

- **PostgreSQL 16 + pgvector** — единый источник правды + kNN (HNSW) по
  эмбеддингам. Вектор — нативный тип `vector(384)` с **день-1** (в v1 эмбеддинги
  лежали JSON-текстом и pgvector доклеивался позже — переносим боль в прошлое).
  Пул с `pool_pre_ping=True` + `pool_recycle` (пулеры вроде Supabase режут idle).
- **Redis** — обоснован сразу несколькими ролями: брокер очереди arq,
  многоуровневый кэш, rate-limit, **лидер-локи** scheduler'а (защита от двойного
  запуска при репликах), эфемерное состояние. Один компонент закрывает пять нужд.
- **arq** (не Celery) — нативно async, лёгкий, ложится на async-стек и FastAPI
  без sync-прослоек. Celery-зрелость нам на старте не нужна, а его sync-корни
  трутся об async-код.
- **Outbox-паттерн** — доменное событие пишется в таблицу `outbox` **в той же
  транзакции**, что и изменение агрегата, а релей отдельно публикует его в
  очередь. Так рассылки/задачи не теряются при сбое между «сохранили в БД» и
  «поставили в очередь» (вводится в M1 вместе с UoW).

## Наблюдаемость (боль v1: не было ничего, кроме access-лога)

- **structlog** — JSON-логи с `request_id`/`trace_id` (одна строка на запрос:
  метод, путь-шаблон, статус, длительность). Уровень от кода: 5xx→error,
  4xx→warning. Никаких `print`.
- **OpenTelemetry** — сквозной трейсинг HTTP→app→БД→LLM, корреляция api↔worker.
  Включается флагом `OTEL_ENABLED`, экспорт по OTLP/HTTP.
- **Prometheus** (`/metrics`) + **Grafana** (провиженинг датасорса и дашборда
  из `deploy/grafana/`). В M0 — RPS и латентность; дальше добавляются латентность
  рекомендаций, hit-rate кэша, токены/стоимость LLM, длина очереди, доставки по
  каналам.

## Надёжность и безопасность (закладки, наполнение по milestone'ам)

- **health/ready**: `/health` — liveness (без зависимостей), `/ready` — проверка
  Postgres+Redis (503 при недоступности, чтобы оркестратор не слал трафик).
  Graceful shutdown дренирует пул/клиенты в lifespan.
- **fail-fast config**: `validate_or_exit(ctx)` роняет процесс с кодом **78**
  (EX_CONFIG) при пустых обязательных полях — понятная ошибка на boot'е.
- **Безопасность**: пользовательский JWT/OAuth2 (M1) + внутренний shared-secret
  (`hmac.compare_digest`) для worker↔api/bot↔api; rate-limit на Redis;
  prompt-safety перед LLM; верификация каналов перед рассылкой (M5).
- **Отказоустойчивость рекомендера**: каждый скорер/источник/канал — за
  интерфейсом и в try/except; сбой одного не роняет выдачу (переносим из v1).

## Что уже есть

**M0** — монорепо: `backend/` (uv, слои, config+validate, api-каркас,
наблюдаемость, Alembic async), `web/` (Next.js standalone), `legacy/` (v1
read-only), `deploy/` (compose: pg+redis+api+web+worker+prometheus+grafana+mailhog).

**M1** — account-центричное ядро:
- Домен `accounts` (чистый): `User`/`UserChannel`/`NotificationPreference`/
  `OneTimeToken`, VO (`Email`, `ChannelType`), доменные ошибки и события.
- Порты: репозитории, `UnitOfWork`, `PasswordHasher`, `TokenService`,
  `SecretTokenGenerator`, `EmailChannel`/`EmailRenderer`, `TaskQueue`, `Cache`, `OutboxStore`.
- Use-case'ы: регистрация, верификация email, вход, сброс пароля, привязка
  Telegram (deep-link токен + подтверждение ботом).
- Инфра: async-SQLAlchemy-репозитории + `SqlAlchemyUnitOfWork` с **транзакционным
  outbox**, argon2-хешер, JWT (httpOnly-cookie), SMTP-`EmailChannel`
  (Mailhog/Yandex/Mail.ru) + Jinja2-рендер, arq-`TaskQueue`, Redis-`Cache`.
- API `/api/v1/auth/*` (register/login/verify/reset/refresh/logout/me) и
  `/api/v1/channels/telegram/*`; JWT-аутентификация + внутренний API-key.
- arq-worker обрабатывает outbox → рассылка писем верификации/сброса.
- Единая миграция схемы (users с `vector(384)`+HNSW, channels, preferences,
  tokens, outbox). Seed демо-аккаунта.

**M2** — LLM Gateway + Embedding:
- Порт `LLMGateway` (`complete`, `structured_output(schema)`) + `LLMChain`:
  цепочка Gemini(REST)→Groq70b→Groq8b с fallback, **circuit-breaker** (5 подряд
  фейлов цепочки → cooldown 120с) и **per-provider cooldown** (2 фейла звена →
  skip 10 мин); async-автопроба Gemini-модели; учёт токенов и Prometheus-метрики.
- Порт `EmbeddingProvider` + `SentenceTransformerEmbeddingProvider` (MiniLM-384,
  ленивый импорт torch через extra `ml`, батчинг, LRU-кэш, версия модели,
  encode в отдельном потоке).
- Admin `/api/v1/admin/llm/{status,reprobe}` (внутренний API-key). Оба провайдера
  и embedding подключены в DI-контейнер.

**M3** — Ingestion pipeline:
- Домен `events`: сущности `Event`/`RawEvent`, enum'ы, чистая таксономия
  (slug/canonicalize_city + CITY_ALIASES) и `compute_series_slug` (порт из v1).
- Порт `EventSource` + реестр; async-источники **habr**(bs4)/**rss**(feedparser
  в потоке)/**kudago**(httpx) с чистыми parse-функциями.
- Нормализатор: `LLMGateway.structured_output(NormalizedEvent)` + пост-обработка
  (enum-валидация, строгая ISO-дата, defence-in-depth «это IT-событие?») —
  системный промпт и правила портированы из v1.
- Пайплайн `source → raw_events → normalize → events`: идемпотентность
  (по source+url / source_url), ретраи с **DLQ** (status=failed при исчерпании),
  эмбеддинг события (best-effort), топики в `topics`/`event_topics`, series_slug.
- API `/api/v1/ingestion/{load/{source},load-all,normalize,retry-failed,status}`
  (внутренний API-key) + arq-задачи `ingest_source`/`normalize_raw_events`.
- Миграция 0003 (events+vector(384)+HNSW, raw_events, topics, event_topics).

**M4** — Рекомендер (two-stage, научное ядро):
- Чистая математика в `domain/recommender` (портирована из v1, детерминизм
  через инъекцию rng/now): cosine, freshness (half-life decay), rule-score,
  bayesian (Beta + Thompson + temporal-decay), MMR-rerank, series anti-flood,
  веса `ScoringWeights`.
- **Two-stage**: `PgvectorCandidateGenerator` (kNN `embedding <=> user_emb` на
  HNSW + upcoming-фильтр, cold-start по quality) → `HybridRanker` (взвешенная
  сумма rule/cosine/bayesian/quality/hype/freshness, каждый компонент в
  try/except) → MMR + анти-флуд серий.
- **Online-обучение**: `RecordInteraction` (like/dislike/save) обновляет
  Bayesian-статы, прогревает `user.embedding` (среднее понравившихся) и
  инвалидирует кэш.
- **Read-only hot-path**: `GET /api/v1/recommendations` (JWT) отдаёт из
  Redis-кэша (TTL 15 мин); `POST /api/v1/interactions` учит и сбрасывает кэш.
- Миграция 0004 (interactions, user_topic_stats, user prefs). Скореры-заделы
  skill_gap/bandit(LinUCB)/gnn(LightGCN) — веса определены, включаются флагами
  позже (gnn выключен и в v1 на малом датасете).

Зелёные проверки: ruff, mypy(strict, 111 файлов), import-linter (границы слоёв),
pytest (unit — домен/security/use-cases/LLM/embedding/ingestion/**вся математика
рекомендера + HybridRanker** на фейках; integration — auth, outbox+UoW,
SMTP↔Mailhog, telegram, ingestion, **recommendations+feedback** через
testcontainers), сборка образов — CI.

## Поток данных: регистрация (пример транзакционного outbox)

```
POST /register → RegisterUser use-case
  └─ UnitOfWork (одна транзакция):
       users.add + channels.add + preferences.add + tokens.add
       add_event(UserRegistered{raw_token})  ──► строка в outbox
       commit                                   (агрегаты + событие атомарно)
  └─ TaskQueue.enqueue("process_outbox")  ──► Redis/arq
worker: process_outbox → OutboxProcessor
  └─ handler(user.registered) → EmailRenderer → EmailChannel(SMTP) → письмо
```

## Дальше (roadmap)

M5 мультиканальная доставка · M6 веб-клиент ·
M7 Telegram-бот · M8 прод (k8s/Helm/HPA) + offline-eval. Детали — в
`docs/REBUILD_PROMPT.md` (контракт) и плане каждого milestone.
