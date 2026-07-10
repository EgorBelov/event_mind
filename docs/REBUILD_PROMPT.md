# Промпт для Claude Code: EventMind v2 — мультиканальная, production-grade, scalable

> Вставь весь текст ниже первым сообщением в новой сессии Claude Code
> **в репозитории, где лежит код v1** (текущий `event_mind`). v1 нужен как
> **read-only справочник** — из него портируем доменную логику (см. раздел
> «Что портировать из v1»), но НЕ наследуем его архитектуру. Первым делом
> перенеси весь v1 в каталог `legacy/` (`git mv`), чтобы он остался рядом
> как референс, а v2 строй в чистом корне репозитория.
>
> Это контракт на серию итераций, а не «сделай всё за раз»: сначала
> утверждаем архитектуру и скелет, дальше наполняем по вертикальным срезам.
> На каждом milestone — рабочий `docker compose up`, зелёные тесты,
> обновлённые доки, отдельный коммит.

---

## Роль и цель

Ты — ведущий инженер, поднимающий с нуля **EventMind v2**: систему агрегации
IT-мероприятий и персональных рекомендаций. Это магистерский проект, но цель —
**настоящий большой масштабируемый продукт продакшн-уровня**, а не прототип.

Система **не завязана на Telegram**. У пользователя есть аккаунт, к которому
привязаны разные каналы доставки (email, Telegram, позже web-push и др.), а
**основной интерфейс — адаптивное веб-приложение**. Telegram — лишь один из
каналов и вторичный интерактивный клиент, а не ось системы.

**Инженерная честность:** каждый «тяжёлый» компонент (очередь, брокер, кэш,
трейсинг, канал доставки) вводится, только если решает конкретную проблему
масштабирования/надёжности — с обоснованием в `ARCHITECTURE.md`. Никакого
карго-культа: не пили швы, которые не разрежешь.

## Режим работы

1. Сначала **войди в plan mode**: предложи архитектуру + план по milestone'ам,
   задай уточняющие вопросы по развилкам. Не пиши код до моего «go».
2. Каждый milestone: рабочий compose, зелёные тесты (unit+integration),
   обновлённые `README.md`/`ARCHITECTURE.md`, отдельный коммит.
3. На развилках с архитектурными последствиями — спрашивай явным вопросом
   с вариантами, не решай молча.
4. Никаких `TODO позже` в ядре: компонент из плана обязан иметь тест.

## Домен

EventMind собирает IT-события из внешних источников, нормализует их через LLM
и рекомендует пользователям, доставляя выдачу по выбранным каналам. Сущности:
`User` (**аккаунт**, не Telegram!), `UserChannel` (привязанные каналы
доставки), `NotificationPreference`, `Event`, `RawEvent` (сырое до
нормализации), `Topic`, `Interaction` (like/dislike/save), профиль интересов,
эмбеддинги пользователя и события.

Рекомендер — гибрид из pluggable-скореров за единым интерфейсом (rule-based,
cosine по эмбеддингам, Thompson sampling, LLM-оценки quality/hype,
freshness-decay, skill-gap, LinUCB-бандит, LightGCN, MMR-rerank + анти-флуд
серий). Это научная корона проекта (глава с оценкой качества).

## Что портировать из v1 (в `legacy/`) — НЕ переизобретать

v1 — рабочая система, вылизанная за много итераций. Архитектуру берём новую,
но следующую доменную логику **портируем/адаптируем**, а не выдумываем заново.
Прежде чем писать соответствующий модуль, прочитай оригинал в `legacy/` и
перенеси суть (очистив от старой архитектуры и синхронного I/O):

- **Математика рекомендера**: bayesian temporal-decay, LinUCB-бандит,
  skill-gap, извлечение `series_slug`, пороги dedup (~0.92), веса скоринга,
  MMR (λ≈0.7), freshness half-life. Оригинал: `legacy/app/recommender/*`.
- **LLM-промпты** (ловились эмпирически, критичны): системный промпт
  нормализатора событий с фильтром не-IT/не-событий; схема extract'а для
  NL-поиска (`SearchFilters`); event-explain; оценки quality/hype. Оригинал:
  `legacy/app/agents/*`, `legacy/app/api/services/nl_search_service.py`.
