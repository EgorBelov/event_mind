# Промпт для Claude Code: перезапуск EventMind v2 (магистерская, scalability-first)

> Вставь весь текст ниже как первое сообщение в новой сессии Claude Code
> в **пустом репозитории**. Это не техзадание «на один заход», а контракт
> на серию итераций: сначала утверждаем архитектуру и скелет, потом
> наполняем по вертикальным срезам. Не пиши весь код сразу — работай
> инкрементально, milestone за milestone, с зелёными тестами на каждом шаге.

---

## Роль и режим работы

Ты — ведущий инженер, поднимающий с нуля **EventMind v2** — систему
агрегации IT-мероприятий и персональных рекомендаций. Это исследовательский
проект магистерской работы, поэтому важны и продакшн-качество, и
воспроизводимость экспериментов.

Работай так:
1. Сначала **войди в plan mode** и предложи архитектуру + план по
   milestone'ам. Дождись моего «go», не начинай писать код до утверждения.
2. Каждый milestone заканчивается: рабочий `docker compose up`, зелёные
   тесты, обновлённый `README`/`ARCHITECTURE.md`, отдельный коммит.
3. На каждой развилке, где решение влияет на архитектуру, спрашивай меня
   через явный вопрос с вариантами, а не выбирай молча.
4. Никаких заглушек «TODO позже» в ядре — если компонент в плане, он
   должен иметь тест.

## Контекст предметной области (что уже понятно из v1)

EventMind собирает IT-события из разных источников, нормализует их через
LLM и рекомендует пользователям в Telegram-боте. Есть три роли процессов:
публичный **API**, **бот** и фоновый **worker** (дайджесты, ingestion,
пересчёт эмбеддингов). Домен переносим, но **код v1 не переиспользуем** —
только идеи. Ключевые доменные сущности: `User`, `Event`, `RawEvent`
(сырое до нормализации), `Topic`, `Interaction` (like/dislike/save),
профиль интересов пользователя, эмбеддинги пользователя и события.

Рекомендер v1 — гибрид из ~9 компонент (rule-based, cosine по эмбеддингам,
Thompson sampling, LLM-оценки quality/hype, freshness-decay, skill-gap,
LinUCB-бандит, LightGCN, MMR-rerank + анти-флуд по сериям событий). Логику
рекомендаций сохраняем как **набор pluggable-скореров за единым
интерфейсом**, а не как переплетённый монолит.

## Что в v1 болело и что чинит v2 (это цель переписывания)

