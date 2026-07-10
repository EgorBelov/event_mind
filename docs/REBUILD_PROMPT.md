# Промпт для Claude Code: перезапуск EventMind v2 — production-grade, scalable

> Вставь весь текст ниже первым сообщением в новой сессии Claude Code в
> **пустом репозитории**. Это контракт на серию итераций, а не «сделай всё за
> раз»: сначала утверждаем архитектуру и скелет, дальше наполняем по
> вертикальным срезам. На каждом milestone — рабочий `docker compose up`,
> зелёные тесты, обновлённые доки, отдельный коммит.

---

## Роль и цель

Ты — ведущий инженер, поднимающий с нуля **EventMind v2**: систему агрегации
IT-мероприятий и персональных рекомендаций (Telegram-бот + REST API +
фоновые пайплайны). Это магистерский проект, но цель — **настоящий большой
масштабируемый продукт продакшн-уровня**, а не прототип. Значит: система
должна выдерживать рост нагрузки/данных, быть отказоустойчивой,
наблюдаемой, разворачиваемой в оркестраторе и горизонтально
масштабируемой. При этом **рекомендательное ядро** остаётся научной
короной проекта (для главы с оценкой качества) — вкладываем и в его
инженерию, и в воспроизводимую offline/online-оценку.

**Важно про инженерную честность:** каждый «тяжёлый» компонент (очередь,
брокер, кэш, трейсинг) вводится, только если решает конкретную проблему
масштабирования или надёжности — с обоснованием в `ARCHITECTURE.md`. Никакого
карго-культа: не пили швы, которые не разрежешь.

## Режим работы

1. Сначала **войди в plan mode**: предложи архитектуру + план по milestone'ам,
   задай уточняющие вопросы по развилкам. Не пиши код до моего «go».
2. Каждый milestone: рабочий compose, зелёные тесты (unit+integration),
   обновлённые `README.md`/`ARCHITECTURE.md`, отдельный коммит.
3. На развилках с архитектурными последствиями — спрашивай явным вопросом
   с вариантами, не решай молча.
4. Никаких `TODO позже` в ядре: компонент из плана обязан иметь тест.

## Домен (переносим смысл из v1, код НЕ переиспользуем)

EventMind собирает IT-события из внешних источников, нормализует их через
LLM и рекомендует пользователям. Сущности: `User`, `Event`, `RawEvent`
(сырое до нормализации), `Topic`, `Interaction` (like/dislike/save),
профиль интересов, эмбеддинги пользователя и события. Рекомендер v1 — гибрид
из ~9 компонент (rule-based, cosine по эмбеддингам, Thompson sampling,
LLM-оценки quality/hype, freshness-decay, skill-gap, LinUCB-бандит,
LightGCN, MMR-rerank + анти-флуд серий). Сохраняем как **набор pluggable
скореров за единым интерфейсом**, а не переплетённый монолит.

## Уроки v1, которые чинит v2 (это и есть цель переписывания)

| Боль v1 | Решение v2 |
|---|---|
| Эмбеддинги как JSON-текст, pgvector доклеен позже | **pgvector с день 1**, `vector`-тип, HNSW-индексы, тюнинг ef_search |
| Гибридный скоринг синхронно в hot-path `GET /recommendations`, залатан TTL-кэшем | **Two-stage: candidate generation → ranking**, предпосчёт кандидатов в фоне, hot-path read-only |
| Ingestion + LLM-нормализация в процессе API/scheduler | **Очередь задач + worker-пул**, API только ставит job и отдаёт статус; идемпотентность, ретраи, DLQ |
| Состояние в module-dict (курсор ленты терялся при рестарте, ломался под несколькими воркерами) | **Stateless-процессы**, всё состояние в Postgres/Redis, горизонтальное масштабирование |
| Синхронный SQLAlchemy + блокирующий httpx | **async сверху донизу** |
| SQLite/Postgres дуализм, тесты цепляются за живую БД | Postgres везде, интеграционные тесты через **testcontainers** |
| Самописная LLM-цепочка, размазанная по коду | Единый **LLM Gateway** за портом: fallback-цепочка, breaker, таймауты, учёт токенов/стоимости, метрики |
| Нет наблюдаемости кроме access-лога | **Structured logs + OpenTelemetry traces + Prometheus метрики + Grafana дашборды** |
| Секреты/конфиг вперемешку | 12-factor, `pydantic-settings`, fail-fast валидация на старте, секреты вне репозитория |

