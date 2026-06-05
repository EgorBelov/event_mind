# EventMind — заметки для будущих сессий с Claude Code

Этот файл автоматически загружается в контекст каждой новой сессии. Цель —
дать AI-ассистенту быстро войти в курс дела без переспрашивания базовых вещей.

## Что это за проект

EventMind — система агрегации IT-мероприятий и персонализированных
рекомендаций. Курсовая ВКР, перерастающая в магистерскую. Три независимых
процесса вокруг общей БД:

- **api** — REST на FastAPI + Uvicorn (`app/api`)
- **bot** — Telegram-клиент на aiogram 3 (`app/bot`)
- **scheduler** — фоновые джобы APScheduler: дайджест, ingestion, backfill
  embeddings, compaction памяти (`app/scheduler`)

## Стек

- Python 3.12 в `.venv/`. Путь к исполняемым файлам зависит от ОС:
  macOS/Linux — `.venv/bin/<tool>`, Windows — `.venv\Scripts\<tool>.exe`.
- FastAPI 0.110, aiogram 3.13, SQLAlchemy 2.0 + Alembic 1.13, Pydantic 2
- LangGraph 0.2; **LLM-цепочка** (см. ниже): Gemini → Groq 70b → Groq 8b
- sentence-transformers 2.7 (MiniLM-L12-v2, 384 dim, multilingual/русский)
- **PostgreSQL + pgvector** на Supabase (dev и prod). SQLite остаётся только
  для in-memory модульных тестов; CI прогоняется на pgvector/pgvector:pg16.
- pytest 8.2 (369 тестов), ruff 0.6

## LLM (важно для модификаций)

Цепочка провайдеров живёт в `app/agents/recommendation/llm.py::_LLMChain`.
На каждом `llm.invoke()` цикл идёт по звеньям до первого успеха:

1. **Gemini** — primary, через `langchain-google-genai` с `transport="rest"`
   (gRPC у Google на macOS/AdGuard режется по DNS).
   - `_probe_gemini_model()` на старте API делает HTTP-POST по списку
     кандидатов и берёт первую с `200`. Сохраняется до перезапуска или
     `POST /admin/llm/reprobe`. Список fallback'ов — `_GEMINI_FALLBACK_MODELS`
     в llm.py; если в `.env` задан `GOOGLE_MODEL` — он идёт первым.
   - Free-tier лимиты часто меняются без предупреждения (20 RPD на
     2.5-flash, 0 на legacy 1.5-flash). Поэтому жёстко не привязываемся.
2. **Groq 70b** (`llama-3.3-70b-versatile`) — fallback.
3. **Groq 8b** (`llama-3.1-8b-instant`) — last-resort fallback.

Поверх есть **circuit-breaker** (5 подряд фейлов цепочки → cooldown 120с) и
**per-provider cooldown** (2 подряд на одном звене → skip на 10 мин).

`with_structured_output` навешивается на первое включённое звено.
`bind_tools` возвращает новую цепочку с привязанными tools (для LangGraph).

## Запуск (dev)

### macOS / Linux (bash/zsh)

```bash
# первый раз
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env       # вписать BOT_TOKEN, GOOGLE_API_KEY, GROQ_API_KEY
.venv/bin/alembic upgrade head

# процессы — каждый в своём терминале
.venv/bin/uvicorn app.api.main:app --reload
.venv/bin/python -m app.bot.main
.venv/bin/python -m app.scheduler.digest
```

Проверки: `curl localhost:8000/health`, `.venv/bin/pytest -q`,
`.venv/bin/ruff check .`.

### Windows (PowerShell)

```powershell
# первый раз — venv именно на 3.12 (py -3.12), не на более новой версии:
# старые пины (torch, sentence-transformers, pydantic) не имеют колёс под 3.13+
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # вписать BOT_TOKEN, GOOGLE_API_KEY, GROQ_API_KEY
.\.venv\Scripts\alembic.exe upgrade head

# процессы — каждый в своём терминале
.\.venv\Scripts\uvicorn.exe app.api.main:app --reload
.\.venv\Scripts\python.exe -m app.bot.main
.\.venv\Scripts\python.exe -m app.scheduler.digest
```

