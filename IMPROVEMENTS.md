# EventMind — бэклог технических доработок

Список улучшений, выявленных при ревью кода и наблюдении за рантаймом
(прогон на Supabase, 29.05.2026). Сгруппирован по приоритету. Каждый пункт —
с привязкой к файлу. Пункты помечаются `[ ]` / `[x]` по мере выполнения.

## ✅ Сделано

- [x] **#1 `embedding_vec` при ingestion.** `_normalize_single` теперь пишет
  вектор через `_write_embedding` (и JSON, и pgvector-колонку) —
  `app/api/services/ingestion_service.py`. Раньше `embedding_vec` оставался
  пустым и требовал ручного `backfill_pgvector` после каждого парсинга.
- [x] **#2 Retry упавших нормализаций.** Добавлены `retry_failed_events()` и
  `POST /ingestion/retry-failed` — переобрабатывают события `status='failed'`
  (актуально после сброса дневного лимита Groq). `normalize_raw_events`
  параметризован по статусам; stale `error` чистится при успехе.
- [x] **Общий парсинг.** `POST /ingestion/load-all?limit=N` — все источники
  по очереди, каждый изолирован try/except + rollback, агрегированные totals.
- [x] **Hot-path `/recommendations`.** Тяжёлый `explain_event_detailed`
  строится только для возвращаемого top-N (+ параметр `limit`), а не для
  всего каталога.
- [x] **`pool_pre_ping=True`** в `app/db/session.py` — для управляемого PG/пулера.
- [x] **Зависимости.** `ruff`, `python-docx` добавлены в `requirements.txt`.
- [x] **Батчинг нормализации + early-stop на rate-limit.**
  `event_normalizer_agent_batch` нормализует пачку событий одним LLM-вызовом
  (кратно меньше токенов); `_normalize_by_ids` ходит пачками по 5, на
  rate-limit (429/TPD) останавливается рано и оставляет необработанные в
  статусе `raw` (а не выжигает в `failed`) — их доберёт `/normalize` после
  сброса квоты. `app/agents/event_normalization/agent.py`,
  `app/api/services/ingestion_service.py`. Backoff в общий `llm.invoke`
  СОЗНАТЕЛЬНО не добавлен — это бы подвешивало user-facing запросы
  (copilot/why); SDK ChatGroq уже ретраит per-minute лимиты через max_retries.
- [x] **Кандидатный отбор через pgvector + N+1 в `/recommendations`.** Сначала
  считается user-embedding, затем `pgvector_top_k_events` отбирает top-300
  кандидатов (на PG; на SQLite fallback на весь каталог), hybrid считается
  только по ним. `joinedload(Event.event_topics)` убирает N+1 на темах.
  `app/api/services/recommendation_service.py`.
- [x] **Логи вместо `print()` в scheduler.** `app/scheduler/digest.py` переведён
  на `logging` (info/warning по уровню).
- [x] **ruff = 0 ошибок по репо.** `ruff check --fix` + unsafe-fix (UP038/SIM105),
  перенос logger в `copilot.py`, per-file-ignores E402 для tests/alembic/scripts
  в `pyproject.toml`.
- [x] **CI.** `.github/workflows/ci.yml` — `ruff check .` + `pytest -q` на
  push/PR в main/dev (Python 3.12, SQLite-БД по умолчанию).
- [x] **Тесты герметичны без GROQ_API_KEY.** `_GroqWithFallback` строит
  `ChatGroq` лениво (не в `__init__`) — импорт модулей больше не требует
  ключа (CI падал на этом). `app/agents/recommendation/llm.py` +
  фиктивный `GROQ_API_KEY` в CI как подстраховка.
- [x] **`retry_count` у raw_events.** Колонка + `_mark_failed` инкрементит
  счётчик; `normalize_raw_events`/`retry-failed` пропускают события, превысившие
  `MAX_NORMALIZE_RETRIES` (3). `app/db/models/raw_event.py`,
  `app/api/services/ingestion_service.py`, миграция `b2c3d4e5f6a7`.
- [x] **Дата начала: `events.start_at` (DateTime).** Нормализатор отдаёт ISO-дату,
  она парсится в `start_at` при ingestion; `_component_freshness` использует
  `start_at` (fallback на парсинг строки). Строковая `date` остаётся для UI.
  Аддитивно — без смены типа существующей колонки.

## 🟠 Масштабирование / производительность

- [ ] **Состояние бота в памяти.** `user_recommendation_index` —
  модульный dict в `app/bot/handlers/recommendations.py`: теряется при
  рестарте и ломается при >1 воркере. Перенести в БД/Redis (как
  copilot-сессии).

## 🟡 Безопасность / ops

- [ ] **Авторизация API.** Все эндпоинты открыты, пользователь — `telegram_id`
  в пути. На деплое любой может читать/менять чужой профиль. Минимум —
  shared-secret между ботом и API (заголовок). `app/api/`.
- [ ] **Pydantic `.dict()` → `model_dump()`.** Deprecation-warning'и в тестах;
  сломается на Pydantic v3.
- [ ] **Тесты Postgres-путей.** Фикстуры на SQLite; ветки
  `pgvector_top_k_events`, `<=>`-запросы, `has_pgvector()` не покрыты, а прод
  теперь PG (Supabase). Добавить хотя бы smoke против PG.

## 🟢 Данные / продукт / документация

- [ ] **Качество фильтра не-IT на fallback-модели.** На 8b (когда 70b-квота
  кончается) фильтр слабее — проскакивают не-IT события. Усилить промпт/порог.
- [ ] **Синхронизировать docs с реализацией.** В `docs/*.docx` и местами в
  README остаётся устаревшее: старый список copilot-tools
  (`get_recent_interactions`, `get_event_details`), claim «ruff без ошибок»,
  «10 миграций» vs фактическое число. Перегенерировать `regenerate_docs.py`.