| Боль v1 | Решение в v2 |
|---|---|
| Эмбеддинги как JSON-текст в колонке, доклеенный pgvector позже | **pgvector с первого дня**, `vector` — единственный тип эмбеддинга, HNSW-индексы |
| Гибридный скоринг синхронно в hot-path `GET /recommendations`, потом залатано TTL-кэшем | Разделение **candidate generation → ranking**, предпосчёт кандидатов в фоне, hot-path только читает |
| Ingestion + LLM-нормализация в процессе API/scheduler | Вынести в **очередь задач** (worker'ы), API только ставит job и отдаёт статус |
| Самописная LLM-цепочка с circuit-breaker'ами, разбросанная по коду | Единый **LLM Gateway** (провайдер-абстракция, retry/fallback/breaker внутри, метрики), остальной код зависит от интерфейса |
| Синхронный SQLAlchemy, блокирующий httpx | **async сверху донизу**: async SQLAlchemy 2.0, async httpx, async aiogram |
| SQLite/Postgres дуализм, тесты цепляются за реальную БД | Postgres везде, интеграционные тесты через **testcontainers**, чистые unit-тесты домена без БД |
| Состояние в module-dict (курсор ленты терялся при рестарте) | Всё состояние — в БД/Redis, процессы **stateless и горизонтально масштабируемы** |
| Нет наблюдаемости кроме access-лога | **structured logging + OpenTelemetry traces + Prometheus-метрики** |
| Конфиг и секреты вперемешку | 12-factor, `pydantic-settings`, fail-fast валидация на старте каждого процесса |

## Целевая архитектура

Модульный монолит с **гексагональными границами**, готовый к вырезанию
сервисов, но без преждевременного микросервисного дробления. Слои:

```
domain/         # чистые сущности, value-objects, доменные сервисы. Без I/O, без фреймворков.
application/    # use-cases (ports): интерфейсы репозиториев, шины, gateway'ев + orchestration.
infrastructure/ # адаптеры: SQLAlchemy-репозитории, LLM Gateway, embedding provider, очередь, кэш, HTTP-клиенты источников.
interfaces/     # входные адаптеры: FastAPI-роутеры, aiogram-хендлеры, worker-энтрипоинты, CLI.
```

Правило зависимостей: `interfaces → application → domain`, `infrastructure`
реализует порты из `application`. `domain` не импортирует ничего наружу.

### Процессы (каждый — отдельный контейнер, stateless, реплицируемый)
- **api** — FastAPI (async), только оркестрация use-case'ов, версионирование `/api/v1`.
- **bot** — aiogram 3, ходит в API по HTTP (никакого прямого доступа к БД).
- **worker** — потребитель очереди задач (ingestion, нормализация,
  backfill эмбеддингов, пересчёт кандидатов рекомендаций).
- **scheduler** — только ставит периодические задачи в очередь (cron→queue),
  сам ничего тяжёлого не делает.

### Хранилища
- **PostgreSQL + pgvector** — основное хранилище + векторный поиск (HNSW).
- **Redis** — брокер очереди, кэш, rate-limit, эфемерное состояние диалогов бота.
- Очередь задач: выбери и обоснуй в плане (кандидаты: **arq**, **Celery**,
  **faststream**). По умолчанию предложи `arq` (нативно async, лёгкий) —
  но вынеси на моё утверждение.

## Технологический стек (Python 3.12)

- **FastAPI** + **uvicorn** (async), Pydantic v2 / pydantic-settings.
- **SQLAlchemy 2.0 async** + **Alembic** (async-совместимые миграции), **pgvector**.
- **aiogram 3** для бота.
- **arq/Celery** + Redis для фоновых задач.
- **LangGraph** оставляем только для реально графовых сценариев (нормализация,
  агентные диалоги), но за портом `application`. Простые LLM-вызовы — через
  LLM Gateway напрямую, без graph-обвязки.
- **sentence-transformers** (MiniLM, 384-dim, multilingual) за интерфейсом
  `EmbeddingProvider` — чтобы модель можно было заменить/вынести в отдельный сервис.
- **pytest** + **pytest-asyncio** + **testcontainers[postgres]** + **httpx**-тесты, **ruff** + **mypy**.
- **OpenTelemetry** (traces), **prometheus-client** (метрики), **structlog** (JSON-логи).
- **Docker** + **docker-compose** (dev), Makefile/taskfile для команд.
- CI: GitHub Actions — lint + type-check + tests на pgvector-контейнере.

## Ключевые абстракции (порты в `application`)

Спроектируй как явные интерфейсы (Protocol/ABC), реализация в `infrastructure`:

1. **`LLMGateway`** — `complete()`, `structured_output(schema)`, `bind_tools()`.
   Внутри: цепочка провайдеров (Gemini → Groq 70b → Groq 8b как в v1),
   per-provider cooldown, circuit-breaker, retry, таймауты, учёт токенов,
   экспорт метрик. Весь остальной код зависит **только** от этого интерфейса.
2. **`EmbeddingProvider`** — `embed_texts(list[str]) -> list[Vector]`,
   батчинг, кэш, версия модели в метаданных вектора.
3. **`EventSource`** — общий контракт источника ingestion (`fetch() -> list[RawEvent]`);
   реализации: habr, rss, kudago, luma, meetup, telegram, timepad. Регистрация
   через плагин-реестр, добавление источника не трогает ядро.
4. **`Repository`-порты** на агрегат (`UserRepo`, `EventRepo`, `InteractionRepo`,
   `RawEventRepo`, …) — интерфейс в `application`, async-SQLAlchemy-реализация
   в `infrastructure`. Доменные сервисы не знают про SQLAlchemy.
5. **`TaskQueue`** — `enqueue(job, payload)`; абстрагирует arq/Celery.
6. **`Cache`** — типизированный доступ к Redis (TTL, инвалидация по тегам).
7. **`Recommender`-пайплайн** — `CandidateGenerator` (retrieval: pgvector kNN +
   фильтры свежести/города) → список **`Scorer`** (rule, cosine, bayesian,
   quality, hype, freshness, skill_gap, bandit, gnn) → **`Reranker`** (MMR +
   series anti-flood). Каждый scorer: `score(user_ctx, candidates) -> dict[event_id, float]`,
   веса из конфига, любой scorer в try/except (сбой одного не рушит выдачу),
   легко включается/выключается флагом. Ранкинг предпосчитывается в worker'е и
   кэшируется; `GET /recommendations` — read-only.

## Модель данных (переносим и чистим)

Стартовые агрегаты (уточни поля в плане): `users`, `events`, `raw_events`,
`topics` + связи `user_topics`/`event_topics`, `interactions`,
`user_topic_stats`, `user_bandit_state`, `user_skill_profile`,
`user_memory`, `recommendation_cache`/`recommendation_candidates`.

Требования к схеме:
- Эмбеддинги — колонки `vector(384)` (pgvector), а не текст. HNSW-индекс.
- `telegram_id` — `BIGINT` сразу.
- Даты событий: хранить и распарсенный `start_at: timestamptz`, и человекочитаемую строку.
- `series_slug` для анти-флуда серий — с индексом.
- Все FK, уникальные ограничения и индексы под hot-path запросы — с первого дня.
- Alembic: первая миграция создаёт консистентную схему целиком (не 14 наслоений).

## Наблюдаемость, надёжность, безопасность

- **Structured JSON-логи** (structlog), request-id/trace-id в каждой строке,
  корреляция API→worker через контекст.
- **OpenTelemetry**: трейсы HTTP-запросов, обращений к БД, к LLM Gateway.
- **Prometheus**: latency рекомендаций, hit-rate кэша, токены/стоимость LLM
  по провайдерам, длина очереди, ошибки источников ingestion.
- **API-security**: `X-API-Key` middleware (`hmac.compare_digest`,
  whitelisted health/docs), rate-limit на Redis, версионирование API.
- **Prompt-safety**: любой пользовательский ввод в LLM оборачивать
  через sanitize + явные user-text границы (перенести идею из v1).
- **Graceful degradation**: сбой LLM/источника/скорера не роняет запрос,
  а логируется и деградирует функциональность.
- **Health/readiness**: `/health` (liveness) и `/ready` (проверка БД+Redis).
- **fail-fast config validation** на старте каждого процесса (код выхода 78).

## Тестирование и качество

- **Unit** — чистый домен и скореры без БД (быстро, детерминировано, `seed=42`).
- **Integration** — репозитории/pgvector/очередь через **testcontainers**.
- **Contract/API** — httpx против поднятого приложения.
- **Eval-скрипты** для магистерской: воспроизводимый offline-eval
  (leave-one-out: Recall@k, nDCG@k) на синтетическом датасете с фиксированным
  seed + LLM-as-judge. Вынести в `eval/`, результаты — в отчёт.
- Покрытие ядра рекомендера и LLM Gateway — обязательно.
- `ruff` + `mypy` в CI как блокирующие шаги.

## Дев-опыт и деплой

- `docker-compose.yml`: postgres(pgvector) + redis + api + bot + worker + scheduler.
- `.env.example` с комментариями по каждому флагу (как в v1, но чище).
- `Makefile`/`Taskfile`: `up`, `test`, `lint`, `migrate`, `seed`, `eval`.
- Сид-скрипт с демо-данными (города, топики, синтетические события) для быстрого старта.
- `ARCHITECTURE.md` (диаграмма слоёв + поток данных) и `README.md` (запуск).
- Мультистейдж Dockerfile, `.dockerignore`, pinned-зависимости (`requirements` или poetry — предложи).

## Предлагаемый план по milestone'ам (уточни в plan mode)

- **M0. Скелет.** Структура слоёв, compose (pg+redis), config+validation,
  логирование/трейсинг, health/ready, CI (lint+type+пустые тесты), первая
  Alembic-миграция. → `docker compose up` работает.
- **M1. Домен + хранилище.** Агрегаты, репозитории-порты + async-реализация,
  pgvector-колонки и индексы, seed-скрипт, интеграционные тесты на testcontainers.
- **M2. LLM Gateway + EmbeddingProvider.** Провайдер-цепочка, breaker, метрики,
  structured-output; юнит-тесты на fallback/cooldown с фейковыми провайдерами.
- **M3. Ingestion pipeline.** `EventSource`-реестр, очередь, worker
  нормализации (LangGraph), идемпотентность, статусы raw_events, 2–3 источника.
- **M4. Рекомендер.** CandidateGenerator (pgvector kNN) + скореры + MMR/anti-flood,
  предпосчёт кандидатов в worker'е, read-only `GET /api/v1/recommendations`, кэш.
- **M5. Бот.** aiogram-хендлеры поверх API: лента, feedback, NL-поиск,
  карточка события «Подробнее», дайджест (через scheduler→queue).
- **M6. Eval + наблюдаемость + доки.** Offline-eval, дашборд метрик,
  ARCHITECTURE.md, нагрузочный смоук.

## Соглашения по коду

- Никаких `print` — только логгер. Async I/O везде, где есть I/O.
- При ошибке в транзакции — обязательный `rollback` (перенос урока v1).
- Доступ к БД — только через репозитории; доступ к LLM — только через Gateway.
- Каждый источник/скорер/провайдер — за своим интерфейсом, регистрируется в реестре.
- Комментарии и доменные термины можно на русском (проект русскоязычный),
  идентификаторы — на английском.
- Не коммитить `.env`, локальные БД, кэши моделей, `data/`.

---

**Первый шаг:** войди в plan mode, задай мне уточняющие вопросы по развилкам
(очередь задач; poetry vs requirements; отдельный сервис эмбеддингов сейчас
или позже; какие 2–3 источника ingestion делаем первыми) и предложи
детальный план M0–M1. Код не пиши до моего «go».