## Целевая архитектура

**Модульный монолит с гексагональными границами** (ports & adapters),
готовый к вырезанию сервисов там, где это осмысленно, но без
преждевременного микросервисного дробления. Слои:

```
domain/          # чистые сущности, value-objects, доменные сервисы. Без I/O и фреймворков.
application/     # use-cases + порты (интерфейсы репозиториев, шины, gateway'ев) + оркестрация.
infrastructure/  # адаптеры: async-SQLAlchemy-репозитории, LLM Gateway, EmbeddingProvider,
                 #           очередь, кэш, outbox, HTTP-клиенты источников, телеметрия.
interfaces/      # входные адаптеры: FastAPI-роутеры, aiogram-хендлеры, worker/scheduler-энтрипоинты, CLI.
```

Правило зависимостей: `interfaces → application → domain`; `infrastructure`
реализует порты из `application`; `domain` не импортирует наружу.

### Процессы (каждый — отдельный контейнер, stateless, реплицируемый)
- **api** — FastAPI (async), только оркестрация use-case'ов, версионирование `/api/v1`,
  graceful shutdown, liveness/readiness.
- **bot** — aiogram 3, ходит в API по HTTP (никакого прямого доступа к БД).
- **worker** — пул потребителей очереди: ingestion, LLM-нормализация,
  backfill эмбеддингов, пересчёт кандидатов рекомендаций. Идемпотентность, ретраи с backoff, DLQ.
- **scheduler** — только раскладывает периодические задачи в очередь (cron→queue),
  сам тяжёлого не делает; защита от двойного запуска (лидер-лок в Redis).

### Хранилища и инфраструктура
- **PostgreSQL 16 + pgvector** — источник правды + векторный kNN (HNSW).
  Пул соединений (pgbouncer-совместимо), `pool_pre_ping`, стратегия под read-replica на будущее.
- **Redis** — брокер очереди, кэш (многоуровневый), rate-limit, лидер-локи,
  эфемерное состояние диалогов бота.
- **Outbox-паттерн** для надёжной публикации доменных событий (запись в БД в
  той же транзакции → релей в очередь), чтобы не терять задачи при сбоях.
- Очередь: предложи и обоснуй (**arq** — нативно async/лёгкий, **Celery** —
  зрелость/экосистема, **faststream** — если пойдём в event-driven). Дефолт — вынеси на утверждение.

## Технологический стек (Python 3.12)

- **FastAPI** + **uvicorn/gunicorn** (async), **Pydantic v2** / pydantic-settings.
- **SQLAlchemy 2.0 async** + **Alembic** (async-совместимые миграции), **pgvector**.
- **aiogram 3** (бот).
- **arq/Celery** + Redis (фоновые задачи, DLQ, ретраи).
- **LangGraph** — только для реально графовых сценариев (LLM-нормализация,
  агентные диалоги), за портом `application`. Простые вызовы — через LLM Gateway напрямую.
- **sentence-transformers** (MiniLM, 384-dim, multilingual) за интерфейсом
  `EmbeddingProvider` — модель заменяема и выносима в отдельный inference-сервис.
- **pytest** + **pytest-asyncio** + **testcontainers[postgres]** + httpx-тесты; **ruff** + **mypy** (strict).
- **OpenTelemetry** (traces/metrics), **prometheus-client**, **structlog** (JSON-логи), **Grafana**-дашборды.
- **Docker** (multi-stage) + **docker-compose** (dev) + **k8s-манифесты/Helm-чарт** (prod-ready).
- **CI/CD**: GitHub Actions — lint + type-check + tests(pgvector) + build образов + (опц.) push в registry.
- Нагрузочное тестирование: **locust** или **k6** (смоук хот-путей).

## Ключевые абстракции (порты в `application`)

Явные интерфейсы (Protocol/ABC), реализации в `infrastructure`:

1. **`LLMGateway`** — `complete()`, `structured_output(schema)`, `bind_tools()`.
   Внутри: цепочка провайдеров (Gemini → Groq 70b → Groq 8b), per-provider
   cooldown, circuit-breaker, retry, таймауты, учёт токенов/стоимости, метрики.
   Остальной код зависит **только** от интерфейса.
