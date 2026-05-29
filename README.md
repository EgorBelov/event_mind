# EventMind

**EventMind** — система агрегации IT-мероприятий и персонализированных
AI-рекомендаций. Состоит из FastAPI-бэкенда, Telegram-бота на aiogram 3,
hybrid-рекомендера на 9 компонент, мульти-агентного AI-копилота на LangGraph
и планировщика фоновых задач (AI-дайджест, ingestion, compaction памяти) на
APScheduler.

---

## Содержание

1. [Идея и возможности](#идея-и-возможности)
2. [Архитектура](#архитектура)
3. [Структура проекта](#структура-проекта)
4. [Стек](#стек)
5. [Модель данных](#модель-данных)
6. [Установка и запуск](#установка-и-запуск)
7. [PostgreSQL + pgvector](#postgresql--pgvector)
8. [Переменные окружения](#переменные-окружения)
9. [Запуск компонентов](#запуск-компонентов)
10. [Docker](#docker)
11. [Telegram-бот: команды и сценарии](#telegram-бот-команды-и-сценарии)
12. [Логика рекомендаций](#логика-рекомендаций)
13. [Пайплайн ingestion](#пайплайн-ingestion)
14. [AI-агенты на LangGraph](#ai-агенты-на-langgraph)
15. [REST API](#rest-api)
16. [Admin-дашборд](#admin-дашборд)
17. [Тесты](#тесты)
18. [Миграции](#миграции)
19. [Минимальный happy-path](#минимальный-happy-path)

---

## Идея и возможности

Система решает три задачи:
- собирать анонсы IT-мероприятий из десятка разнородных источников и
  приводить их к единой структуре;
- строить персональную ленту с прозрачным объяснением «почему именно это»;
- вести мульти-туровый диалог с AI-помощником по карьерным задачам
  (план развития, объяснение события, разбор истории).

Реализованный функционал:
- 6 ingestion-источников: Habr (HTML), RSS/Atom, KudaGo (JSON), Lu.ma
  (ICS), Meetup (GraphQL), Telegram-каналы (web-preview);
- AI-нормализация сырых событий через Groq LLM с Pydantic-валидацией:
  `format / city / level / topics / tech_stack / seniority /
  quality_score / hype_score`;
- семантическая дедупликация — cosine ≥ 0.92 за последние 90 дней;
- настройка профиля через Telegram inline-мастер (темы → формат → город) +
  4-экранный onboarding-тур (`/start`, `/tour`) с возможностью пропустить;
- deep-linking `t.me/<bot>?start=event_<id>` — открывает карточку события
  сразу из ссылки;
- холодный старт через `/bio` — LLM с pydantic-валидацией извлекает
  skill-профиль и виртуально обновляет topic_weights;
- **hybrid recommender из 9 компонент:** rule + cosine + bayesian (Thompson)
  + quality + hype + freshness + skill_gap + bandit (LinUCB) + gnn
  (LightGCN, выключен по умолчанию);
- MMR-диверсификация (λ=0.7) поверх отсортированного списка;
- **AI-рекомендации**: hybrid отбирает top-N, один LLM-вызов с
  pydantic-схемой пишет объяснения батчем;
- **объяснимость двух уровней** в карточке события:
  - ❓ Почему — короткий LLM-ответ в поп-апе с привязкой к конкретному факту;
  - 📖 Подробнее — отдельное сообщение: развёрнутый разбор + 1–2 совета
    + числовая разбивка по компонентам + counterfactual;
- семантический и keyword-поиск (один запрос делает оба прохода
  параллельно через `/events/combined-search`);
- похожие события (по пересечению тем);
- `/undo` — откат последнего лайка/дизлайка/сохранения во **всех четырёх**
  подсистемах (topic_weights, Bayesian α/β, LinUCB A/b, long-term memory);
- **AI Copilot** — мульти-туровый Supervisor-Worker граф LangGraph с
  5 специалистами (recommendation, career_coach, roadmap, explainer,
  summary) и 5 function-calling tools; история диалога — в
  `copilot_sessions`, активная сессия живёт 15 минут;
- **long-term memory** (mem0-style): LLM пишет активные заметки от первого
  лица в `user_memories` — Copilot ссылается на них через `recall_about_user`;
- trending-аналитика (`/trending`) с ASCII-bar-графиком тем за 7 дней;
- подписки и AI-дайджест (интервал настраиваемый через
  `DIGEST_INTERVAL_MINUTES`);
- HTML admin-дашборд (`/admin/`) и `/analytics/*`;
- композитный `/health`: БД, embeddings warm-up, доступность Groq LLM;
- Alembic-миграции (10 ревизий, включая pgvector);
- автоматический fallback Groq: при сбое primary-модели запрос
  переключается на `groq_fallback_model`.

---

## Архитектура

```
┌─────────────────┐      HTTP        ┌────────────────────┐
│  Telegram Bot   │ ───────────────► │      FastAPI       │
│   (aiogram 3)   │ ◄─────────────── │    REST backend    │
└────────┬────────┘                  └──────────┬─────────┘
         │                                      │
         │ async httpx                          │ SQLAlchemy 2
         │                                      ▼
         │                            ┌────────────────────┐
         │                            │  SQLite / Postgres │
         │                            │   + pgvector       │
         │                            └─────────┬──────────┘
         │                                      │
┌────────▼─────────┐    invoke()      ┌─────────▼──────────┐
│   APScheduler    │ ───────────────► │  LangGraph agents  │
│ digest+ingest+   │                  │   (Groq LLM +      │
│ memory-compact   │                  │   fallback)        │
└──────────────────┘                  └─────────┬──────────┘
                                                │
                                                │ sentence-transformers
                                                ▼
                                      ┌────────────────────┐
                                      │ Hybrid Recommender │
                                      │   9 components     │
                                      └────────────────────┘
```

Три независимых процесса:
1. **api** (`uvicorn app.api.main:app`) — основной REST-сервис, держит БД
   и LLM-агентов.
2. **bot** (`python -m app.bot.main`) — Telegram-фронт, long-polling,
   общается с api по HTTP.
3. **scheduler** (`python -m app.scheduler.digest`) — APScheduler:
   `daily_digest`, `ingest_habr`, `ingest_rss`, `ingest_telegram`,
   `compact_memories`.

`bot` и `scheduler` ждут healthcheck'а `api` перед стартом (в `docker-compose`).

---

## Структура проекта

```text
eventmind/
├── app/
│   ├── api/
│   │   ├── main.py                          # FastAPI app + /health
│   │   ├── routers/                         # HTTP-роутеры по доменам
│   │   │   ├── users.py                     # /users/* — регистрация, профиль, bio
│   │   │   ├── events.py                    # /events/* — поиск, semantic-search, combined-search
│   │   │   ├── recommendations.py           # /recommendations/* — hybrid лента + interactions + why
│   │   │   ├── agent_recommendations.py     # /agent-recommendations/* — hybrid + LLM объяснения
│   │   │   ├── copilot.py                   # /copilot/* — one-shot + multi-turn AI-копилот
│   │   │   ├── ingestion.py                 # /ingestion/* — load-{habr,rss,...} + нормализация
│   │   │   ├── subscriptions.py             # /subscriptions/* — подписки на дайджест
│   │   │   ├── admin.py                     # /admin/ — HTML-дашборд
│   │   │   ├── analytics.py                 # /analytics/* — topics/interactions/trending
│   │   │   └── vocabulary.py                # /vocabulary/* — динамические словари
│   │   ├── schemas/                         # Pydantic-схемы
│   │   └── services/                        # бизнес-логика (вне роутеров)
│   │
│   ├── bot/
│   │   ├── main.py                          # Dispatcher, порядок router'ов
│   │   ├── handlers/                        # роутеры по сценариям
│   │   │   ├── start.py                     # /start, /tour, мастер настройки, /edit, /bio
│   │   │   ├── recommendations.py           # «🎯 Рекомендации», ❓Почему/📖Подробнее, 👍/👎/⭐
│   │   │   ├── profile.py                   # /profile, /saved, /stats, /trending
│   │   │   ├── search.py                    # «🔍 Поиск», /search, /semantic
│   │   │   ├── copilot.py                   # /copilot + multi-turn продолжение текстом
│   │   │   └── subscriptions.py             # /subscribe, /unsubscribe
│   │   ├── keyboards/                       # inline + reply клавиатуры
│   │   ├── utils.py                         # esc + send (HTML с авто-fallback в plain)
│   │   └── services/api_client.py           # EventMindAPIClient — async-обёртка над API
│   │
│   ├── core/
│   │   ├── config.py                        # Pydantic-settings: BOT_TOKEN, GROQ_*, DIGEST_*, …
│   │   ├── logging.py
│   │   └── topics.py                        # seed topics/cities/formats/levels + утилиты
│   │
│   ├── db/
│   │   ├── base.py, session.py, dependencies.py
│   │   └── models/                          # 11 моделей SQLAlchemy
│   │
│   ├── recommender/
│   │   ├── scoring.py                       # rule-based score
│   │   ├── hybrid.py                        # 9 компонент: rule+cos+bayes+quality+hype+
│   │   │                                    # freshness+skill+bandit+gnn
│   │   ├── embeddings.py                    # MiniLM + session_embedding + blend
│   │   ├── retrieval.py                     # RAG retrieval + interaction context
│   │   ├── bayesian.py                      # Beta + Thompson + temporal decay
│   │   ├── bandit.py                        # LinUCB contextual bandit (numpy)
│   │   ├── gnn.py                           # LightGCN (numpy, без torch)
│   │   ├── dedup.py                         # семантическая дедупликация по cosine
│   │   ├── diversity.py                     # MMR re-ranking
│   │   ├── cold_start.py                    # LLM bootstrap из bio
│   │   ├── skill_gap.py                     # target_skills vs event.tech_stack
│   │   ├── memory.py                        # long-term memory: write/recall/extract/compact
│   │   ├── explain.py                       # decomposed score + counterfactual
│   │   └── user_model.py                    # topic_weights helpers
│   │
│   ├── ingestion/sources/                   # 6 адаптеров с единым интерфейсом
│   │   ├── habr.py                          # BeautifulSoup + lxml
│   │   ├── rss.py                           # feedparser
│   │   ├── kudago.py                        # публичный JSON API
│   │   ├── luma.py                          # ICS-фиды
│   │   ├── meetup.py                        # GraphQL (Pro-token)
│   │   └── tg_channels.py                   # web-preview scraping (t.me/s/<channel>)
│   │
│   ├── agents/
│   │   ├── recommendation/                  # llm.py с _GroqWithFallback + legacy graph
│   │   ├── event_normalization/             # raw_event → нормализованный event
│   │   └── copilot/                         # Supervisor-Worker граф
│   │       ├── agent.py                     # retrieve → supervisor → specialist → finalize
│   │       ├── state.py                     # CopilotState + Intent Literal
│   │       ├── supervisor.py                # классификация intent'а (pydantic + keyword fallback)
│   │       ├── common.py                    # invoke_with_tools, format_history
│   │       ├── tools.py                     # 5 function-calling tools
│   │       └── specialists/                 # recommendation/career_coach/roadmap/explainer/summary
│   │
│   └── scheduler/digest.py                  # APScheduler: digest + ingestion + memory compact
│
├── alembic/versions/                        # 10 миграций
├── data/                                    # справочные источники
├── docs/                                    # обзор, план показа, отчёт (HSE)
│   └── diagrams/                            # PNG-диаграммы
├── tests/                                   # 180 тестов в 25 файлах
├── scripts/
│   ├── eval_offline.py                      # leave-one-out Recall@k / nDCG@k
│   ├── llm_judge.py                         # LLM-as-judge для оценки выдачи
│   ├── train_gnn.py                         # тренировка LightGCN
│   ├── compact_memories.py                  # ручной запуск compaction
│   ├── backfill_pgvector.py                 # SQLite → Postgres embedding-кэш
│   ├── append_overview_chapter.py           # глава 6 в обзоре (исторически)
│   └── regenerate_docs.py                   # полная регенерация всех 3 .docx
├── .env / .env.example
├── alembic.ini
├── Dockerfile + docker-compose.yml          # сервисы api / bot / scheduler
├── pyproject.toml                           # ruff + pytest конфиг
├── requirements.txt
├── CLAUDE.md                                # bootstrap-контекст для AI-сессий
└── README.md
```

---

## Стек

- **Python 3.12**
- **FastAPI 0.110** + **Uvicorn**
- **aiogram 3.13** — Telegram-бот, long-polling
- **SQLAlchemy 2.0** + **Alembic**
- **SQLite** (dev, WAL + busy_timeout=10s) / **PostgreSQL + pgvector** (prod)
- **LangGraph 0.2** + **langchain-core** — multi-agent графы
- **langchain-groq** + Groq LLM (primary `llama-3.3-70b-versatile`,
  fallback `llama-3.1-8b-instant`)
- **sentence-transformers 2.7** — multilingual MiniLM-L12-v2 (384 dim)
- **APScheduler 3.10** — фоновые джобы
- **BeautifulSoup 4 + lxml**, **feedparser**, **httpx**
- **Pydantic 2** + **pydantic-settings**
- **pytest 8.2** (180 тестов), **ruff**

---

## Модель данных

11 таблиц + 2 association.

**Профиль и события:**
- `users` — `telegram_id`, `username`, `preferred_format`, `city`,
  `topic_weights` (JSON), `is_subscribed`, `embedding` (JSON-вектор или
  `vector(384)` на PG).
- `events` — `title`, `description`, `format`, `city`, `level`, `date`,
  `summary`, `embedding`, `tech_stack` (JSON), `seniority`,
  `quality_score` (1–10), `hype_score` (1–10), `event_type`,
  `target_audience`, `source_url`.
- `raw_events` — `title`, `raw_description`, `source_url`,
  `status ∈ {raw, normalized, non_it, failed}`, `error`.
- `topics` — `code`, `title`; `user_topics`, `event_topics` — many-to-many.

**Слои модели пользователя:**
- `user_topic_stats` — `alpha`, `beta` (Beta-параметры предпочтения по
  теме, для Thompson sampling + temporal decay).
- `user_skill_profiles` — `current_role`, `target_role`, `seniority`,
  `current_skills`, `target_skills`, `goals`, `learning_horizon`
  (заполняется через `/bio`).
- `user_bandit_states` — `dim`, `a_json` (d×d), `b_json` (d),
  `update_count` (онлайн-обновляемое состояние LinUCB).
- `user_memories` — `text`, `category`, `salience` (1–10), `embedding`,
  `access_count`, `last_accessed_at`, `source` (long-term memory, mem0).
- `copilot_sessions` — `messages_json`, `started_at`, `last_message_at`,
  `closed` (мульти-туровая история).

**Взаимодействия:**
- `interactions` — `user_id`, `event_id`, `action ∈ {like, dislike, save}`,
  `created_at`.

**Словари динамические** (`app/core/topics.py`): seed-значения +
автоматическое расширение по поступающим событиям. Любой новый slug от
парсера/LLM проходит через `slugify_code` и записывается в `topics`.
Лейблы для UI вычисляются через `topic_title()`, `format_label()`,
`city_label()`, `level_label()`.

Актуальный снимок — `GET /vocabulary`.

---

## Установка и запуск

Требуется Python 3.12+.

```bash
# 1. Клонировать репозиторий
git clone git@github.com:EgorBelov/event_mind.git
cd event_mind

# 2. Виртуальное окружение
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Зависимости
pip install -r requirements.txt

# 4. Переменные окружения
cp .env.example .env
# открыть .env и заполнить BOT_TOKEN и GROQ_API_KEY (обязательны)

# 5. Применить миграции (создаст eventmind.db по умолчанию)
alembic upgrade head

# 6. (опционально) наполнить событиями
curl -X POST "http://localhost:8000/ingestion/load-habr?limit=20"
curl -X POST "http://localhost:8000/ingestion/load-rss?limit_per_feed=20"
```

---

## PostgreSQL + pgvector

Прод-вариант — PostgreSQL с расширением `pgvector`: top-k поиск
выполняется на стороне БД через оператор `<=>` (cosine distance) с
IVFFlat-индексом. На датасете 10⁴–10⁵ событий это ускоряет `/copilot` и
semantic-search на порядок.

Переключение управляется только `DATABASE_URL`. Код автоматически
определяет backend (`app/db/backend.py:has_pgvector`) и выбирает быстрый
путь, если расширение доступно. На SQLite/без pgvector — прежняя
in-process сортировка по cosine.

```bash
# 1. Создать БД и расширение
psql -U postgres -c "CREATE DATABASE eventmind;"
psql -U postgres -d eventmind -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 2. В .env переключиться на Postgres
# DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/eventmind

# 3. Накатить миграции (9a1b2c3d4e5f добавит embedding_vec + IVFFlat)
alembic upgrade head

# 4. Перенести JSON-embedding'и → vector (если данные были на SQLite)
DATABASE_URL=postgresql+psycopg2://... python -m scripts.backfill_pgvector
```

Если `pgvector` не установлен на сервере (`CREATE EXTENSION` падает):
- Postgres.app / brew — `brew install pgvector`;
- EnterpriseDB — собрать из исходников
  (`make PG_CONFIG=/Library/PostgreSQL/15/bin/pg_config && sudo make install`).

---

## Переменные окружения

Читаются через `pydantic-settings` из `.env` (см. `app/core/config.py`).
Шаблон — `.env.example`.

### Базовое

| Переменная | Default | Описание |
|---|---|---|
| `BOT_TOKEN` | — | Токен Telegram-бота. Обязателен для `app.bot.main` и scheduler. |
| `DATABASE_URL` | `sqlite:///./eventmind.db` | SQLAlchemy URL. Для PG: `postgresql+psycopg2://user:pass@host:5432/db`. |
| `API_HOST` | `http://localhost:8000` | Базовый URL FastAPI, который дёргают bot и scheduler. |
| `DEBUG` | `false` | Verbose-логи и SQL echo. |

### LLM (Groq)

| Переменная | Default | Описание |
|---|---|---|
| `GROQ_API_KEY` | — | Ключ Groq Cloud. Без него LLM-агенты падают, система деградирует до rule-based. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Primary-модель. |
| `GROQ_FALLBACK_MODEL` | `llama-3.1-8b-instant` | Резерв — при rate-limit'е primary `_GroqWithFallback` автоматически переключается. |
| `GROQ_TEMPERATURE` | `0.4` | Temperature обоих моделей. |
| `GROQ_MAX_RETRIES` | `2` | Retries при сетевых ошибках. |

### Ingestion

| Переменная | Default | Описание |
|---|---|---|
| `INGEST_ENABLED` | `true` | Включает периодический ingestion внутри scheduler-процесса. |
| `INGEST_INTERVAL_HOURS` | `6` | Период `ingest_habr` / `ingest_rss` / `ingest_telegram`. |
| `INGEST_HABR_LIMIT` | `20` | Лимит событий с Habr за тик. |
| `INGEST_RSS_LIMIT_PER_FEED` | `20` | Лимит на одну RSS-ленту за тик. |
| `RSS_FEEDS` | `""` | RSS/Atom URL'ы через запятую. |
| `TG_INGEST_CHANNELS` | `""` | Telegram-каналы через запятую (username без `@`). |
| `LUMA_CALENDARS` | `""` | ICS URL'ы Lu.ma через запятую. |
| `MEETUP_TOKEN`, `MEETUP_GROUPS` | `""` | OAuth Pro-token + urlnames для Meetup. |
| `TG_API_ID`, `TG_API_HASH` | `null`/`""` | (опционально) для расширенного Telegram-доступа. |

### Дайджест

| Переменная | Default | Описание |
|---|---|---|
| `DIGEST_INTERVAL_MINUTES` | `1440` | Интервал рассылки AI-дайджеста. Для dev — `10`. |
| `DIGEST_RUN_ON_STARTUP` | `false` | Запускать ли первую рассылку сразу при старте scheduler'а. |

### Recsys-веса

| Переменная | Default | Описание |
|---|---|---|
| `SCORE_RULE_WEIGHT` | `0.5` | Вес rule-компонента. |
| `SCORE_COSINE_WEIGHT` | `10.0` | Вес семантической близости. |
| `SCORE_BAYES_WEIGHT` | `5.0` | Вес Thompson sampling. |
| `SCORE_QUALITY_WEIGHT` | `0.5` | Вес quality. |
| `SCORE_HYPE_WEIGHT` | `0.3` | Вес hype. |
| `SCORE_FRESHNESS_WEIGHT` | `2.0` | Вес freshness. |
| `SCORE_SKILL_GAP_WEIGHT` | `3.0` | Вес skill-gap. |
| `FRESHNESS_HALF_LIFE_DAYS` | `30.0` | Half-life экспоненциального decay по дате. |
| `MMR_ENABLED` / `MMR_LAMBDA` | `true` / `0.7` | MMR-диверсификация. |
| `BAYES_DECAY_PER_DAY` | `0.995` | γ для temporal decay Bayesian-параметров. |
| `DEDUP_ENABLED` / `DEDUP_THRESHOLD` | `true` / `0.92` | Семантическая дедупликация. |
| `BANDIT_ENABLED` / `BANDIT_WEIGHT` / `BANDIT_ALPHA` | `true` / `2.0` / `1.0` | LinUCB вкл/вес/exploration. |
| `GNN_ENABLED` / `GNN_WEIGHT` / `GNN_EMBEDDING_DIM` | `false` / `3.0` / `32` | LightGCN: по умолчанию выкл. |
| `MEMORY_ENABLED` / `MEMORY_MIN_SALIENCE` / `MEMORY_COMPACT_THRESHOLD` | `true` / `4.0` / `50` | Long-term memory. |

---

## Запуск компонентов

Три **независимых процесса**. Запускайте в отдельных терминалах или через
docker-compose.

### 1) FastAPI backend

```bash
# dev — авто-перезагрузка
uvicorn app.api.main:app --reload

# prod
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Полезные URL:
- `http://localhost:8000/` — корневой ответ
- `http://localhost:8000/health` — healthcheck (db / embeddings / llm)
- `http://localhost:8000/docs` — Swagger UI
- `http://localhost:8000/admin/` — HTML-дашборд

### 2) Telegram-бот

```bash
python -m app.bot.main
```

Без `BOT_TOKEN` упадёт с `ValueError: BOT_TOKEN не найден в .env`.

### 3) Scheduler

Раз в `DIGEST_INTERVAL_MINUTES` берёт подписчиков, для каждого получает
топ AI-карточку и отправляет через Telegram Bot API. Параллельно крутит
ingestion и compaction памяти.

```bash
python -m app.scheduler.digest
```

Зависит от запущенного API и валидного `BOT_TOKEN`.

---

## Docker

```bash
docker compose up -d --build    # api / bot / scheduler
docker compose logs -f api
docker compose down
```

`bot` и `scheduler` стартуют только после healthcheck'а `api`. Внутри
контейнеров `DATABASE_URL` указывает на `/app/eventmind.db`. Том
пробрасывается для сохранения `data/` и SQLite-файла.

---

## Telegram-бот: команды и сценарии

| Команда / текст | Что делает |
|---|---|
| `/start` | 4-экранный onboarding-тур + кнопка «🚀 Начать настройку» в конце. |
| `/start event_<id>` | Deep-link на карточку события (для шеринга). |
| `/tour` | Повторить тур в любой момент. |
| `/edit` | Перезапуск мастера для перенастройки тем/формата/города. |
| `/profile` | Текущий профиль и веса интересов. |
| `/recommend` | Лента hybrid-рекомендаций; кнопки ❓ Почему / 📖 Подробнее / 👍 / 👎 / ⭐ / Похожие / Следующее. |
| `🎯 Рекомендации` | Reply-кнопка-эквивалент `/recommend`. |
| `🔍 Поиск` или `Найти: <q>` | Comb-поиск: keyword (до 3) + semantic (до 5) в один проход; goal-intent → Copilot. |
| `/saved` | Сохранённые события. |
| `/stats` | Личная статистика: лайки/дизлайки/сохранения, топ тем, последние действия. |
| `/undo` | Откат последнего фидбэка во всех 4 подсистемах. |
| `/bio <текст>` | Холодный старт: LLM с pydantic-валидацией извлекает skill-профиль. |
| `/copilot <цель>` | Старт новой сессии Copilot (Supervisor-Worker). |
| (просто текст в чат, если есть активная сессия) | Продолжение мульти-турового диалога Copilot. Сессия живёт 15 минут после последнего сообщения. |
| `/trending` | Горячие темы за 7 дней + ASCII-bar-график. |
| `/subscribe`, `/unsubscribe` | Управление подпиской на AI-дайджест. |

Reply-меню: «🎯 Рекомендации», «🔍 Поиск», «👤 Профиль», «⚙️ Ещё». Под
профилем — инлайн-сабменю: Избранное / Активность / Изменить профиль /
переключатель AI-дайджеста. Под «⚙️ Ещё» — Тренды / Помощь.

Карточка события: вместо переключения «обычные / AI» теперь два
независимых пояснения:
- **❓ Почему** — короткий ответ LLM в поп-апе (1–2 предложения с
  привязкой к одному конкретному факту: тема, target_skill, лайкнутое
  событие);
- **📖 Подробнее** — отдельное сообщение: развёрнутый LLM-нарратив +
  1–2 практических совета + rule-based разбивка по компонентам с числами
  + counterfactual («без skill_gap-сигнала событие потеряло бы ~45 %
  веса»).

Весь исходящий текст рендерится через `bot/utils.send` — HTML с
экранированием динамики и авто-откатом в plain-text при сбое парсинга
Telegram'ом.

---

## Логика рекомендаций

Hybrid scoring — `app/recommender/hybrid.py`. 9 компонент, каждая в
`try/except` — сбой одной не ломает выдачу.

| # | Компонент | Парадигма | Вес (default) | Что считает |
|---|---|---|---|---|
| 1 | rule | rule-based | 0.5 | `+2` за пересечение тем, `+3` за `preferred_format == event.format` (`+1` для `any`), `+2` за совпадение города (`+1` для `any`). Надёжный baseline. |
| 2 | cosine | content-based | 10.0 | `cosine(user_emb, event_emb)`. user_emb = blend(0.7·long-term, 0.3·session) на последних 5 взаимодействиях. |
| 3 | bayesian | Bayesian preference | 5.0 | Thompson sampling: `p ~ Beta(α, β)` по каждой теме события, `max(p)`. Temporal decay `γ^days`. |
| 4 | quality | LLM-эвристика | 0.5 | `event.quality_score / 10` (выставляется AI-нормализатором). |
| 5 | hype | LLM-эвристика | 0.3 | `event.hype_score / 10`. |
| 6 | freshness | эвристика времени | 2.0 | `exp(-ln(2) × |days| / half_life)`. |
| 7 | skill_gap | goal-aware | 3.0 | `|target_skills ∩ tech_stack| / |target_skills|` + бонус за seniority. |
| 8 | bandit | contextual bandit (LinUCB) | 2.0 | UCB: `xᵀθ̂ + α·√(xᵀA⁻¹x)` на 16-мерном векторе пары (user, event). |
| 9 | gnn | collaborative (LightGCN) | 3.0 (выкл) | `user_emb · event_emb` из натренированной модели. По умолчанию `GNN_ENABLED=false`. |

**Итоговый score** = сумма всех компонент с весами из `core/config.py`.
Каждый компонент best-effort: при сбое вклад = 0, hybrid плавно
деградирует до rule-based.

**MMR-диверсификация** (`recommender/diversity.mmr_rerank`) поверх:
`λ · relevance − (1−λ) · max_sim(picked)`. Гарантирует, что top-k не
один-к-одному из одной темы.

**Embedding-кэш.** Embedding'и пользователя и событий persist'ятся:
`refresh_user_embedding` (с обязательным `db.rollback()` на сбое — иначе
PendingRollbackError ломает запрос) и `ensure_event_embeddings`
(пакетный досчёт недостающих). За счёт кэша `/recommendations` отдаётся
за ~0.4 с вместо ~16 с.

**Cold-start** через `POST /users/{tid}/analyze-bio`: LLM с
pydantic-валидацией извлекает темы, приоритеты, формат, город, seniority,
цели → `apply_cold_start` расставляет topic_weights с буст-маркером для
priority-тем, пишет «виртуальные» Bayesian-обновления, создаёт
`UserSkillProfile`.

**Обратная связь** обновляет 4 подсистемы синхронно в одной транзакции:

| action | `topic_weights` | Bayesian `α/β` | LinUCB `A, b` | long-term memory |
|---|---|---|---|---|
| like | +3 | α += 3 | A += xxᵀ, b += 1.0·x | LLM пишет заметку при значимости |
| save | +1 | α += 1 | A += xxᵀ, b += 1.5·x | LLM пишет заметку при значимости |
| dislike | −2 | β += 2 | A += xxᵀ, b −= 1.0·x | LLM пишет заметку при значимости |

Повторное нажатие той же кнопки → откат (`direction=-1`) во всех четырёх.
`/undo` делает то же для последнего фидбэка.

**Объяснения** (`explain.explain_event_detailed`): `text`, `topic_match`,
`format_match`, `city_match`, `semantic_similarity`,
`bayesian_posterior`, `history_signals`, `score_breakdown`,
`counterfactual`. Подписи компонент в `_COMPONENT_LABELS_RU` —
человеческий русский без технических терминов («Bayesian Thompson»,
«LinUCB», «LightGCN» в UI не светятся).

**Offline-эвал:**
```bash
python -m scripts.eval_offline --k 5
python -m scripts.llm_judge --k 5 --variants rule hybrid bandit_on
python -m scripts.train_gnn          # если GNN_ENABLED=true
```

---

## Пайплайн ingestion

1. **Источник** (`app/ingestion/sources/`, единый интерфейс `_load_and_normalize`):
   | URL | Источник | Параметры |
   |---|---|---|
   | `POST /ingestion/load-habr` | Habr (HTML) | `limit` |
   | `POST /ingestion/load-rss` | RSS/Atom | `limit_per_feed`, `.env` `RSS_FEEDS` |
   | `POST /ingestion/load-kudago` | KudaGo (JSON) | `limit` |
   | `POST /ingestion/load-luma` | Lu.ma (ICS) | `limit_per_calendar`, `.env` `LUMA_CALENDARS` |
   | `POST /ingestion/load-meetup` | Meetup (GraphQL) | `MEETUP_TOKEN`, `MEETUP_GROUPS` |
   | `POST /ingestion/load-telegram` | Telegram-каналы (web-preview) | `limit_per_channel`, `.env` `TG_INGEST_CHANNELS` |
2. Запись попадает в `raw_events` со статусом `raw`.
3. **`EventNormalizerAgent`** (LangGraph + Groq LLM,
   `app/agents/event_normalization/agent.py`) возвращает JSON:
   `title, description, format, city, level, date, topics, event_type,
   target_audience, source_url, tech_stack, seniority, quality_score,
   hype_score`. Pydantic валидирует. Промпт даёт seed-словари как
   «предпочтительные», но разрешает создавать новые slug'и. Все строки
   проходят через `slugify_code` → стабильный snake_case.
4. Не-IT события (`topics == []`) → `status=non_it`, в `events` НЕ
   попадают.
5. **Дедупликация:** сначала точное совпадение `title`; затем
   **семантическая** (`recommender/dedup.find_semantic_duplicate`) ищет
   событие с cosine ≥ `DEDUP_THRESHOLD` (0.92) за 90 дней — ловит
   парафразы и кросс-источниковые дубли.
6. Если новое — создаётся `Event`, привязываются темы (`event_topics`),
   считается `embedding` (best-effort).
7. `raw_event.status` обновляется на `normalized` или `failed` (с
   `error`).

```bash
curl -X POST "http://localhost:8000/ingestion/load-habr?limit=20"
curl -X POST "http://localhost:8000/ingestion/load-rss?limit_per_feed=20"
curl http://localhost:8000/ingestion/status
```

**Автоматическое пополнение.** При `INGEST_ENABLED=true` scheduler
дёргает `ingest_habr`, `ingest_rss`, `ingest_telegram` (если указаны
каналы) каждые `INGEST_INTERVAL_HOURS` часов. RSS и Telegram сдвинуты на
30/60 с относительно Habr, чтобы не пересекаться.

---

## AI-агенты на LangGraph

Три графа в `app/agents/`:

### 1) Event normalization (`event_normalization/agent.py`)

Однонодовый граф. Один LLM-вызов на сырое событие → нормализованный
JSON с pydantic-валидацией. Фильтрует не-IT, clamp'ает scores в 1..10.

### 2) AI-рекомендации (вариант C, без LangGraph)

Старая 4-нодовая цепочка `user_profile → event_analyzer → recommendation
→ explanation` оставлена в `app/agents/recommendation/graph.py` для
истории, но НЕ используется в endpoint'е (она делала 4 LLM-вызова и
работала ~15 с, фиксировано 3 карточки).

Сейчас в `app/api/services/ai_recommendation_service.py`:
```
hybrid_score (детерминированно, ~ms) → top-N кандидатов
                ↓
        один LLM-вызов с pydantic-схемой
                ↓
        {event_id: reason} → подмена `explanation` в карточках
```
Параметр `limit` (1..10) реально работает. При сбое LLM —
`_GroqWithFallback` переключается на резервную модель; если и она упала
— rule-based объяснения.

### 3) Copilot (`copilot/agent.py`) — Supervisor-Worker multi-agent

```
START → retrieve → supervisor → conditional edge:
                                  ├── recommendation_specialist  (intent=recommend)
                                  ├── career_coach               (intent=career)
                                  ├── roadmap_planner            (intent=roadmap)
                                  ├── event_explainer            (intent=explain)
                                  └── summary_specialist         (intent=summary)
                                          ↓
                                       finalize → END
```

**`retrieve`** — общий для всех специалистов: top-k событий по cosine
(query⊕profile), снимок истории, skill-профиль.

**`supervisor`** — structured LLM-вызов с pydantic-валидацией
(`SupervisorDecision`): классифицирует запрос в один из 5 intent'ов +
извлекает `target_event_id` / `horizon_months`. При сбое — keyword
fallback.

**Специалисты:**

| Специалист | Intent | Tools | Особенности |
|---|---|---|---|
| `recommendation_specialist` | recommend | все 5 + critique-revise | основной workhorse |
| `career_coach` | career | profile, search_events, recall_about_user | фокус на skill_gap/target_role |
| `roadmap_planner` | roadmap | profile, search_events, recall_about_user | этапный план под `horizon_months` |
| `event_explainer` | explain | explain_event, profile | разворачивает `explain_event_detailed` в нарратив |
| `summary_specialist` | summary | interactions_summary, profile | анализ истории |

**6 function-calling tools** в `agents/copilot/tools.py` (`TOOL_DEFINITIONS`):
`search_events`, `get_user_profile`, `get_interactions_summary`,
`explain_event`, `recall_about_user`, `mark_saved`. Связываются через
`bind_tools` — модель сама решает, что вызвать. Подмножество на специалиста
раздаётся через `filter_tools(...)`.

**Multi-turn:** `POST /copilot/{tid}/turn` хранит сессии в
`copilot_sessions`, принимает опциональный `session_id`. История
прокидывается в supervisor (для контекстной классификации) и в
специалиста (для преемственности). В боте состояние сессии живёт 15
минут в RAM `user_id → {session_id, last_activity}`; любое следующее
текстовое сообщение продолжает диалог.

**State** — `CopilotState` (TypedDict): supervisor пишет `intent`,
`routing_reason`, `target_event_id`, `horizon_months`; специалисты —
`answer`, `recommended_event_ids`, `specialist`, `tool_calls_log`.

**Прозрачность:** в ответе API возвращаются `intent`, `specialist`,
`routing_reason`, `tool_calls`.

**Логирование сбоев.** При любом Exception внутри `_invoke_graph`
вызывается `logger.exception` — реальная причина попадает в логи API,
пользователь видит «Copilot временно недоступен», сессия сохраняется.

### Long-term memory agent (`recommender/memory.py`) — mem0-style

Активно извлекает значимые факты о пользователе и хранит как заметки от
первого лица в `user_memories`:
> «хочет перейти в ML за 6 месяцев»
> «активно сохраняет события про Kubernetes»

**Триггеры записи:**

| Триггер | Что пишется | Salience |
|---|---|---|
| `create_interaction` | LLM смотрит на feedback, пишет 0–2 заметки если нетривиально | 1..10 |
| `/copilot/turn` | LLM из последней пары user/assistant вытаскивает новые цели/ограничения | 1..10 |
| `analyze_bio` | Цели → `goal`/8, приоритеты → `interest`/7 | фикс |

Категории: `interest`, `dislike`, `goal`, `constraint`, `context`,
`event_pref`, `other`. Pydantic-валидация LLM-выхода.

**Semantic recall** через tool `recall_about_user(query, k)`: top-k по
`0.7·cosine + 0.3·salience_norm`, инкремент `access_count`.

**Compaction:** при >50 заметок LLM группирует по категориям и сжимает
до ≤5 на категорию. Scheduler-job раз в 7 дней или вручную
`python -m scripts.compact_memories`.

---

## REST API

База: `http://localhost:8000`. Swagger: `/docs`, OpenAPI: `/openapi.json`.

### System

| Метод | URL | Описание |
|---|---|---|
| GET | `/` | Корневой ответ. |
| GET | `/health` | `{db, embeddings, llm: ok/fail}`. |

### Users

| Метод | URL | Описание |
|---|---|---|
| POST | `/users/register` | Создать/обновить пользователя (`telegram_id`, `topics`, `preferred_format`, `city`). |
| GET | `/users/{telegram_id}` | Профиль. |
| GET | `/users/{telegram_id}/stats` | Личная статистика. |
| POST | `/users/{telegram_id}/analyze-bio` | Cold-start: LLM извлекает skill-профиль из bio. |
| POST | `/users/{telegram_id}/update-embedding` | Пересчёт персонального embedding'а. |

### Events

| Метод | URL | Описание |
|---|---|---|
| POST | `/events/load` | Загрузить события из `data/events.json`. |
| GET | `/events/` | Список всех событий. |
| GET | `/events/search` | Keyword-поиск (`q`, `topics`, `format`, `city`). |
| GET | `/events/semantic-search` | Embedding top-k (`q`, `limit`). На PG — pgvector через `<=>`. |
| GET | `/events/combined-search` | Keyword + semantic в одном запросе (`q`, `keyword_limit`, `semantic_limit`). Распознаёт goal-intent. |
| GET | `/events/{event_id}` | Карточка события. |
| GET | `/events/{event_id}/similar` | Похожие по темам. |

### Recommendations

| Метод | URL | Описание |
|---|---|---|
| GET | `/recommendations/{telegram_id}` | Hybrid-рекомендации (9 компонент + MMR). |
| POST | `/recommendations/interactions` | Сохранить like/dislike/save (обновит 4 подсистемы). |
| POST | `/recommendations/{telegram_id}/undo` | Откатить последний фидбэк. |
| GET | `/recommendations/{telegram_id}/event/{event_id}/interactions` | Действия пользователя по событию. |
| GET | `/recommendations/{telegram_id}/saved` | Сохранённые события. |
| GET | `/recommendations/{telegram_id}/why/{event_id}` | `{short, full}` для ❓ Почему / 📖 Подробнее. |

### Agent recommendations (вариант C)

| Метод | URL | Описание |
|---|---|---|
| GET | `/agent-recommendations/{telegram_id}` | `{success, answer, cards}` — нарратив + карточки. |
| GET | `/agent-recommendations/{telegram_id}/cards` | Только карточки с AI-`explanation`. Фолбэк на rule-based при сбое LLM. |

### Copilot

| Метод | URL | Описание |
|---|---|---|
| POST | `/copilot/{telegram_id}` | One-shot Copilot (legacy compat). |
| POST | `/copilot/{telegram_id}/turn` | Multi-turn: продолжает сессию по `session_id` или создаёт новую. |
| GET | `/copilot/{telegram_id}/sessions` | Список открытых сессий. |
| POST | `/copilot/sessions/{session_id}/close` | Закрыть сессию. |

### Ingestion

| Метод | URL | Описание |
|---|---|---|
| POST | `/ingestion/load-habr` | Парсит Habr, сохраняет, нормализует. |
| POST | `/ingestion/load-rss` | Парсит ленты из `RSS_FEEDS`, нормализует. |
| POST | `/ingestion/load-kudago` | KudaGo JSON API. |
| POST | `/ingestion/load-luma` | Lu.ma ICS. |
| POST | `/ingestion/load-meetup` | Meetup GraphQL (требует `MEETUP_TOKEN`). |
| POST | `/ingestion/load-telegram` | Telegram-каналы (web-preview). |
| POST | `/ingestion/load-raw` | Залить `data/events_raw.json` в `raw_events`. |
| POST | `/ingestion/normalize` | Прогнать `raw_events.status == 'raw'` через AI-нормализатор. |
| GET | `/ingestion/status` | Счётчики по статусам. |

### Subscriptions

| Метод | URL | Описание |
|---|---|---|
| POST | `/subscriptions/{telegram_id}/subscribe` | Подписаться на AI-дайджест. |
| POST | `/subscriptions/{telegram_id}/unsubscribe` | Отписаться. |
| GET | `/subscriptions/users` | Список подписчиков (используется scheduler'ом). |

### Admin / Vocabulary / Analytics

| Метод | URL | Описание |
|---|---|---|
| GET | `/admin/` | HTML-дашборд. |
| GET | `/vocabulary` | `{topics, cities, formats, levels}` — динамический snapshot. |
| GET | `/vocabulary/{topics\|cities\|formats\|levels}` | Отдельный список. |
| GET | `/analytics/topics` | Топ лайкнутых/сохранённых/дизлайкнутых тем. |
| GET | `/analytics/interactions` | Сумма действий + топ событий по интеракциям. |
| GET | `/analytics/trending` | Горячие события (`likes×3 + saves×2`) и trending-темы (`days`, `limit`). |

#### Примеры curl

```bash
# Регистрация
curl -X POST http://localhost:8000/users/register \
  -H "Content-Type: application/json" \
  -d '{"telegram_id":1,"username":"hisoka","preferred_format":"online","city":"moscow","topics":["ai_ml","backend"]}'

# Рекомендации
curl http://localhost:8000/recommendations/1

# Лайк
curl -X POST http://localhost:8000/recommendations/interactions \
  -H "Content-Type: application/json" \
  -d '{"telegram_id":1,"event_id":3,"action":"like"}'

# Multi-turn Copilot — новая сессия
curl -X POST "http://localhost:8000/copilot/1/turn" \
  -H "Content-Type: application/json" \
  -d '{"message":"хочу за полгода вырасти в middle backend"}'

# Продолжить сессию
curl -X POST "http://localhost:8000/copilot/1/turn" \
  -H "Content-Type: application/json" \
  -d '{"session_id":42,"message":"а если без конференций?"}'

# Habr ingestion
curl -X POST "http://localhost:8000/ingestion/load-habr?limit=10"

# Trending за неделю
curl "http://localhost:8000/analytics/trending?days=7&limit=5"
```

---

## Admin-дашборд

`http://localhost:8000/admin/` — HTML-страница без шаблонизатора
(`app/api/routers/admin.py`):
- карточки: пользователи, события, подписчики, взаимодействия;
- статусы ingestion (`raw / normalized / failed / non_it`);
- таблица последних 10 событий.

---

## Тесты

```bash
pytest -q              # 180 тестов, ~30 с
pytest tests/test_scoring.py -v
ruff check .           # 0 ошибок (line-length=100, py312)
```

Состав (26 файлов):
- `test_scoring`, `test_user_model`, `test_interactions`, `test_new_features`
- `test_bayesian`, `test_bayes_decay` — Beta-апдейты, Thompson, decay
- `test_retrieval` — RAG retrieval + interaction context
- `test_multi_objective` — breakdown, freshness, quality+hype, MMR
- `test_dedup` — semantic dedup threshold
- `test_cold_start` — `apply_cold_start`
- `test_skill_gap`, `test_bandit`, `test_gnn`
- `test_copilot_tools`, `test_supervisor`, `test_specialists`,
  `test_copilot_graph_e2e`
- `test_memory`, `test_memory_integration`
- `test_ingestion`, `test_multi_source` — офлайн-моки источников
- `test_card_format`, `test_scheduler`, `test_db_session`

---

## Миграции

```bash
alembic upgrade head                              # применить все
alembic revision --autogenerate -m "add field"    # создать
alembic downgrade -1                              # откат на ревизию
```

История (`alembic/versions/`, 10 ревизий):
- `6af520bb31e0_initial_schema` — базовые таблицы;
- `7b1c9d2e3a4f_add_summary_embedding_to_events` — `summary`, `embedding`;
- `b3c4d5e6f7a8_add_enriched_fields` — `tech_stack`, `seniority`,
  `quality_score`, `hype_score`;
- `c5d6e7f89012_add_user_topic_stats` — Bayesian α/β;
- `d6e7f8901234_add_user_skill_profile` — skill-профиль для cold start;
- `e7f890123456_add_copilot_sessions` — мульти-туровая история;
- `f8901234abcd_add_bandit_state` — LinUCB-матрицы;
- `abcd1234ef56_add_user_memories` — long-term memory;
- `9a1b2c3d4e5f_add_pgvector` — **только PG**: `CREATE EXTENSION vector`,
  `events.embedding_vec` / `users.embedding_vec` типа `vector(384)`,
  IVFFlat-индекс. На SQLite — no-op.

---

## Минимальный happy-path

```bash
# 1. Подготовка
cp .env.example .env                     # вписать BOT_TOKEN + GROQ_API_KEY
alembic upgrade head

# 2. Три процесса в отдельных терминалах
uvicorn app.api.main:app --reload
python -m app.bot.main
python -m app.scheduler.digest

# 3. Наполнить событиями
curl -X POST "http://localhost:8000/ingestion/load-habr?limit=20"
curl -X POST "http://localhost:8000/ingestion/load-rss?limit_per_feed=20"

# 4. В Telegram: /start → тур → 🚀 Начать настройку → /recommend
#    Поставить 👍 / 👎 / ⭐ → /recommend ещё раз → лента подстроилась
#    /copilot хочу за полгода стать middle backend
```

---

## Документация

- `docs/Обзор_проекта_EventMind.docx` — авторитетный summary архитектуры
  и состояния. Глава 7 — подробное описание 9 компонент рекомендера.
- `docs/План_показа_EventMind.docx` — план защиты на 15–20 минут с
  глоссарием и сценариями демо.
- `docs/отчет_Курсовая.docx` — полный технический отчёт (HSE-шаблон).
- `docs/diagrams/` — PNG-диаграммы (архитектура, recsys-pipeline,
  Copilot-граф, ER, ingestion).
- `CLAUDE.md` — bootstrap-контекст для будущих AI-сессий.

Все три .docx идемпотентно регенерируются под текущую реализацию:
```bash
python -m scripts.regenerate_docs
```
