# EventMind — заметки для будущих сессий с Claude Code

Этот файл автоматически загружается в контекст каждой новой сессии. Цель —
дать AI-ассистенту быстро войти в курс дела без переспрашивания базовых вещей.

## Что это за проект

EventMind — система агрегации IT-мероприятий и персонализированных
рекомендаций. Три независимых процесса вокруг общей БД:

- **api** — REST на FastAPI + Uvicorn (`app/api`)
- **bot** — Telegram-клиент на aiogram 3 (`app/bot`)
- **scheduler** — фоновые джобы APScheduler: дайджест, ingestion, compaction
  памяти (`app/scheduler`)

## Стек

- Python 3.12 в `.venv/`. Путь к исполняемым файлам зависит от ОС:
  macOS/Linux — `.venv/bin/<tool>`, Windows — `.venv\Scripts\<tool>.exe`
  (например `.venv\Scripts\python.exe`, `.venv\Scripts\pytest.exe`).
- FastAPI 0.110, aiogram 3.13, SQLAlchemy 2.0 + Alembic, Pydantic 2
- LangGraph 0.2 + langchain-groq (primary `llama-3.3-70b-versatile`, fallback
  `llama-3.1-8b-instant`)
- sentence-transformers 2.7 (MiniLM-L12-v2, 384 dim, русский)
- SQLite (dev) / PostgreSQL + pgvector (prod)
- pytest 8.2 (172 теста), ruff

## Запуск (dev)

Код кроссплатформенный — различаются только путь к venv и shell-синтаксис.
Сам `.venv` НЕ переносится между ОС (и не в git) — на каждой машине
создаётся заново под её платформу.

### macOS / Linux (bash/zsh)

```bash
# первый раз
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env       # вписать BOT_TOKEN, GROQ_API_KEY
.venv/bin/alembic upgrade head

# процессы — каждый в своём терминале
.venv/bin/uvicorn app.api.main:app --reload
.venv/bin/python -m app.bot.main
.venv/bin/python -m app.scheduler.digest
```

Проверки: `curl localhost:8000/health`, `.venv/bin/pytest -q`, `.venv/bin/ruff check .`.

### Windows (PowerShell)

```powershell
# первый раз — venv именно на 3.12 (py -3.12), не на более новой версии:
# старые пины (torch, sentence-transformers, pydantic) не имеют колёс под 3.13+
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # вписать BOT_TOKEN, GROQ_API_KEY
.\.venv\Scripts\alembic.exe upgrade head

# процессы — каждый в своём терминале
.\.venv\Scripts\uvicorn.exe app.api.main:app --reload
.\.venv\Scripts\python.exe -m app.bot.main
.\.venv\Scripts\python.exe -m app.scheduler.digest
```

Проверки: `curl localhost:8000/health`, `.\.venv\Scripts\pytest.exe -q`,
`.\.venv\Scripts\ruff.exe check .`.

> Windows-нюанс: HuggingFace кэширует модель MiniLM через симлинки, которых
> Windows без Developer Mode не поддерживает — кэш работает «деградированно»
> (чуть больше места на диске, на функциональность не влияет). Чтобы убрать
> предупреждение: `setx HF_HUB_DISABLE_SYMLINKS_WARNING 1` или включить
> Developer Mode.

## Ключевые dev-флаги в `.env`

- `DIGEST_INTERVAL_MINUTES=10` + `DIGEST_RUN_ON_STARTUP=true` — увидеть
  дайджест прямо сейчас (default 1440 / false).
- `INGEST_ENABLED=true`, `INGEST_INTERVAL_HOURS=6` — периодический ingestion.
- `GNN_ENABLED=false` по умолчанию (на малом датасете шумит).
- `MEMORY_ENABLED=true` — long-term память пользователя.

## Архитектура рекомендера (hybrid из 9 компонент)

Полное описание — в `docs/Обзор_проекта_EventMind.docx` глава 7. Кратко:

| Компонент | Парадигма | Где | Вес |
|-----------|-----------|-----|-----|
| rule | rule-based | `recommender/scoring.py` | 0.5 |
| cosine | content-based (embeddings) | `recommender/embeddings.py` | 10.0 |
| bayesian | Thompson sampling | `recommender/bayesian.py` | 5.0 |
| quality | LLM-оценка 1–10 | `events.quality_score` | 0.5 |
| hype | LLM-оценка 1–10 | `events.hype_score` | 0.3 |
| freshness | exp-decay по дате | `recommender/hybrid.py` | 2.0 |
| skill_gap | goal-aware | `recommender/skill_gap.py` | 3.0 |
| bandit | LinUCB contextual | `recommender/bandit.py` | 2.0 |
| gnn | LightGCN collaborative | `recommender/gnn.py` | 3.0 (выкл) |

Поверх — MMR-rerank (λ=0.7). Все компоненты в `app/recommender/hybrid.py`,
каждая в try/except — сбой одной не ломает выдачу.

## AI Copilot

LangGraph Supervisor-Worker граф в `app/agents/copilot/`:
`retrieve → supervisor → один из 5 specialists → finalize`.

5 специалистов: `recommendation`, `career_coach`, `roadmap`, `explainer`,
`summary`. 6 function-calling tools в `app/agents/copilot/tools.py`
(`TOOL_DEFINITIONS`): `search_events`, `get_user_profile`,
`get_interactions_summary`, `explain_event`, `recall_about_user`,
`mark_saved`. Подмножество tools на специалиста раздаётся через
`filter_tools(...)`.