> Windows-нюанс: HuggingFace кэширует MiniLM через симлинки, которых
> Windows без Developer Mode не поддерживает — кэш работает «деградированно».
> Чтобы убрать предупреждение: `setx HF_HUB_DISABLE_SYMLINKS_WARNING 1`.

## Ключевые dev-флаги в `.env`

См. `.env.example` для полного списка. Самое важное:

- `GOOGLE_API_KEY` / `GROQ_API_KEY` — хотя бы один обязателен.
- `GOOGLE_MODEL=` (пустой) — автопроба сама подберёт работающую Gemini.
- `API_SHARED_SECRET=` — пустой в dev (auth выключен); на проде задать.
- `DATABASE_URL=postgresql+psycopg2://...` для Supabase; иначе SQLite.
- `DIGEST_INTERVAL_MINUTES=10` + `DIGEST_RUN_ON_STARTUP=true` — увидеть
  дайджест прямо сейчас (default 1440 / false).
- `INGEST_ENABLED=true`, `INGEST_INTERVAL_HOURS=6` — периодический ingestion.
- `GNN_ENABLED=false` по умолчанию (на малом датасете шумит).
- `MEMORY_ENABLED=true` — long-term память пользователя.
- `RECOMMENDATION_CACHE_ENABLED=true`, `RECOMMENDATION_CACHE_TTL_MINUTES=15`.

## Архитектура рекомендера (hybrid из 9 компонент)

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

Поверх — MMR-rerank (λ=0.7) + **series anti-flood**: если у событий одинаковый
`series_slug`, в выдаче остаётся выпуск, ближайший по `start_at` к now.
Все компоненты — в try/except, сбой одной не ломает выдачу.

### Read-only hot-path

`GET /recommendations` сейчас **read-only**: не вызывает `refresh_user_embedding`
и `ensure_event_embeddings` (раньше каждый GET писал по UPDATE на Supabase).
Прогрев `user.embedding` идёт на пишущих путях
(`create_or_update_user`, `analyze_bio`, `create_interaction`).
Прогрев `event.embedding` — при ingestion + scheduler-джоб
`backfill_event_embeddings` (раз в час) и `backfill_user_embeddings` (раз в 4 ч).

### TTL-кэш рекомендаций

`recommendation_cache` (PK `telegram_id`, TTL 15 мин). Hit пропускает весь
скоринг. Инвалидируется на feedback / register / edit / analyze-bio.

## AI Copilot (временно скрыт в боте)

LangGraph Supervisor-Worker граф в `app/agents/copilot/`:
`retrieve → supervisor → один из 5 specialists → finalize`. Код и API
остаются (`POST /copilot/{tid}/turn`, таблица `copilot_sessions`), но
**роутер `app/bot/handlers/copilot.py` не подключается в `app/bot/main.py`**:
после демонстрации руководителю UX признан кривым и будет переработан.
Кнопки/команды `/copilot` из меню и тура убраны.

5 специалистов: `recommendation`, `career_coach`, `roadmap`, `explainer`,
`summary`. 6 function-calling tools в `app/agents/copilot/tools.py`.
**LLM-compaction**: при превышении истории сжимаем середину одним
system-summary turn'ом (см. `copilot.py::_compact_history`).

## NL-поиск событий

`POST/GET /events/nl-search?q=<...>` — пользователь пишет фразу обычным
языком («конференции по AI с 3 по 10 июня в Москве», «онлайн вебинары»),
LLM с `with_structured_output` извлекает фильтры в Pydantic-схему
`SearchFilters`: `{date_from, date_to, city, event_type, format, topics,
free_text}`.

Сервис: `app/api/services/nl_search_service.py`.
- **LRU-кэш** по нормализованному запросу (256 записей) — одна и та же
  фраза не дёргает LLM повторно.
