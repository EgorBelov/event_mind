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

## 🔴 Корректность / надёжность

- [ ] **Счётчик попыток у raw_events.** Добавить `retry_count` (миграция),
  чтобы `retry-failed` не гонял вечно безнадёжные события и можно было
  отсекать «битые» после N попыток. `app/db/models/raw_event.py`.
- [ ] **Нормализация даты в ISO + тип `DateTime`.** Сейчас `events.date` —
  строка, у реальных событий часто `unknown`/пусто → freshness падает в
  дефолт 0.5, сортировка по дате невозможна. Обязать нормализатор возвращать
  ISO-дату или null; в модели — `DateTime`. `app/db/models/event.py`,
  `app/agents/event_normalization/`.

## 🟠 Масштабирование / производительность

- [ ] **Кандидатный отбор через pgvector в `/recommendations`.** Сейчас
  `db.query(Event).all()` + hybrid на каждое событие — O(каталог) на запрос.
  Использовать `retrieval.pgvector_top_k_events` для предотбора 200–500
  кандидатов, затем hybrid только по ним.
  `app/api/services/recommendation_service.py`.
- [ ] **N+1 в скоринге.** `_get_event_topic_codes(event)` лениво грузит
  relationship → отдельный SELECT на событие (особенно больно на PG по сети,
  ~360 ms RTT). Eager-load через `joinedload(Event.event_topics)`.
- [ ] **Состояние бота в памяти.** `user_recommendation_index` —
  модульный dict в `app/bot/handlers/recommendations.py`: теряется при
  рестарте и ломается при >1 воркере. Перенести в БД/Redis (как
  copilot-сессии).

## 🟡 Безопасность / ops

- [ ] **Авторизация API.** Все эндпоинты открыты, пользователь — `telegram_id`
  в пути. На деплое любой может читать/менять чужой профиль. Минимум —
  shared-secret между ботом и API (заголовок). `app/api/`.
- [ ] **CI.** Нет автозапуска тестов. Добавить GitHub Actions:
  `pytest -q` + `ruff check .` на push/PR.
- [ ] **ruff в `app/`.** Заявлено «0 ошибок», реально ~10 (72 по репо).
  `ruff check --fix .` уберёт ~43 автоматом, остальное — точечно.
- [ ] **Pydantic `.dict()` → `model_dump()`.** Deprecation-warning'и в тестах;
  сломается на Pydantic v3.
- [ ] **Логи вместо `print()` в scheduler.** `app/scheduler/digest.py` весь на
  `print(...)` — на проде не попадёт в структурированные логи.
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