- **Парсеры источников** со всеми квирками: habr, rss, kudago, luma, meetup,
  timepad, telegram. Оригинал: `legacy/app/ingestion/sources/*`.
- **Канонизация**: city-алиасы (msk→moscow, piter→spb), нормализация
  event_type/format по closed-домену, таксономия топиков. Оригинал:
  `legacy/app/core/topics.py`, city-canonicalization.
- **Фильтры выдачи**: upcoming-only (NULL-сейф), локализация дат (raw
  `start_at` до конвертации зоны). Оригинал: `legacy/app/db/event_filters.py`,
  `legacy/app/bot/utils.py`.
- **Eval-скрипты** (`seed=42`, воспроизводимость): offline leave-one-out и
  LLM-judge на синтетическом датасете. Оригинал: `legacy/scripts/eval_*`.
- **Тесты как спецификация**: 369 кейсов в `legacy/tests/` — готовый чек-лист
  ожидаемого поведения. Переписывай тесты под новую архитектуру, но сверяйся
  с их сценариями, чтобы не потерять граничные случаи.

Чего НЕ портировать: слои/структуру v1, синхронный SQLAlchemy, module-dict
состояние, JSON-эмбеддинги, самописную LLM-обвязку, Telegram-центричную
идентичность — всё это заменяется новой архитектурой из этого промпта.

## Две независимые оси: интерфейсы и каналы доставки

Не путать эти понятия — это ключ к развязке от Telegram:

**Интерактивные клиенты** (пользователь сам заходит и листает):
- **Веб-приложение (Next.js)** — основной интерфейс: лента рекомендаций,
  профиль/интересы, NL-поиск, карточка события, настройки каналов и подписок,
  in-app «инбокс» уведомлений. Адаптивный/responsive, PWA-ready.
- **Telegram-бот** — вторичный клиент, привязывается к аккаунту.
- Оба потребляют **один и тот же `/api/v1`**, никакой логики на клиенте.

**Каналы доставки** (система сама пушит дайджест/уведомление):
- Порт **`NotificationChannel.send(user, message)`**; реализации выбираются по
  `NotificationPreference` пользователя, контент рендерится под канал.
- **На старте**: `EmailChannel` (HTML-дайджесты), `TelegramChannel`,
  **in-app** (лента/инбокс в вебе). **Web-push — позже**, но абстракция и
  data-model закладываются под него сразу (Service Worker + VAPID).
- Добавить канал = новый адаптер, ядро не трогаем (тот же плагин-подход, что
  для источников ingestion и скореров).

## Идентичность и аутентификация (центральная, не Telegram-bound)

- **`User`** — аккаунт с email; вход через **JWT/OAuth2** (email+пароль и/или
  соц-логин Google). Email-верификация, сброс пароля.
- **`UserChannel`** — `{user_id, type: email|telegram|webpush, address/chat_id,
  verified, enabled}`. Один аккаунт — несколько каналов.
- **Привязка Telegram** — через **deep-link токен**: в вебе жмёшь «привязать
  Telegram» → одноразовый токен → `/start <token>` в боте связывает `chat_id`
  с аккаунтом. Бот больше не создаёт «пользователя из воздуха».
- **`NotificationPreference`** — какие каналы включены, частота дайджеста,
  тихие часы, типы уведомлений.
- Внутренние вызовы (бот↔API, worker↔API) — по внутреннему **API-key**
  (`hmac.compare_digest`), пользовательские — по JWT.

## Уроки v1, которые чинит v2

| Боль v1 | Решение v2 |
|---|---|
| `telegram_id` = первичный ключ пользователя | **Аккаунт-центричная модель**, Telegram — привязанный канал |
| Эмбеддинги как JSON-текст, pgvector доклеен позже | **pgvector с день 1**, `vector`-тип, HNSW-индексы |
| Скоринг синхронно в hot-path, залатан TTL-кэшем | **Two-stage: candidate generation → ranking**, предпосчёт в фоне, hot-path read-only |
| Ingestion + LLM-нормализация в процессе API/scheduler | **Очередь + worker-пул**, идемпотентность, ретраи, DLQ |
| Состояние в module-dict, терялось при рестарте | **Stateless-процессы**, состояние в Postgres/Redis, горизонтальное масштабирование |
| Синхронный SQLAlchemy + блокирующий httpx | **async сверху донизу** |
| SQLite/Postgres дуализм, тесты цепляются за живую БД | Postgres везде, integration-тесты через **testcontainers** |
| Самописная LLM-цепочка, размазанная по коду | Единый **LLM Gateway** за портом |
| Доставка только в Telegram, вшита в хендлеры | **Мультиканальная доставка** за портом `NotificationChannel` |
| Нет наблюдаемости кроме access-лога | **Structured logs + OpenTelemetry + Prometheus + Grafana** |