- **Канонизация** на постпроцессе: `canonicalize_city` сворачивает алиасы
  (msk→moscow, piter→spb), event_type/format проверяются против closed-доменов
  нормализатора (`_ALLOWED_EVENT_TYPE`, `_ALLOWED_FORMAT`).
- **Строгий проход** → до 5 совпадений.
- **Relax-fallback** при 0: поэтапно снимаем фильтры в порядке
  `free_text → topics → format → event_type → city → date`, при первом
  непустом наборе показываем **1 ближайшее событие** + CTA «🎯 К рекомендациям».
- **NULL-сейф для дат только в `upcoming_only`**: при явном диапазоне
  (`date_from`/`date_to`) события без `start_at` ОТСЕИВАЮТСЯ (раньше
  хабровские статьи без даты пролезали в выдачу под «в августе»).

UI бота: `app/bot/handlers/search.py`. Sticky waiting-state (60 мин),
после ввода НЕ сбрасывается — пользователь может писать запрос за
запросом. Под последним результатом — кнопки «⭐ Сохранить» (Interaction
`save`) и «🔍 Новый поиск».

## Карточка события и кнопки

- **Одна кнопка «📖 Подробнее»** в карточке рекомендации (была пара
  «❓ Почему / 📖 Подробнее»). Зовёт `GET /events/{id}/explain` — сервис
  `app/api/services/event_explain_service.py`: LLM пишет человеческое
  описание события без скоров и метрик. In-memory кэш TTL 6 ч, общий
  для всех пользователей.
- **Ссылка на источник** во всех местах рендера — хелпер
  `app/bot/utils.py::event_url_line(event)`. URL экранируется как
  HTML-атрибут (Telegram строго парсит href).
- **Локализация даты**: `format_event_date` смотрит на **raw** `start_at`
  ДО конвертации зоны — если часы/минуты нулевые, показываем только дату
  (без вымышленного «03:00 Moscow» от полночи UTC). Голая ISO-строка
  `"2026-06-16"` тоже переводится в «16 июня 2026».

## Фильтр прошедших событий

`app/db/event_filters.py::upcoming_only(query, grace_hours=6)` — общий
SQL-фильтр. NULL-сейф: события без `start_at` остаются. Применён в
рекомендациях, всех видах поиска, `cb_similar` и `retrieval` (copilot).
БД ничего не удаляет — interactions/история продолжают учить bayesian/bandit.

## API security / ops

- **`ApiKeyMiddleware`** (`app/api/middleware.py`): `X-API-Key` через
  `hmac.compare_digest` против `settings.api_shared_secret`. Пустой
  секрет = open-mode (dev). Whitelist: `/`, `/health`, `/docs`,
  `/redoc`, `/openapi.json`. Бот и scheduler шлют заголовок ВО ВСЕ
  запросы (см. `_auth_headers()` / `_api_headers()`).
- **`RequestLogMiddleware`**: одна строка на запрос —
  `METHOD PATH -> STATUS (rid=…, NN.NNms)`. Логгер `eventmind.access`.
  Уровень от кода: 5xx ERROR, 4xx WARNING, прочее INFO. Прокидывает
  X-Request-ID.
- **HTTPException handler**: 4xx → короткий WARNING без traceback,
  5xx → ERROR. Все ответы содержат `X-Request-ID`.
- **`config_validate`** (`app/core/config_validate.py`): per-context
  required-поля. `validate_or_exit(ctx)` → код 78 (EX_CONFIG).

## Соглашения по коду

- При `Exception` во время `db.flush()`/`db.commit()` обязательно
  `db.rollback()` — иначе SQLAlchemy уходит в `PendingRollbackError`.
- Все обращения LLM — только через `from app.agents.recommendation.llm import llm`.
- Никаких `print` — везде `logging`.
- В Telegram-боте использовать `app/bot/utils.send` вместо прямого
  `message.answer` (HTML + plain-fallback).
- Пользовательский ввод в LLM-промпт оборачивать через
  `prompt_safety.sanitize_user_text` + `wrap_user_text(<user_input>...)`.