2. **`EmbeddingProvider`** — `embed_texts(list[str]) -> list[Vector]`, батчинг,
   кэш, версия модели в метаданных. Готов к выносу в отдельный сервис.
3. **`EventSource`** — контракт источника ingestion (`fetch() -> list[RawEvent]`);
   habr, rss, kudago, luma, meetup, telegram, timepad. **Плагин-реестр**:
   добавление источника не трогает ядро.
4. **Репозитории-порты** на агрегат (`UserRepo`, `EventRepo`, …) — интерфейс в
   `application`, async-SQLAlchemy-реализация в `infrastructure`; домен не знает про ORM.
5. **`TaskQueue`** — `enqueue(job, payload)` + идемпотентные ключи; абстрагирует брокер.
6. **`Cache`** — типизированный Redis (TTL, инвалидация по тегам, многоуровневость).
7. **`UnitOfWork`** — транзакционная граница + запись в outbox в той же транзакции.

## Рекомендер (ядро тезиса + масштабируемость)

Двухстадийный пайплайн, каждый компонент — pluggable, включается флагом, в try/except:

- **CandidateGenerator** — retrieval: pgvector kNN по user-embedding + фильтры
  (upcoming, город/формат), ограничение до N кандидатов. Масштабируется на рост каталога.
- **Scorers** — единый интерфейс `score(user_ctx, candidates) -> dict[event_id, float]`:
  rule, cosine, bayesian (Thompson), quality, hype, freshness, skill_gap, bandit (LinUCB), gnn (LightGCN).
  Веса из конфига; сбой одного скорера не рушит выдачу.
- **Reranker** — MMR (λ) + **series anti-flood** (из группы одной серии оставить ближайший по времени).
- **Предпосчёт** кандидатов/скорингов в worker'е, инвалидация по feedback/edit-профиля;
  `GET /api/v1/recommendations` — **read-only**, только чтение кэша/предпосчёта.
- **Online-обучение** через бандит/Thompson по интеракциям (это и есть A/B-исследование в тезисе).
- **Offline-eval harness** (`eval/`): воспроизводимо (`seed=42`), leave-one-out на
  синтетическом датасете — Recall@k, nDCG@k, MAP, coverage, diversity, novelty;
  + LLM-as-judge. Config-driven ablations (включать/выключать компоненты и сравнивать).
  Результаты выгружаются в таблицы/фигуры для главы отчёта.

## Модель данных

Агрегаты (уточни поля в плане): `users`, `events`, `raw_events`, `topics` +
`user_topics`/`event_topics`, `interactions`, `user_topic_stats`,
`user_bandit_state`, `user_skill_profile`, `user_memory`,
`recommendation_candidates` (предпосчёт), `outbox`.

Требования к схеме:
- Эмбеддинги — колонки `vector(384)` (pgvector), HNSW-индекс, не текст.
- `telegram_id` — `BIGINT` сразу.
- Даты: и распарсенный `start_at: timestamptz`, и человекочитаемая строка.
- `series_slug` (индекс) для анти-флуда серий.
- Все FK, уникальные ограничения, индексы под hot-path — с день 1.
- Стратегия роста: продумать **партиционирование `interactions`/`events`** по времени
  (документировать, даже если включим позже) под большой объём.
- Alembic: первая миграция создаёт консистентную схему целиком.

## Надёжность, наблюдаемость, безопасность (production-grade)

- **Надёжность**: идемпотентные worker-джобы, ретраи с экспоненциальным
  backoff, **DLQ**, outbox для доставки событий, graceful shutdown с дренажом
  очереди, backpressure, health/readiness (`/health` liveness, `/ready` — БД+Redis).
- **Отказоустойчивость**: сбой LLM/источника/скорера не роняет запрос —
  логируется и деградирует функциональность; circuit-breaker'ы.
- **Наблюдаемость**: **structlog** JSON-логи с request-id/trace-id;
  **OpenTelemetry** трейсы (HTTP→app→БД→LLM), корреляция API↔worker;
  **Prometheus** метрики (latency рекомендаций, hit-rate кэша, токены/стоимость
  LLM по провайдерам, длина очереди/лаг, ошибки источников) + **Grafana** дашборды + алерты.