## Целевая архитектура

**Модульный монолит бэкенда с гексагональными границами** (ports & adapters) +
**отдельный фронтенд-SPA/SSR (Next.js)**. Слои бэкенда:

```
domain/          # чистые сущности, value-objects, доменные сервисы. Без I/O и фреймворков.
application/     # use-cases + порты (репозитории, шины, gateway'и, каналы) + оркестрация.
infrastructure/  # адаптеры: async-SQLAlchemy-репозитории, LLM Gateway, EmbeddingProvider,
                 #           очередь, кэш, outbox, NotificationChannel'ы, HTTP-клиенты источников, телеметрия.
interfaces/      # входные адаптеры: FastAPI-роутеры, aiogram-хендлеры, worker/scheduler, CLI.
```

Правило зависимостей: `interfaces → application → domain`; `infrastructure`
реализует порты `application`; `domain` наружу не импортирует.

### Процессы (каждый — отдельный контейнер, stateless, реплицируемый)
- **api** — FastAPI (async), оркестрация use-case'ов, `/api/v1`, CORS под веб-клиент,
  JWT-auth, graceful shutdown, liveness/readiness.
- **web** — **Next.js** приложение (SSR/SEO для публичных страниц событий + PWA).
- **bot** — aiogram 3, ходит в API по HTTP.
- **worker** — пул потребителей очереди: ingestion, LLM-нормализация, backfill
  эмбеддингов, пересчёт кандидатов, **рассылка по каналам**. Идемпотентность, ретраи, DLQ.
- **scheduler** — раскладывает периодические задачи в очередь (cron→queue),
  лидер-лок в Redis от двойного запуска.

### Хранилища и инфраструктура
- **PostgreSQL 16 + pgvector** — источник правды + kNN (HNSW). Пул соединений,
  `pool_pre_ping`, стратегия под read-replica на будущее.
- **Redis** — брокер очереди, многоуровневый кэш, rate-limit, лидер-локи, эфемерное состояние.
- **Outbox-паттерн** — надёжная публикация доменных событий (запись в БД в той
  же транзакции → релей в очередь), чтобы не терять задачи/рассылки при сбоях.
- Очередь: предложи и обоснуй (**arq** дефолт — нативно async/лёгкий; Celery — зрелость; faststream — event-driven).

## Технологический стек

**Бэкенд (Python 3.12):** FastAPI + uvicorn/gunicorn (async), Pydantic v2,
SQLAlchemy 2.0 async + Alembic + pgvector, aiogram 3, arq/Celery + Redis,
LangGraph (только графовые сценарии: нормализация, агентные диалоги — за
портом), sentence-transformers (MiniLM 384-dim, multilingual) за
`EmbeddingProvider`, OpenTelemetry + prometheus-client + structlog, pytest +
pytest-asyncio + testcontainers, ruff + mypy(strict). Email: SMTP/провайдер
(Resend/SendGrid/SES) за `EmailChannel`.

**Фронтенд:** **Next.js (React)** + TypeScript, адаптивный/responsive,
SSR/SEO для публичных страниц событий, PWA (под будущий web-push), типизированный
API-клиент (генерация из OpenAPI-схемы FastAPI), auth через JWT (httpOnly-cookie).

**Инфра/деплой:** Docker (multi-stage) + docker-compose (dev) + k8s-манифесты/Helm
(prod-ready, HPA), GitHub Actions CI/CD (lint+mypy+tests(pgvector)+build фронта и бэка),
нагрузочное тестирование locust/k6, Grafana-дашборды.

## Ключевые абстракции (порты в `application`)

1. **`LLMGateway`** — `complete()`, `structured_output(schema)`, `bind_tools()`.
   Внутри: цепочка Gemini → Groq 70b → Groq 8b, per-provider cooldown,
   circuit-breaker, retry, таймауты, учёт токенов/стоимости, метрики.