- Никогда не коммитить `.env`, `eventmind.db`, `data/` (см. `.gitignore`).

## Тесты

**369 кейсов** в `tests/`. Запуск: `.venv/bin/pytest -q` (~80–95 с на тёплом
кэше; первый прогон дольше — докачивается MiniLM ~120 МБ). На
Postgres-`DATABASE_URL` 3 SQLite-PRAGMA теста пропускаются.

Ключевые файлы:
- Скоринг: `test_scoring`, `test_multi_objective`, `test_bayesian`/`test_bayes_decay`,
  `test_bandit`, `test_gnn`, `test_skill_gap`.
- Рекомендер: `test_get_recommendations`, `test_recommendation_cache`,
  `test_feed_cursor`, `test_dedup`, `test_series`, `test_retrieval`.
- Поиск: `test_nl_search` (27), `test_events_router_routing` (3),
  `test_past_events_filter` (5).
- Бот: `test_event_url_line` (4), `test_date_localization` (6),
  `test_event_explain` (6).
- Ingestion: `test_ingestion`, `test_multi_source`.
- Память: `test_memory`/`test_memory_integration`, `test_memory_hard_cap`,
  `test_cold_start`.
- AI: `test_supervisor`, `test_copilot_tools`, `test_copilot_graph_e2e`,
  `test_specialists`, `test_llm_circuit_breaker`, `test_gemini_probe`.
- Security/ops: `test_api_key_auth`, `test_config_validate`, `test_middleware`,
  `test_prompt_safety`.
- Данные: `test_enum_validation`, `test_ingestion_idempotent`,
  `test_city_canonicalization`.
- Прочее: `test_scheduler`, `test_interactions`, `test_pgvector`,
  `test_db_session`.

## Документация

- `docs/Обзор_проекта_EventMind.docx` — авторитетный summary архитектуры.
- `docs/План_показа_EventMind.docx` — план защиты на 15–20 минут.
- `docs/отчет_Курсовая.docx` — HSE-стилизованный отчёт (Глава 4 содержит
  Таблицу 4.2 — Recall@k / nDCG@k и Таблицу 4.3 — оценки LLM-судьи;
  обе сгенерированы воспроизводимыми скриптами с фиксированным `seed=42`).
- Бэкап последней «чистой» версии отчёта — `docs/отчет_Курсовая_backup_*.docx`.
- Все три перегенерируются `python -m scripts.regenerate_docs`.

## Оценочные скрипты (offline eval)

- `scripts/eval_offline.py` — leave-one-out на реальной БД (требует
  ≥3 positive-сигнала на пользователя). Output: Recall@k, nDCG@k для
  rule / hybrid / bayesian.
- `scripts/eval_offline_synthetic.py` — тот же leave-one-out на
  изолированном синтетическом датасете (in-memory SQLite, seed=42,
  20 пользователей × 80 событий × 8 тем). Используется на этапе
  прототипа, когда реальных positive-сигналов недостаточно.
- `scripts/llm_judge.py` — LLM-as-judge на реальной БД.
- `scripts/llm_judge_synthetic.py` — LLM-as-judge на синтетическом
  датасете (через `build_synthetic_db()` из первого). Прямые
  `SystemMessage`/`HumanMessage` (без `ChatPromptTemplate` — JSON-промпт
  ломал placeholder-синтаксис).

## Ingestion

6 источников (`app/ingestion/sources/`): habr, rss, kudago, luma, meetup,
telegram. Эндпоинты в `app/api/routers/ingestion.py`:

- `POST /ingestion/load-<source>` — один источник.
- `POST /ingestion/load-all?limit=N` — все источники по очереди,
  изоляция try/except + rollback, агрегированные totals.
- `POST /ingestion/normalize` — дообработать `raw`-события.
- `POST /ingestion/retry-failed` — переобработать `failed`.
- `GET /ingestion/status` — счётчики по статусам raw_events.