Сессии мульти-туровые — состояние в таблице `copilot_sessions`. В боте —
`app/bot/handlers/copilot.py`, активная сессия 15 минут.

## Соглашения по коду

- При `Exception` во время `db.flush()` обязательно `db.rollback()` —
  иначе SQLAlchemy уходит в `PendingRollbackError` и ломает запрос. Свежий
  прецедент: `refresh_user_embedding` в
  `app/api/services/recommendation_service.py` — без rollback'а вся
  `/recommendations` валилась 500-кой при «database is locked».
- Все обращения LLM идут через `app/agents/recommendation/llm.py` — там
  однократный fallback primary → fallback model.
- Никаких «временно недоступен» без `logger.exception` — иначе причину не
  выяснить. В `/copilot` и `/agent-recommendations` логирование уже стоит.
- В Telegram-боте использовать `app/bot/utils.send` (HTML + plain-fallback)
  вместо прямого `message.answer`.
- Никогда не коммитить `.env`, `eventmind.db`, `data/` (см. `.gitignore`).

## Тесты

172 кейса в `tests/`. Запуск: `.venv/bin/pytest -q` (macOS/Linux) или
`.\.venv\Scripts\pytest.exe -q` (Windows). ~30 с на тёплом кэше; первый
прогон на новой машине дольше — докачивается модель MiniLM (~120 МБ).
На Postgres-`DATABASE_URL` 3 SQLite-PRAGMA теста (`test_db_session`) пропускаются.
Ключевые файлы: `test_scoring`, `test_multi_objective`,
`test_bayesian`/`test_bayes_decay`, `test_bandit`, `test_gnn`,
`test_memory`/`test_memory_integration`, `test_dedup`, `test_supervisor`,
`test_copilot_tools`, `test_copilot_graph_e2e`, `test_cold_start`,
`test_scheduler`.

## Документация

- `docs/Обзор_проекта_EventMind.docx` — авторитетный summary архитектуры
  и состояния. Глава 7 — подробно про рекомендер (9 компонент).
- `docs/План_показа_EventMind.docx` — план защиты на 15–20 минут с
  глоссарием.
- `docs/отчет_Курсовая.docx` — HSE-стилизованный отчёт (введение → 5 глав
  → заключение → глоссарий → библиография).
- Все три перегенерируются скриптом `python -m scripts.regenerate_docs` —
  идемпотентно, под текущую реализацию.

## Ingestion (загрузка событий)

6 источников (`app/ingestion/sources/`): habr, rss, kudago, luma, meetup,
telegram. Эндпоинты в `app/api/routers/ingestion.py`:

- `POST /ingestion/load-<source>` — один источник.
- `POST /ingestion/load-all?limit=N` — **все источники по очереди**, каждый
  изолирован try/except + rollback, агрегированные totals.
- `POST /ingestion/normalize` — дообработать `raw`-события.
- `POST /ingestion/retry-failed` — переобработать `failed` (после сброса
  лимита Groq).
- `GET /ingestion/status` — счётчики по статусам raw_events.

Пайплайн: source → `raw_events` → AI-нормализация (Pydantic) → `events`.
Нормализация **батчевая** (`event_normalizer_agent_batch`, пачки по 5 — кратно
меньше токенов); на rate-limit (429/TPD) обработка останавливается рано и
оставляет остаток в `raw` (не `failed`) — доберётся следующим `/normalize`.
`embedding_vec` (pgvector) пишется сразу через `_write_embedding`.

## Бэклог доработок

`IMPROVEMENTS.md` в корне — живой список доработок (сделанные `[x]` +
открытые `[ ]`, с привязкой к файлам, по приоритету). **Держать в актуальном
состоянии при каждом изменении** (как и этот файл).

## Текущее состояние (29 мая 2026)

Активная ветка: `dev`.

**Инфраструктура:** dev-БД переехала на **Supabase Postgres** (session pooler,
IPv4) — pgvector 0.8.0 активен, retrieval идёт по `<=>`. `DATABASE_URL` в
`.env`. `pool_pre_ping=True` в `app/db/session.py`. SQLite-PRAGMA тесты
`skipif` при не-SQLite. Подробности — память `dev-db-supabase`.

**Свежие правки:**

1. `/recommendations`: кандидатный отбор через pgvector (top-300 на PG,
   fallback на весь каталог на SQLite) + `joinedload(event_topics)` против
   N+1; тяжёлый `explain_event_detailed` — только для top-N (+ `limit`).
2. Ingestion: `/load-all`, `/retry-failed`, батчинг нормализации + early-stop
   на rate-limit, запись `embedding_vec` при ingestion.
3. Ops: scheduler переведён на `logging` (не `print`); `ruff` = 0 ошибок по
   репо (+ per-file-ignores E402 для tests/alembic/scripts); CI на GitHub
   Actions (`.github/workflows/ci.yml`: ruff + pytest на push/PR).
4. Кроссплатформенные команды (macOS/Linux + Windows) в этом файле +
   `.env.example`; `ruff` и `python-docx` в `requirements.txt`.
5. (ранее) rollback в `refresh_user_embedding`; `logger.exception` в
   `/copilot` и `/agent-recommendations`; параметризуемый дайджест;
   чистка англицизмов в «Почему»; UX-правки `/start` и `tour:skip`.