2. **`EmbeddingProvider`** — `embed_texts(...)`, батчинг, кэш, версия модели; выносим в сервис позже.
3. **`EventSource`** — контракт источника ingestion; habr, rss, kudago, luma,
   meetup, telegram, timepad. Плагин-реестр.
4. **`NotificationChannel`** — `send(user, rendered_message)`; email/telegram/in-app
   (web-push позже). Выбор по `NotificationPreference`, рендер под канал.
5. **Репозитории-порты** на агрегат; async-SQLAlchemy-реализация в infrastructure; домен не знает про ORM.
6. **`TaskQueue`** — `enqueue(job, payload)` + идемпотентные ключи.
7. **`Cache`** — типизированный Redis (TTL, инвалидация по тегам).
8. **`UnitOfWork`** — транзакционная граница + запись в outbox в той же транзакции.

## Рекомендер (ядро тезиса + масштабируемость)

Двухстадийно, каждый компонент pluggable, включается флагом, в try/except:
- **CandidateGenerator** — pgvector kNN по user-embedding + фильтры (upcoming,
  город/формат), ограничение до N. Масштабируется на рост каталога.
- **Scorers** — единый интерфейс `score(user_ctx, candidates) -> dict[event_id, float]`:
  rule, cosine, bayesian, quality, hype, freshness, skill_gap, bandit (LinUCB), gnn (LightGCN).
- **Reranker** — MMR (λ) + series anti-flood.
- **Предпосчёт** кандидатов в worker'е, инвалидация по feedback/edit-профиля;
  `GET /api/v1/recommendations` — read-only.
- **Мультиканальная доставка**: тот же ранкинг питает и in-app ленту, и
  email-дайджест, и Telegram-пуш — рендер под канал, логика скоринга одна.
- **Online-обучение** через бандит/Thompson по интеракциям.
- **Offline-eval harness** (`eval/`): воспроизводимо (`seed=42`), leave-one-out
  на синтетике — Recall@k, nDCG@k, MAP, coverage, diversity, novelty + LLM-as-judge,
  config-driven ablations. Результаты → таблицы/фигуры для главы отчёта.

## Модель данных

Агрегаты (уточни поля в плане): `users` (аккаунт+auth), `user_channels`,
`notification_preferences`, `events`, `raw_events`, `topics` +
`user_topics`/`event_topics`, `interactions`, `user_topic_stats`,
`user_bandit_state`, `user_skill_profile`, `user_memory`,
`recommendation_candidates` (предпосчёт), `notifications` (in-app инбокс + лог
доставки), `outbox`.

Требования: эмбеддинги — `vector(384)` + HNSW; даты — `start_at: timestamptz` +
человекочитаемая строка; `series_slug` (индекс); все FK/уникальные/индексы под
hot-path с день 1; продумать **партиционирование `interactions`/`notifications`**
по времени под объём; первая Alembic-миграция создаёт консистентную схему целиком.

## Надёжность, наблюдаемость, безопасность

- **Надёжность**: идемпотентные джобы, ретраи с backoff, **DLQ**, outbox,
  graceful shutdown с дренажом очереди, backpressure, health/ready (`/health`, `/ready` — БД+Redis).
- **Отказоустойчивость**: сбой LLM/источника/скорера/канала не роняет запрос — деградация + circuit-breaker.
- **Наблюдаемость**: structlog JSON с request-id/trace-id; OpenTelemetry
  (HTTP→app→БД→LLM, корреляция api↔worker); Prometheus (latency рекомендаций,
  hit-rate кэша, токены/стоимость LLM, длина очереди, доставки/ошибки по каналам) + Grafana + алерты.
- **Безопасность**: JWT/OAuth2 для пользователей + внутренний API-key,
  rate-limit на Redis, версионирование API, whitelisted health/docs, секреты
  вне репозитория, **prompt-safety** (sanitize + границы user-text перед LLM),
  верификация email/каналов перед рассылкой (анти-абьюз, unsubscribe-ссылки в письмах).
- **fail-fast config validation** на старте каждого процесса (код выхода 78).

## Деплой и дев-опыт

