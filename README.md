# EventMind

**EventMind** — прототип системы агрегации IT-событий и персонализированных AI-рекомендаций.
Состоит из FastAPI-бэкенда, Telegram-бота на aiogram 3, набора LangGraph-агентов (Groq LLM),
hybrid-рекомендера (rule + embeddings) и планировщика ежедневных AI-дайджестов на APScheduler.

---

## Содержание

1. [Идея и возможности](#идея-и-возможности)
2. [Архитектура](#архитектура)
3. [Структура проекта](#структура-проекта)
4. [Стек](#стек)
5. [Модель данных](#модель-данных)
6. [Установка и запуск](#установка-и-запуск)
7. [Переменные окружения](#переменные-окружения)
8. [Запуск компонентов: API, Bot, Scheduler](#запуск-компонентов-api-bot-scheduler)
9. [Запуск через Docker](#запуск-через-docker)
10. [Telegram-бот: команды и сценарии](#telegram-бот-команды-и-сценарии)
11. [Логика рекомендаций](#логика-рекомендаций)
12. [Пайплайн ingestion](#пайплайн-ingestion)
13. [LangGraph-агенты](#langgraph-агенты)
14. [REST API: полный справочник endpoints](#rest-api-полный-справочник-endpoints)
15. [Admin-дашборд](#admin-дашборд)
16. [Тесты](#тесты)
17. [Миграции](#миграции)

---

## Идея и возможности

Система предназначена для:
- сбора и нормализации IT-событий (JSON-источник, Habr и т. д.);
- хранения профиля пользователя (темы, формат, город, веса интересов, embedding);
- выдачи персональных рекомендаций (rule-based + embedding similarity);
- фиксации обратной связи (like / dislike / save) и адаптации профиля;
- объяснений рекомендаций с учётом истории взаимодействий;
- AI-помощника (Copilot) с подбором roadmap-событий под цель пользователя;
- автоматической ежедневной AI-рассылки в Telegram.

Реализованный функционал:
- настройка профиля через Telegram inline-меню (темы, формат, город);
- регистрация / обновление пользователя через API;
- загрузка событий из JSON, парсинг событий с Habr (HTML, BeautifulSoup);
- AI-нормализация сырых событий через LangGraph + Groq LLM;
- генерация `summary`, `tech_stack`, `seniority`, `quality_score`, `hype_score`;
- detection дубликатов событий (`SequenceMatcher`, порог 0.85);
- hybrid-рекомендации: rule + cosine similarity по `sentence-transformers`
  (`paraphrase-multilingual-MiniLM-L12-v2`);
- LangGraph-граф рекомендаций (`user_profile → event_analyzer → recommendation → explanation`);
- объяснения рекомендаций с учётом history-signals (лайков, сохранений, формата);
- семантический поиск (`/semantic`, `/events/semantic-search`);
- keyword-поиск (`/search`, `/events/search`);
- похожие события (по пересечению тем);
- персональная статистика пользователя (`/stats`);
- холодный старт через `/bio` (LLM или keyword-rules);
- AI Copilot (`/copilot <цель>`) — roadmap-агент по цели пользователя;
- trending-аналитика (`/trending`) — горячие события и темы;
- подписки и ежедневный AI-дайджест (APScheduler, интервал 24 ч);
- HTML admin-дашборд (`/admin/`);
- аналитика по темам и взаимодействиям (`/analytics/*`);
- Alembic-миграции (initial + summary/embedding + enriched fields).

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
         │                            │   SQLite (Alembic) │
         │                            └─────────┬──────────┘
         │                                      │
         │                                      │ читает / пишет
         │                                      │
┌────────▼─────────┐    invoke()      ┌─────────▼──────────┐
│   APScheduler    │ ───────────────► │  LangGraph agents  │
│  digest (24 ч)   │                  │   (Groq LLM)       │
└──────────────────┘                  └─────────┬──────────┘
                                                │
                                                │ sentence-transformers
                                                ▼
                                      ┌────────────────────┐
                                      │ Hybrid Recommender │
                                      └────────────────────┘
```

Три независимых процесса:
1. **API** (`uvicorn app.api.main:app`) — основной сервис, держит БД и LLM-агентов.
2. **Bot** (`python -m app.bot.main`) — Telegram-фронт, общается с API через httpx.
3. **Scheduler** (`python -m app.scheduler.digest`) — APScheduler, который раз в сутки
   ходит в API за подписчиками и AI-карточками, и шлёт их в Telegram-API напрямую.

---

## Структура проекта

```text
eventmind/
├── app/                                  # основной пакет приложения
│   ├── api/                              # FastAPI backend
│   │   ├── main.py                       # точка входа FastAPI, подключение всех роутеров + /health
│   │   ├── routers/                      # HTTP-роутеры (по доменам)
│   │   │   ├── users.py                  # /users/* — регистрация, профиль, статистика, bio
│   │   │   ├── events.py                 # /events/* — список, поиск, semantic-search, similar
│   │   │   ├── recommendations.py        # /recommendations/* — rule+embedding рекомендации, лайки
│   │   │   ├── agent_recommendations.py  # /agent-recommendations/* — LangGraph-агенты
│   │   │   ├── copilot.py                # /copilot/* — AI-копилот по цели пользователя
│   │   │   ├── ingestion.py              # /ingestion/* — raw events, Habr, нормализация
│   │   │   ├── subscriptions.py          # /subscriptions/* — подписки на AI-дайджест
│   │   │   ├── admin.py                  # /admin/ — HTML-дашборд
│   │   │   └── analytics.py              # /analytics/* — topics / interactions / trending
│   │   ├── schemas/                      # Pydantic-схемы для запросов и ответов
│   │   │   ├── user.py                   # UserCreate, UserResponse
│   │   │   ├── event.py                  # EventResponse
│   │   │   └── recommendation.py         # RecommendationResponse, InteractionCreate
│   │   └── services/                     # доменная бизнес-логика (вне роутеров)
│   │       ├── user_service.py           # CRUD юзера, stats, analyze_bio
│   │       ├── event_service.py          # загрузка JSON-событий, прикрепление тем
│   │       ├── search_service.py         # keyword + semantic search, similar
│   │       ├── ingestion_service.py      # raw_events → normalized events через AI-агента
│   │       ├── recommendation_service.py # формирование списка рекомендаций, interactions
│   │       └── subscription_service.py   # subscribe / unsubscribe / list
│   │
│   ├── bot/                              # Telegram-бот (aiogram 3)
│   │   ├── main.py                       # инициализация Dispatcher, подключение роутеров
│   │   ├── handlers/                     # хэндлеры команд / callback'ов / текстовых кнопок
│   │   │   ├── start.py                  # /start, мастер настройки (темы → формат → город)
│   │   │   ├── profile.py                # /profile, /saved, /stats, /bio, /trending, /copilot
│   │   │   ├── recommendations.py        # /recommend и AI-рекомендации с like/dislike/save
│   │   │   ├── subscriptions.py          # /subscribe / /unsubscribe
│   │   │   └── search.py                 # /search, /semantic, "Найти: <q>"
│   │   ├── keyboards/                    # inline + reply клавиатуры и лейблы тем/городов
│   │   │   ├── inline.py                 # topics_keyboard, recommendation_keyboard и пр.
│   │   │   └── reply.py                  # главное меню (reply-кнопки)
│   │   └── services/
│   │       └── api_client.py             # EventMindAPIClient — async-обёртка над всеми endpoint-ами
│   │
│   ├── core/                             # инфраструктура общего пользования
│   │   ├── config.py                     # pydantic-settings: BOT_TOKEN, DATABASE_URL, GROQ_*, …
│   │   ├── logging.py                    # setup_logging, get_logger
│   │   └── topics.py                     # TOPIC_TITLES, ALLOWED_TOPICS, FORMAT/CITY/LEVEL_LABELS
│   │
│   ├── db/                               # ORM-слой
│   │   ├── base.py                       # declarative Base
│   │   ├── session.py                    # SQLAlchemy engine + SessionLocal
│   │   ├── dependencies.py               # FastAPI get_db
│   │   └── models/                       # SQLAlchemy-модели
│   │       ├── user.py                   # User (topic_weights JSON, embedding JSON, is_subscribed)
│   │       ├── event.py                  # Event (+ summary, embedding, tech_stack, scores)
│   │       ├── raw_event.py              # RawEvent (статус: raw / normalized / non_it / failed)
│   │       ├── interaction.py            # Interaction (like / dislike / save)
│   │       └── topic.py                  # Topic, UserTopic, EventTopic (many-to-many)
│   │
│   ├── recommender/                      # модуль ранжирования и объяснений
│   │   ├── scoring.py                    # rule-based score: темы, веса, формат, город
│   │   ├── hybrid.py                     # blend rule + embedding cosine (0.5 * rule + 10 * sim)
│   │   ├── embeddings.py                 # sentence-transformers wrappers, кэш в БД
│   │   ├── explain.py                    # explain_event_for_user / explain_event_detailed
│   │   └── user_model.py                 # parse/dump topic_weights, apply_feedback_to_weights
│   │
│   ├── ingestion/                        # загрузка событий из внешних источников
│   │   └── sources/
│   │       └── habr.py                   # парсер habr.com/ru/events/ (BeautifulSoup + lxml)
│   │
│   ├── agents/                           # LangGraph-агенты на Groq LLM
│   │   ├── recommendation/               # граф из 4 нод
│   │   │   ├── llm.py                    # ChatGroq instance
│   │   │   ├── state.py                  # TypedDict-state графа
│   │   │   ├── user_profile_agent.py     # анализ профиля
│   │   │   ├── event_analyzer_agent.py   # анализ событий
│   │   │   ├── recommendation_agent.py   # ранжирование + сборка карточек
│   │   │   ├── explanation_agent.py      # человекочитаемое объяснение
│   │   │   └── graph.py                  # сборка StateGraph
│   │   ├── event_normalization/          # нормализация raw → event
│   │   │   ├── state.py
│   │   │   └── agent.py                  # извлекает format/city/level/topics/tech_stack/scores
│   │   └── copilot/                      # одно-нодовый граф AI Copilot
│   │       ├── state.py
│   │       └── agent.py                  # цель + профиль + события → roadmap
│   │
│   ├── scheduler/
│   │   └── digest.py                     # APScheduler, ежедневный AI-дайджест в Telegram
│   │
│   └── admin/                            # заготовка под admin-инструменты
│
├── alembic/                              # миграции БД
│   ├── env.py
│   └── versions/
│       ├── 6af520bb31e0_initial_schema.py
│       ├── 7b1c9d2e3a4f_add_summary_embedding_to_events.py
│       └── b3c4d5e6f7a8_add_enriched_fields.py
│
├── data/                                 # справочные источники
│   ├── events.json                       # курируемые события (load → /events/load)
│   └── events_raw.json                   # сырые события под /ingestion/load-raw
│
├── tests/                                # pytest-набор unit-тестов
│   ├── test_scoring.py
│   ├── test_user_model.py
│   ├── test_interactions.py
│   └── test_new_features.py
│
├── docs/                                 # документация курсовой
├── .env / .env.example                   # переменные окружения
├── alembic.ini                           # конфигурация Alembic
├── Dockerfile                            # python:3.12-slim + libxml2 + entrypoint API
├── docker-compose.yml                    # сервисы: api / bot / scheduler
├── pyproject.toml                        # ruff + mypy + pytest конфиг
├── requirements.txt                      # python-зависимости
└── README.md
```

---

## Стек

- **Python 3.12**
- **FastAPI 0.110** + **Uvicorn** — REST backend
- **aiogram 3.13** — Telegram-бот
- **SQLAlchemy 2.0** + **Alembic** — ORM и миграции
- **SQLite** по умолчанию (легко заменяется на PostgreSQL через `DATABASE_URL`)
- **LangGraph 0.2** + **LangChain Core** — оркестрация AI-агентов
- **langchain-groq** + Groq LLM (`llama-3.3-70b-versatile`)
- **sentence-transformers 2.7** — multilingual MiniLM embeddings
- **APScheduler 3.10** — cron-job дайджестов
- **BeautifulSoup 4 + lxml** — парсинг Habr
- **httpx** — HTTP-клиент бота
- **pydantic 2 / pydantic-settings**
- **pytest** — unit-тесты, **ruff** + **mypy** — линт/типы

---

## Модель данных

- `users` — `telegram_id`, `username`, `preferred_format`, `city`,
  `topic_weights` (JSON-string, `{topic_code: int}`),
  `is_subscribed` (0/1), `embedding` (JSON-вектор), `created_at/updated_at`.
- `events` — `title`, `description`, `format`, `city`, `level`, `date`,
  `event_type`, `target_audience`, `source_url`,
  `summary`, `embedding`, `tech_stack` (JSON-array),
  `seniority`, `quality_score` (1–10), `hype_score` (1–10).
- `raw_events` — `title`, `raw_description`, `source_url`,
  `status` (`raw` / `normalized` / `non_it` / `failed`), `error`.
- `topics` — `code` (`ai_ml`, `backend`, …), `title`.
- `user_topics`, `event_topics` — many-to-many связи.
- `interactions` — `user_id`, `event_id`, `action` (`like` / `dislike` / `save`), `created_at`.

Словари (`app/core/topics.py`) — **динамические**: проект стартует с seed-значений
и расширяется по мере поступления событий. Жёсткого whitelist'а нет.

- **topics** (seed): `ai_ml`, `data_science`, `business_analytics`, `backend`,
  `frontend`, `product`, `cybersecurity`, `devops`. Любой новый slug,
  пришедший от парсера/LLM, автоматически создаётся в таблице `topics`
  (`ensure_topic` / `_get_or_create_topic`).
- **format** (seed): `online`, `offline`, `hybrid`, `any`, `unknown`.
  Любая другая строка от LLM проходит через `slugify_code` и сохраняется
  как есть на `events.format` / `users.preferred_format`.
- **city** (seed): `moscow`, `spb`, `kazan`, `ekb`, `any`, `unknown` +
  всё, что появилось у спарсенных событий (`SELECT DISTINCT city FROM events`).
- **level** (seed): `beginner`, `middle`, `advanced`, `any`, `unknown` +
  любые новые уровни из событий.

Для UI лейблы вычисляются через `topic_title()`, `format_label()`,
`city_label()`, `level_label()` — если seed-словарь не знает кода,
автоматически возвращается humanized-вариант (`mlops_day` → `Mlops Day`).

Актуальный snapshot словаря доступен через `GET /vocabulary` и
`GET /vocabulary/{topics|cities|formats|levels}`.

---

## Установка и запуск

Требуется Python 3.12+.

```bash
# 1. Клонировать репозиторий и перейти в каталог
cd eventmind

# 2. (рекомендуется) создать виртуальное окружение
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Сконфигурировать переменные окружения
cp .env.example .env
# открыть .env и заполнить BOT_TOKEN, GROQ_API_KEY и т.д.

# 5. Применить миграции (создаст eventmind.db по умолчанию)
alembic upgrade head

# 6. (опционально) загрузить демо-события из data/events.json
curl -X POST http://localhost:8000/events/load
# или из data/events_raw.json + AI-нормализация:
curl -X POST http://localhost:8000/ingestion/load-raw
curl -X POST http://localhost:8000/ingestion/normalize
```

---

## Переменные окружения

Все переменные читаются через `pydantic-settings` из файла `.env`
(см. `app/core/config.py`).

| Переменная       | По умолчанию                  | Описание                                                       |
|------------------|-------------------------------|----------------------------------------------------------------|
| `BOT_TOKEN`      | —                             | Токен Telegram-бота. **Обязателен** для `app.bot.main` и `digest`. |
| `DATABASE_URL`   | `sqlite:///./eventmind.db`    | SQLAlchemy URL. Для PostgreSQL: `postgresql://user:pass@host:5432/db`. |
| `API_HOST`       | `http://localhost:8000`       | Базовый URL FastAPI, который дёргают bot и scheduler.          |
| `GROQ_API_KEY`   | —                             | Ключ Groq Cloud для LLM-агентов. Без него агенты падают, система деградирует до rule-based. |
| `GROQ_MODEL`     | `llama-3.3-70b-versatile`     | Имя модели Groq.                                               |
| `DEBUG`          | `false`                       | Включает verbose-логи и SQL echo.                              |
| `RSS_FEEDS`            | `""`        | Список RSS/Atom-лент через запятую для `/ingestion/load-rss`.        |
| `INGEST_ENABLED`       | `true`      | Включает периодический ingestion внутри scheduler-процесса.          |
| `INGEST_INTERVAL_HOURS`| `6`         | Период запуска `ingest_habr` / `ingest_rss` в часах.                 |
| `INGEST_HABR_LIMIT`    | `20`        | Сколько событий тянуть с Habr за один тик планировщика.              |
| `INGEST_RSS_LIMIT_PER_FEED` | `20`    | Лимит элементов на одну RSS-ленту за один тик.                       |

Файл `.env.example` уже содержит шаблон — скопируйте и подставьте свои значения.

---

## Запуск компонентов: API, Bot, Scheduler

EventMind — три **независимых процесса**. Запускайте их в отдельных терминалах
(или через docker-compose, см. ниже).

### 1) FastAPI backend

```bash
# dev-режим с авто-перезагрузкой
uvicorn app.api.main:app --reload

# prod-вариант
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Полезные URL после запуска:
- `http://localhost:8000/` — корневой ответ
- `http://localhost:8000/health` — healthcheck
- `http://localhost:8000/docs` — Swagger UI
- `http://localhost:8000/redoc` — ReDoc
- `http://localhost:8000/admin/` — HTML-дашборд

### 2) Telegram-бот

Бот ходит в API по адресу `API_HOST` и использует long-polling.

```bash
python -m app.bot.main
```

Перед первым стартом обязательно создайте бота через [@BotFather](https://t.me/BotFather)
и положите токен в `BOT_TOKEN`. Запуск без токена приведёт к
`ValueError: BOT_TOKEN не найден в .env`.

### 3) Scheduler (AI-дайджест)

Раз в 24 часа берёт подписчиков (`GET /subscriptions/users`), для каждого
получает топ AI-карточку (`GET /agent-recommendations/{tid}/cards`) и
отправляет её через Telegram Bot API (`https://api.telegram.org/bot<token>/sendMessage`).

```bash
python -m app.scheduler.digest
```

Зависит от запущенного API и валидного `BOT_TOKEN`.

---

## Запуск через Docker

В корне репо лежит `Dockerfile` и `docker-compose.yml` с тремя сервисами:
`api`, `bot`, `scheduler`. SQLite-файл и `data/` пробрасываются через volume.

```bash
docker compose up -d --build      # запустить все три сервиса
docker compose logs -f api        # логи API
docker compose down               # остановить
```

`bot` и `scheduler` стартуют только после того, как у `api` пройдёт healthcheck
`GET /health`. Внутри контейнеров `DATABASE_URL` указывает на `/app/eventmind.db`.

---

## Telegram-бот: команды и сценарии

| Команда / текст              | Что делает                                                                       |
|------------------------------|----------------------------------------------------------------------------------|
| `/start`                     | Запускает мастер настройки профиля (темы → формат → город). Сохраняет через API. |
| `/edit`                      | Перезапуск мастера, чтобы переопределить темы/формат/город.                      |
| `/profile`                   | Показывает текущий профиль и веса интересов.                                     |
| `/recommend`                 | Лента rule+embedding рекомендаций с inline-кнопками 👍 / 👎 / ⭐ и «Дальше».     |
| **AI-рекомендации** (кнопка) | Аналогичная лента, но карточки готовит LangGraph-граф (Groq LLM).                |
| `/saved`                     | Список сохранённых событий.                                                      |
| `/stats`                     | Личная статистика: лайки/дизлайки/сохранения, топ тем, последние действия.       |
| `/search <запрос>`           | Keyword-поиск по `title` / `description` / темам / формату / городу.             |
| `Найти: <запрос>`            | Reply-кнопка-эквивалент `/search`.                                               |
| `/semantic <запрос>`         | Семантический поиск через embeddings (cosine similarity).                        |
| `/bio <текст>`               | Холодный старт: LLM (или keyword-rules) извлекает темы из текста и обновляет профиль. |
| `/trending`                  | Горячие события и темы за 7 дней (likes×3 + saves×2).                            |
| `/copilot <цель>`            | AI Copilot: формирует roadmap-ответ + подбор событий под цель пользователя.      |
| `/subscribe`                 | Подписка на ежедневный AI-дайджест.                                              |
| `/unsubscribe`               | Отписка от дайджеста.                                                            |

Reply-меню — компактное, 4 кнопки: «🎯 Рекомендации» (открывает inline-пикер
«Обычные / AI»), «🔍 Поиск», «👤 Профиль» (под профилем inline-сабменю:
Избранное / Активность / Изменить профиль / AI-дайджест toggle),
«⚙️ Ещё» (Тренды / Copilot / Помощь). Все редкие действия живут
за inline-кнопками или slash-командами.

---

## Логика рекомендаций

Используется **hybrid scoring** — `app/recommender/hybrid.py`:

1. **Rule-based score** (`scoring.score_event_for_user`):
   - сумма `topic_weights[topic]` по темам события;
   - `+2` за каждое пересечение тем (явное совпадение профиля и события);
   - `+3` за полное совпадение `preferred_format == event.format`, `+1` за `format = any`;
   - `+2` за совпадение `city`, `+1` за `city = any`.
2. **Embedding similarity** (`embeddings.py`):
   - модель `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`;
   - user embedding строится из тем + весов + предпочтений + истории
     (`build_rich_user_embedding`); кэшируется в `users.embedding`;
   - event embedding — `title + description`, кэшируется в `events.embedding`;
   - сравнение через `cosine_similarity`.
3. **Итоговый score**: `rule * 0.5 + similarity * 10`.
   При недоступности `sentence-transformers` система плавно деградирует
   до чисто rule-based варианта.

**Обратная связь** (`user_model.apply_feedback_to_weights`):
- `like` → `+3` к весам соответствующих тем;
- `save` → `+1`;
- `dislike` → `-2` (минимальный вес = 0).
- Повторное нажатие той же кнопки отменяет действие (обратное изменение весов).

**Объяснения** (`explain.explain_event_detailed`) возвращают структуру:
`text`, `topic_match`, `format_match`, `city_match`, `semantic_similarity`,
`history_signals` (фразы вида «сохранял похожие темы», «лайкал похожие темы»,
«любит online-формат»).

---

## Пайплайн ingestion

1. Источник:
   - JSON-файл `data/events_raw.json` через `POST /ingestion/load-raw`,
   - HTML с Habr через `POST /ingestion/load-habr?limit=N`
     (см. `app/ingestion/sources/habr.py`),
   - произвольные RSS/Atom-ленты через `POST /ingestion/load-rss?limit_per_feed=N`
     (см. `app/ingestion/sources/rss.py`). Список лент задаётся в `.env`
     переменной `RSS_FEEDS=url1,url2,...`.
2. Запись попадает в таблицу `raw_events` со статусом `raw`.
3. `EventNormalizerAgent` (LangGraph + Groq LLM, `app/agents/event_normalization/`)
   получает сырое описание и возвращает JSON:
   `title, description, format, city, level, date, topics, event_type,
   target_audience, source_url, tech_stack, seniority, quality_score, hype_score`.
   - Промпт даёт LLM **seed-словари** как «предпочтительные» значения, но
     **разрешает создавать новые slug'и** для тем/городов/уровней, если в seed
     нет подходящего (например `mlops`, `novosibirsk`, `expert`).
   - Все возвращённые строки проходят через `slugify_code` → стабильный
     snake_case.
4. Не-IT события (`topics == []`) помечаются как `non_it` и НЕ попадают в `events`.
5. Если событие IT — проверяется дубль по `title`; если новое — создаётся `Event`,
   привязываются темы (`event_topics`). Новые темы автоматически появляются
   в таблице `topics` через `_get_or_create_topic` → `topic_title()` сразу
   получает корректный human-label.
6. Опционально считается `summary` и `embedding` (для `events`-таблицы).
7. Статус `raw_event` обновляется на `normalized` или `failed`
   (в случае ошибки записывается `error`).

Стартовать конвейер целиком:

```bash
curl -X POST "http://localhost:8000/ingestion/load-habr?limit=20"
# или RSS:
curl -X POST "http://localhost:8000/ingestion/load-rss?limit_per_feed=20"
# или вручную:
curl -X POST http://localhost:8000/ingestion/load-raw
curl -X POST http://localhost:8000/ingestion/normalize
curl http://localhost:8000/ingestion/status
```

**Автоматическое пополнение.** `app/scheduler/digest.py` помимо ежедневного
AI-дайджеста раз в `INGEST_INTERVAL_HOURS` часов (по умолчанию 6) дёргает
`/ingestion/load-habr` и `/ingestion/load-rss`. Включается переменной
`INGEST_ENABLED=true` (по умолчанию). Лимит за тик — `INGEST_HABR_LIMIT` и
`INGEST_RSS_LIMIT_PER_FEED`.

---

## LangGraph-агенты

Три графа в `app/agents/`:

### 1. Recommendation graph (`recommendation/graph.py`)

```
START → user_profile_agent → event_analyzer_agent
      → recommendation_agent → explanation_agent → END
```

State: `RecommendationState` (`user_profile`, `events`, `user_analysis`,
`events_analysis`, `ranked_event_ids`, `ranked_cards`, `final_answer`).

Возвращает финальный текст (`final_answer`) и набор карточек `ranked_cards`
(используются в `/agent-recommendations/{tid}/cards`).

### 2. Event normalization agent (`event_normalization/agent.py`)

Однонодовый агент, превращает «сырое» событие в нормализованный JSON.
Использует строгий system-prompt: фильтрует не-IT, clamp'ает scores в 1..10,
ограничивает темы списком `ALLOWED_TOPICS`.

### 3. Copilot graph (`copilot/agent.py`)

Однонодовый граф. Вход: `goal`, `user_profile`, `events`, `interaction_summary`.
Выход: дружелюбный roadmap-ответ + парсится `RECOMMENDED_IDS: [..]` для подсветки
карточек в Telegram (`/copilot`).

LLM-провайдер: `ChatGroq` (см. `app/agents/recommendation/llm.py`), модель
берётся из `GROQ_MODEL`.

---

## REST API: полный справочник endpoints

База: `http://localhost:8000`. Swagger: `/docs`, OpenAPI: `/openapi.json`.

### System

| Метод | URL        | Описание                                |
|-------|------------|-----------------------------------------|
| GET   | `/`        | Корневой ответ: `{"message", "docs"}`.  |
| GET   | `/health`  | Healthcheck: `{"status": "ok"}`.        |

### Users (`/users`)

| Метод | URL                                      | Тело / параметры                                                                 | Описание                                                              |
|-------|------------------------------------------|----------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| POST  | `/users/register`                        | JSON `UserCreate`: `telegram_id`, `username?`, `preferred_format?`, `city?`, `topics: list[str]` | Создаёт или обновляет пользователя, сохраняет `topic_weights`.        |
| GET   | `/users/{telegram_id}`                   | —                                                                                | Профиль пользователя. 404, если нет.                                  |
| GET   | `/users/{telegram_id}/stats`             | —                                                                                | `likes_count`, `dislikes_count`, `saves_count`, `top_topics`, `last_actions`. |
| POST  | `/users/{telegram_id}/analyze-bio`       | `{"bio": "<свободный текст>"}`                                                   | LLM/keyword извлекает темы и обновляет профиль (cold start).          |
| POST  | `/users/{telegram_id}/update-embedding`  | —                                                                                | Пересчитывает и кэширует персональный embedding пользователя.         |

### Events (`/events`)

| Метод | URL                                | Параметры                                                              | Описание                                                              |
|-------|------------------------------------|------------------------------------------------------------------------|-----------------------------------------------------------------------|
| POST  | `/events/load`                     | —                                                                      | Загружает события из `data/events.json` (если не дубликат по title).  |
| GET   | `/events/`                         | —                                                                      | Список всех событий с расширенным набором полей (summary, scores).    |
| GET   | `/events/search`                   | `q`, `topics` (csv), `format`, `city` — все опциональны                | Keyword-поиск по `title/description` + фильтры.                       |
| GET   | `/events/semantic-search`          | `q` (required), `limit` (1..20, по умолчанию 5)                        | Поиск по embedding-сходству.                                          |
| GET   | `/events/{event_id}/similar`       | `limit` (1..10, по умолчанию 3)                                        | События со схожими темами.                                            |

### Recommendations (`/recommendations`)

| Метод | URL                                                          | Тело / параметры                                | Описание                                                  |
|-------|--------------------------------------------------------------|-------------------------------------------------|-----------------------------------------------------------|
| GET   | `/recommendations/{telegram_id}`                             | —                                               | Hybrid-рекомендации, сортировка по `score` desc.          |
| POST  | `/recommendations/interactions`                              | `{"telegram_id", "event_id", "action": "like|dislike|save"}` | Сохраняет действие, апдейтит веса тем.                    |
| GET   | `/recommendations/{telegram_id}/event/{event_id}/interactions` | —                                             | Список действий пользователя по конкретному событию.      |
| GET   | `/recommendations/{telegram_id}/saved`                       | —                                               | Сохранённые события пользователя.                         |

### Agent recommendations (`/agent-recommendations`)

| Метод | URL                                                | Параметры                       | Описание                                                                       |
|-------|----------------------------------------------------|---------------------------------|--------------------------------------------------------------------------------|
| GET   | `/agent-recommendations/{telegram_id}`             | —                               | Прогон LangGraph-графа, возвращает `{success, answer}` (текстовый ответ LLM).  |
| GET   | `/agent-recommendations/{telegram_id}/cards`       | `limit` (1..10, по умолчанию 3) | Прогон графа + карточки. Fallback на rule-based, если LLM упал.                |

### Copilot (`/copilot`)

| Метод | URL                       | Тело                  | Параметры                       | Описание                                                                   |
|-------|---------------------------|-----------------------|---------------------------------|----------------------------------------------------------------------------|
| POST  | `/copilot/{telegram_id}`  | `{"goal": "<цель>"}`  | `limit` (1..10, по умолчанию 3) | LangGraph-агент Copilot: подбирает события и составляет roadmap под цель.  |

### Ingestion (`/ingestion`)

| Метод | URL                       | Параметры                       | Описание                                                                  |
|-------|---------------------------|---------------------------------|---------------------------------------------------------------------------|
| POST  | `/ingestion/load-raw`     | —                               | Заливает `data/events_raw.json` в `raw_events`.                           |
| POST  | `/ingestion/load-habr`    | `limit` (default 20)            | Парсит habr.com/ru/events, сохраняет в `raw_events`, сразу нормализует.   |
| POST  | `/ingestion/load-rss`     | `limit_per_feed` (default 20)   | Парсит все ленты из `RSS_FEEDS`, сохраняет в `raw_events`, нормализует.   |
| POST  | `/ingestion/normalize`    | —                               | Нормализует все `raw_events.status == 'raw'` через AI-агента.             |
| GET   | `/ingestion/status`       | —                               | Счётчики `total / raw / normalized / non_it / failed`.                    |

### Subscriptions (`/subscriptions`)

| Метод | URL                                              | Описание                                              |
|-------|--------------------------------------------------|-------------------------------------------------------|
| POST  | `/subscriptions/{telegram_id}/subscribe`         | Включает подписку на AI-дайджест.                     |
| POST  | `/subscriptions/{telegram_id}/unsubscribe`       | Выключает подписку.                                   |
| GET   | `/subscriptions/subscribers`                     | Список подписчиков (используется scheduler-ом).       |
| GET   | `/subscriptions/users`                           | Обратно-совместимый алиас `/subscribers`.             |

### Admin (`/admin`)

| Метод | URL        | Описание                                                                  |
|-------|------------|---------------------------------------------------------------------------|
| GET   | `/admin/`  | HTML-дашборд: количество юзеров/событий/подписчиков/взаимодействий + последние 10 событий. |

### Vocabulary (`/vocabulary`)

| Метод | URL                       | Описание                                                                                |
|-------|---------------------------|-----------------------------------------------------------------------------------------|
| GET   | `/vocabulary`             | Полный snapshot: `{topics, cities, formats, levels}`. Используется ботом и фронтом.     |
| GET   | `/vocabulary/topics`      | `[{code, title}, ...]` — seed + темы из таблицы `topics`.                               |
| GET   | `/vocabulary/cities`      | Seed + `DISTINCT city` из `events` / `users`.                                           |
| GET   | `/vocabulary/formats`     | Seed + `DISTINCT format` из `events` / `users`.                                         |
| GET   | `/vocabulary/levels`      | Seed + `DISTINCT level` из `events`.                                                    |

### Analytics (`/analytics`)

| Метод | URL                      | Параметры                                      | Описание                                                                |
|-------|--------------------------|------------------------------------------------|-------------------------------------------------------------------------|
| GET   | `/analytics/topics`      | —                                              | Топ лайкнутых/сохранённых/дизлайкнутых тем + средние веса по юзерам.    |
| GET   | `/analytics/interactions`| —                                              | Сумма действий по `action` + топ событий по интеракциям.                |
| GET   | `/analytics/trending`    | `days` (1..90, по умолчанию 7), `limit` (1..50)| Горячие события (`likes×3 + saves×2`) и trending-темы.                  |

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

# AI Copilot
curl -X POST "http://localhost:8000/copilot/1?limit=3" \
  -H "Content-Type: application/json" \
  -d '{"goal":"хочу разобраться в Kubernetes и SRE"}'

# Habr → нормализация
curl -X POST "http://localhost:8000/ingestion/load-habr?limit=10"

# Trending
curl "http://localhost:8000/analytics/trending?days=7&limit=5"
```

---

## Admin-дашборд

После запуска API открой `http://localhost:8000/admin/` — увидишь
HTML-страницу с карточками:
- пользователи, события, подписчики, взаимодействия;
- статусы ingestion (`raw / normalized / failed`);
- таблица последних 10 событий.

Реализация — `app/api/routers/admin.py` (без шаблонизатора, статичный HTML).

---

## Тесты

```bash
pytest                  # запустить весь набор
pytest tests/test_scoring.py -v
```

Состав:
- `test_scoring.py` — rule-based scoring (темы, веса, формат, город).
- `test_user_model.py` — парсинг / сериализация весов, применение фидбэка.
- `test_interactions.py` — like / dislike / save и обновление весов.
- `test_new_features.py` — embeddings, hybrid, explain, ingestion-helpers.

---

## Миграции

```bash
# применить последние миграции
alembic upgrade head

# создать новую миграцию по diff'у моделей
alembic revision --autogenerate -m "add some field"

# откат на одну ревизию
alembic downgrade -1
```

История миграций в `alembic/versions/`:
- `6af520bb31e0_initial_schema` — базовые таблицы;
- `7b1c9d2e3a4f_add_summary_embedding_to_events` — поля `summary`, `embedding`;
- `b3c4d5e6f7a8_add_enriched_fields` — `tech_stack`, `seniority`,
  `quality_score`, `hype_score`.

---

## Минимальный happy-path

```bash
# терминал 1 — API
alembic upgrade head
uvicorn app.api.main:app --reload

# терминал 2 — бот
python -m app.bot.main

# терминал 3 — (опционально) дайджесты
python -m app.scheduler.digest

# терминал 4 — наполнить событиями
curl -X POST http://localhost:8000/events/load
# или AI-pipeline:
curl -X POST "http://localhost:8000/ingestion/load-habr?limit=20"
```

После этого в Telegram пишем боту `/start`, проходим мастер и нажимаем
«Рекомендации» / «AI-рекомендации».
