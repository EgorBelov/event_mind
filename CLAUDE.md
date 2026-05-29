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

- Python 3.12 в `.venv/` (используй `.venv/bin/python` и `.venv/bin/pytest`)
- FastAPI 0.110, aiogram 3.13, SQLAlchemy 2.0 + Alembic, Pydantic 2
- LangGraph 0.2 + langchain-groq (primary `llama-3.3-70b-versatile`, fallback
  `llama-3.1-8b-instant`)
- sentence-transformers 2.7 (MiniLM-L12-v2, 384 dim, русский)
- SQLite (dev) / PostgreSQL + pgvector (prod)
- pytest 8.2 (170 тестов), ruff

## Запуск (dev)

```bash
# первый раз
cp .env.example .env       # вписать BOT_TOKEN, GROQ_API_KEY
.venv/bin/alembic upgrade head

# процессы — каждый в своём терминале
.venv/bin/uvicorn app.api.main:app --reload
.venv/bin/python -m app.bot.main
.venv/bin/python -m app.scheduler.digest
```

Проверки: `curl localhost:8000/health`, `pytest -q`, `ruff check .`.

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
`summary`. 5 function-calling tools в `app/agents/copilot/tools.py`:
`search_events`, `get_user_profile`, `get_recent_interactions`,
`recall_about_user`, `get_event_details`.

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

170 кейсов в `tests/`. Запуск: `.venv/bin/pytest -q` (~30 с).
Ключевые файлы: `test_scoring`, `test_hybrid`/`test_multi_objective`,
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

## Текущее состояние (29 мая 2026)

Активная ветка: `dev`. Свежий пакет правок:

1. Починен `GET /recommendations` (rollback в `refresh_user_embedding`) —
   раньше при «database is locked» падало 500 → бот показывал «Пока нет
   рекомендаций» при настроенном профиле.
2. В `/copilot` и `/agent-recommendations` добавлены `logger.exception`
   во всех ветках fallback'а.
3. Дайджест: `DIGEST_INTERVAL_MINUTES` и `DIGEST_RUN_ON_STARTUP` — теперь
   настраивается через `.env`.
4. Чистка англицизмов в «Почему» (нет «Bayesian Thompson», «LinUCB»,
   «LightGCN» в пользовательском UI).
5. `/start` теперь сбрасывает старую reply-клавиатуру через
   `ReplyKeyboardRemove` — кнопка «Начать настройку» больше не
   дублируется.
6. Пропуск тура (`tour:skip`) даёт отдельное сообщение с инлайн-кнопкой
   «🚀 Начать настройку».
7. Регенерация docs/ под текущую реализацию (`scripts/regenerate_docs.py`).