- **docker-compose.yml** (dev): postgres(pgvector) + redis + api + web + bot +
  worker + scheduler + prometheus + grafana + mailhog (перехват писем в dev).
- **k8s/Helm** (prod): Deployment'ы (HPA по CPU/queue-lag), Service, Ingress
  (веб+api), ConfigMap/Secret, probes, PDB, миграции как init-job.
- Мультистейдж Dockerfile'ы (бэк и фронт), `.dockerignore`, pinned-зависимости.
- **CI/CD** GitHub Actions: lint → mypy → tests(pgvector) → build образов (api/web/bot/worker).
- **Makefile/Taskfile**: `up`, `test`, `lint`, `typecheck`, `migrate`, `seed`, `eval`, `load-test`.
- `.env.example` с комментариями; сид-скрипт демо-данных; `ARCHITECTURE.md`
  (диаграмма слоёв + поток данных + обоснование тяжёлых компонентов), `README.md`.

## Тестирование

- **Unit** — чистый домен и скореры без БД (детерминизм, `seed=42`).
- **Integration** — репозитории/pgvector/очередь/outbox/каналы через testcontainers.
- **Contract/API** — httpx против поднятого приложения; фронт — типы из OpenAPI.
- **Load** — locust/k6 смоук хот-путей. **Eval** — offline-скрипты рекомендера.
- `ruff` + `mypy(strict)` — блокирующие в CI. Покрытие ядра рекомендера, LLM Gateway, каналов обязательно.

## Соглашения по коду

- Async I/O везде, где есть I/O. Никаких `print` — только structlog.
- При ошибке в транзакции — `rollback`; БД только через репозитории/UoW; LLM только через Gateway; доставка только через `NotificationChannel`.
- Каждый источник/скорер/провайдер/канал — за интерфейсом, регистрируется в реестре.
- Комментарии и доменные термины можно на русском; идентификаторы — на английском.
- Не коммитить `.env`, локальные БД, кэши моделей, `data/`.

## Предлагаемый план по milestone'ам (уточни в plan mode)

- **M0. Скелет + инфра.** Перенос v1 в `legacy/` (`git mv`), слои бэка, каркас Next.js, compose (pg+redis+prometheus+grafana+mailhog),
  config+validation, structlog+OTel, health/ready, graceful shutdown, CI, первая Alembic-миграция.
  → `docker compose up` поднимает веб+api, метрики в Grafana.
- **M1. Аккаунты + auth + домен.** `User`/`UserChannel`/`NotificationPreference`,
  JWT/OAuth2, email-верификация, привязка Telegram deep-link'ом, репозитории+UoW+outbox,
  pgvector-колонки/индексы, seed, integration-тесты.
- **M2. LLM Gateway + EmbeddingProvider.** Провайдер-цепочка, breaker, cooldown, structured-output, unit-тесты fallback.
- **M3. Ingestion pipeline.** `EventSource`-реестр, очередь + worker-нормализация (LangGraph),
  идемпотентность, ретраи, DLQ, статусы raw_events, 2–3 источника.
- **M4. Рекомендер.** CandidateGenerator + скореры + MMR/anti-flood, предпосчёт,
  read-only `GET /api/v1/recommendations`, кэш+инвалидация.
- **M5. Мультиканальная доставка.** `NotificationChannel` (email+telegram+in-app),
  `NotificationPreference`, дайджест scheduler→queue→рассылка, in-app инбокс, unsubscribe.
- **M6. Веб-клиент.** Next.js: лента, профиль/интересы, NL-поиск, карточка события,
  настройки каналов, инбокс; типизированный API-клиент; auth-flow.
- **M7. Telegram-бот.** aiogram поверх API: привязка аккаунта, лента, feedback, NL-поиск.
- **M8. Прод-готовность + eval.** k8s/Helm + HPA, дашборды/алерты, load-test, offline-eval + ablations, доки.

---

**Первый шаг:** войди в plan mode, задай уточняющие вопросы по развилкам
(очередь: arq / Celery / faststream; poetry vs requirements; email-провайдер:
Resend / SendGrid / SES / чистый SMTP; соц-логин: только email+пароль или сразу
Google OAuth; монорепо vs отдельные репозитории под бэк и фронт; какие 2–3
источника ingestion первыми) и предложи детальный план M0–M1. Код не пиши до моего «go».