Пайплайн: source → `raw_events` → AI-нормализация (Pydantic-валидация +
строгая валидация ISO-даты + defence-in-depth в `_persist_normalized`) →
`events`. Нормализация **батчевая**: `_adaptive_batch_size` подбирает
размер чанка из средней длины описаний (target ~6000 символов, в [2..10]).
На rate-limit обработка останавливается рано, остаток в `raw`.
`embedding_vec` (pgvector) пишется сразу. `series_slug` (см.
`recommender/series.py`) — снимает `#15`, `vol.2`, годы, даты, римские
в контексте; используется для anti-flood в выдаче.

## Бэклог доработок

`IMPROVEMENTS.md` в корне — живой список доработок (сделанные `[x]` +
открытые `[ ]`, с привязкой к файлам, по приоритету). **Держать в актуальном
состоянии при каждом изменении** (как и этот файл).

## Текущее состояние (5 июня 2026)

Активная ветка: `dev`.

**Инфраструктура:** dev-БД и CI — **Supabase / pgvector pg16** (session
pooler, IPv4). `DATABASE_URL` в `.env`. `pool_pre_ping=True` +
`pool_recycle=1500` (Supabase pooler режет idle ~5 мин). SQLite-job
из CI удалён — на проде/деве везде Postgres, дублирование себя не оправдало.

**Свежие фичи**:

1. **NL-поиск событий** (`GET /events/nl-search`): LLM-extract фильтров
   (`SearchFilters`: даты/город/тип/формат/темы), LRU-кэш, канонизация,
   relax-fallback при 0 → 1 ближайшее событие + CTA «🎯 К рекомендациям».
   В боте sticky waiting (60 мин) — не нужно жать «🔍 Поиск» перед каждым
   запросом.
2. **Единая «📖 Подробнее»** в карточке: одна кнопка вместо «❓ Почему /
   📖 Подробнее». Новый сервис `event_explain_service.py` пишет
   человеческое описание (без скоров/метрик), кэш TTL 6 ч.
3. **Ссылки на источник везде**: `event_url_line` в bot/utils. Прошито в
   recommendations, search, profile/saved, trending, similar, deep-link.
4. **Фикс «00 UTC» в датах**: `format_event_date` смотрит на raw `start_at`
   до конвертации зоны — если часы нулевые, показываем только дату.
5. **Фильтр прошедших событий**: `app/db/event_filters.py::upcoming_only`,
   применён везде в выдаче. БД ничего не удаляет.
6. **Copilot скрыт в боте**: роутер не подключается в `app/bot/main.py`,
   упоминания убраны из меню и тура (UX признан кривым на демо).
7. **CI: только Postgres**. `test-sqlite` job удалён, полный suite на
   `pgvector/pgvector:pg16`.
8. **LLM-цепочка**: Gemini (REST-транспорт, автопроба модели) → Groq 70b →
   Groq 8b. Circuit-breaker + per-provider cooldown. `POST /admin/llm/reprobe`.
9. **Read-only `/recommendations`** + TTL-кэш + курсор ленты в БД.
10. **pgvector-dedup** + adaptive batch + series anti-flood +
    усиленный фильтр не-IT/не-событий в системном промпте нормализатора.
11. **Security/ops**: `X-API-Key` shared-secret + request-middleware с
    timing'ами + 4xx WARNING без traceback + fail-fast config validation.
12. **LLM-устойчивость**: prompt-injection sanitize + memory hard-cap (500) +
    scheduler-backfill для embedding'ов.
13. **DB**: `users.telegram_id` → BIGINT; миграции `c3d4`, `d4e5`, `e5f6`,
    `f6a7` (feed_cursor, recommendation_cache, series_slug, telegram_id BIGINT).
14. **Данные**: строгая enum-валидация полей нормализатора + idempotent
    re-ingestion + локализация дат в боте + 19-городный seed и CITY_ALIASES.
15. **Отчёт**: проведён научный аудит, сокращены 5 разделов (~3 стр), Глава 4
    наполнена цифрами через `eval_offline_synthetic.py` (Таблица 4.2) и
    `llm_judge_synthetic.py` (Таблица 4.3).