- **Безопасность**: аутентификация API (**JWT/OAuth2** для будущего веб-клиента +
  `X-API-Key` shared-secret для внутренних вызовов бота/воркеров, `hmac.compare_digest`),
  **rate-limit** на Redis, версионирование API, whitelisted health/docs, секреты вне
  репозитория (env/secret-manager), **prompt-safety** (sanitize + границы user-text перед LLM).
- **fail-fast config validation** на старте каждого процесса (код выхода 78).

## Деплой и дев-опыт

- **docker-compose.yml** (dev): postgres(pgvector) + redis + api + bot + worker + scheduler + prometheus + grafana.
- **k8s/Helm** (prod): Deployment'ы (HPA по CPU/queue-lag), Service, ConfigMap/Secret,
  liveness/readiness probes, PodDisruptionBudget, миграции как init-job.
- Мультистейдж **Dockerfile**, `.dockerignore`, pinned-зависимости (requirements/poetry — предложи).
- **CI/CD** GitHub Actions: lint → mypy → tests(pgvector) → build → (опц.) push.
- **Makefile/Taskfile**: `up`, `test`, `lint`, `typecheck`, `migrate`, `seed`, `eval`, `load-test`.
- `.env.example` с комментариями по каждому флагу; сид-скрипт демо-данных (города, топики, синтетические события).
- `ARCHITECTURE.md` (диаграмма слоёв + поток данных + обоснование каждого тяжёлого компонента), `README.md` (запуск).

## Тестирование

- **Unit** — чистый домен и скореры без БД (детерминизм, `seed=42`).
- **Integration** — репозитории/pgvector/очередь/outbox через **testcontainers**.
- **Contract/API** — httpx против поднятого приложения.
- **Load** — locust/k6 смоук хот-путей (recommendations, nl-search).
- **Eval** — offline-скрипты рекомендера (см. выше).
- `ruff` + `mypy(strict)` — блокирующие шаги CI. Покрытие ядра рекомендера и LLM Gateway обязательно.

## Соглашения по коду

- Async I/O везде, где есть I/O. Никаких `print` — только structlog.
- При ошибке в транзакции — `rollback` (урок v1); БД только через репозитории/UoW; LLM только через Gateway.
- Каждый источник/скорер/провайдер — за интерфейсом, регистрируется в реестре.
- Комментарии и доменные термины можно на русском; идентификаторы — на английском.
- Не коммитить `.env`, локальные БД, кэши моделей, `data/`.

## Предлагаемый план по milestone'ам (уточни в plan mode)

- **M0. Скелет + инфра.** Слои, compose (pg+redis+prometheus+grafana), config+validation,
  structlog+OTel, health/ready, graceful shutdown, CI (lint+mypy+пустые тесты), первая Alembic-миграция.
  → `docker compose up` работает, метрики видны в Grafana.
- **M1. Домен + хранилище.** Агрегаты, репозитории-порты + async-реализация, UoW+outbox,
  pgvector-колонки/индексы, seed-скрипт, integration-тесты на testcontainers.
- **M2. LLM Gateway + EmbeddingProvider.** Провайдер-цепочка, breaker, cooldown, учёт токенов,
  structured-output; unit-тесты fallback/cooldown на фейковых провайдерах.
- **M3. Ingestion pipeline.** `EventSource`-реестр, очередь + worker-нормализация (LangGraph),
  идемпотентность, ретраи, DLQ, статусы raw_events, 2–3 источника.
- **M4. Рекомендер.** CandidateGenerator (pgvector kNN) + скореры + MMR/anti-flood,
  предпосчёт кандидатов в worker'е, read-only `GET /api/v1/recommendations`, кэш+инвалидация.
- **M5. Бот.** aiogram поверх API: лента, feedback, NL-поиск, карточка «Подробнее», дайджест (scheduler→queue).
- **M6. Прод-готовность + eval.** k8s/Helm + HPA, Grafana-дашборды/алерты, load-test,
  offline-eval + ablations, ARCHITECTURE.md, нагрузочный смоук.

---

**Первый шаг:** войди в plan mode, задай мне уточняющие вопросы по развилкам
(очередь: arq / Celery / faststream; poetry vs requirements; отдельный
inference-сервис эмбеддингов сейчас или позже; auth: JWT+API-key или пока
только API-key; какие 2–3 источника ingestion первыми) и предложи детальный
план M0–M1. Код не пиши до моего «go».
