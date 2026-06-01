# EventMind — бэклог технических доработок

Живой список улучшений. Сделанные — `[x]` для исторического трека (что
сделано, как, какой ценой). Открытые — `[ ]`, разделены на «реалистично
сделать в ближайшем спринте» (🟠🟡🟢) и «крупные направления под
магистерскую» (🚀).

Состояние на **1 июня 2026**, ветка `dev`. 261 тест, ruff = 0.

---

## ✅ Сделано

### Корректность и производительность hot-path

- [x] **Read-only `GET /recommendations`.** Раньше read-path внутри вызывал
  `refresh_user_embedding` + `ensure_event_embeddings` с `db.commit()` —
  каждый GET был writer (под Supabase = round-trip на каждое открытие
  ленты). Прогрев `user.embedding` перенесён в пишущие пути
  (`create_or_update_user`, `analyze_bio`, `create_interaction` — все ветки,
  включая toggle off). Прогрев `event.embedding` — при ingestion и в
  scheduler-джобах `backfill_event_embeddings` (раз/час) и
  `backfill_user_embeddings` (раз/4ч).
- [x] **TTL-кэш рекомендаций.** Таблица `recommendation_cache` (миграция
  `d4e5f6a7b8c9`): `items_json + expires_at`. Hit пропускает весь скоринг.
  TTL по умолчанию 15 мин (`recommendation_cache_ttl_minutes`).
  Инвалидация на feedback / register / edit / analyze-bio.
- [x] **Кандидатный отбор через pgvector.** `pgvector_top_k_events(top=300)`
  на PG / fallback на полный каталог на SQLite. `joinedload(event_topics)`
  убирает N+1 на темах. Тяжёлый `explain_event_detailed` строится только
  для возвращаемого top-N.
- [x] **pgvector-dedup.** `find_semantic_duplicate` на PG делает один
  `<=>`-запрос с `LIMIT 1` и порогом по distance вместо Python-цикла по
  500 кандидатам. При сбое pgvector возвращает `ok=False` — vызывающая
  сторона прогоняет in-memory путь как страховку.
- [x] **Адаптивный batch-размер нормализации.** `_adaptive_batch_size`
  считает batch_size из средней длины raw_description (target ~6000
  символов, в [2..10]).

### Данные и ingestion

- [x] **`embedding_vec` при ingestion.** `_normalize_single` пишет вектор
  через `_write_embedding` (JSON + pgvector-колонку). Раньше требовался
  ручной `backfill_pgvector` после каждого парсинга.
- [x] **Retry-failed.** `POST /ingestion/retry-failed` + `retry_count` в
  raw_events + `MAX_NORMALIZE_RETRIES=3`. Безнадёжные не подбираются.
- [x] **Общий парсинг.** `POST /ingestion/load-all?limit=N` — все источники
  по очереди, каждый изолирован try/except + rollback, агрегированные totals.
- [x] **Батчинг + early-stop.** `event_normalizer_agent_batch` нормализует
  пачку одним LLM-вызовом; на rate-limit (429/TPD) обработка прерывается
  и оставляет необработанные в `raw` (не `failed`).
- [x] **`events.start_at` (DateTime).** Нормализатор отдаёт ISO-дату,
  freshness считается по `start_at`. Миграция `b2c3d4e5f6a7`.
- [x] **Строгая валидация ISO-даты от LLM.** `_validate_iso_date`: regex
  + календарная проверка через `datetime.date()` + год в [2020..2035].
  Мусор от LLM в `events.date` больше не попадает. Defence-in-depth: те
  же чек дублируется в `_persist_normalized`.
- [x] **events.series_slug + анти-флуд.** `compute_series_slug(title, city)`
  снимает `#15`, `vol.2`, годы, даты, римские в контексте. При ingestion
  проставляется автоматически; `/recommendations` оставляет один выпуск
  серии — ближайший к now по `start_at`. Backfill старых событий —
  `scripts/backfill_series_slug.py`.
- [x] **Усиление фильтра не-IT.** В `_SYSTEM_PROMPT` агента нормализации —
  явные категории НЕ-IT (PR/HR/маркетинг/коучинг/...) и few-shot решения.

### LLM-надёжность

- [x] **LLM-цепочка с автопробой Gemini.** `_LLMChain` в
  `app/agents/recommendation/llm.py`: Gemini (REST-транспорт, обходит
  gRPC-DNS на macOS) → Groq 70b → Groq 8b. `_probe_gemini_model` делает
  HTTP-POST по списку кандидатов и берёт первую с 200; кэшируется до
  перезапуска или `POST /admin/llm/reprobe`.
- [x] **Circuit-breaker.** 5 подряд фейлов цепочки → cooldown 120 с;
  `CircuitOpenError` без httpx-таймаута.
- [x] **Per-provider cooldown.** 2 подряд фейла на одном звене → skip
  на 10 мин. Раньше каждый запрос платил 30+ секунд на 429 → fallback.
- [x] **Compaction Copilot-истории.** При >`_MAX_HISTORY*2` сообщений
  середина сжимается одним system-summary через LLM; голова и хвост
  сохраняются. При сбое LLM — деградация в sliding window.
- [x] **Prompt-injection sanitize.** `app/core/prompt_safety.py`:
  `sanitize_user_text` (control/zero-width/BIDI чистка, обрезка
  длины), `wrap_user_text` (обёртка `<user_input>` + обезоруживание
  поддельных тегов), `has_injection_hints` (логирование).
- [x] **Тесты герметичны без ключей.** ChatGroq/ChatGoogle строятся
  лениво — импорт модулей не требует API-ключей (CI на этом падал).

### Security / ops

- [x] **API shared-secret auth.** `ApiKeyMiddleware`: `X-API-Key` через
  `hmac.compare_digest`. Whitelist `/health`/`/docs`/`/openapi.json`.
  Бот и scheduler шлют заголовок во ВСЕ запросы.
- [x] **Request-log middleware.** Одна строка на запрос с тайминговым
  суффиксом и `X-Request-ID`. 5xx → ERROR, 4xx → WARNING, прочее → INFO.
- [x] **HTTPException 4xx → WARNING без traceback.** Раньше стандартный
  FastAPI access-log писал ERROR на нормальные 404. Новый
  exception_handler логирует кратко и возвращает `{detail, request_id}`.
- [x] **Fail-fast валидация конфига.** `validate_or_exit(ctx)` для api/
  bot/scheduler-контекстов. Код выхода 78 (EX_CONFIG). Пустой
  `API_SHARED_SECRET` даёт WARNING.
- [x] **Memory hard-cap.** `USER_MEMORY_HARD_CAP=500`. При write
  превышение сразу триммится по salience ASC + id ASC — без LLM.
- [x] **Supabase resiliency.** `pool_pre_ping=True` + `pool_recycle=1500`.
  Safe-commit в `_normalize_by_ids` — rollback при сбое pooler'а, чтобы
  следующий источник в `load-all` не унаследовал PendingRollbackError.

### Состояние и схема

- [x] **Курсор ленты в БД.** `users.feed_cursor` (миграция `c3d4e5f6a7b8`)
  + endpoints `/recommendations/{tid}/cursor[/reset|/advance]`. В боте
  module-dict `user_recommendation_index` удалён.
- [x] **`users.telegram_id` → BigInteger.** Telegram канал/группа ID
  выходят за 2³¹. Миграция `f6a7b8c9d0e1`: `ALTER COLUMN TYPE BIGINT` на
  PG, на SQLite no-op.

### Тесты и CI

- [x] **Покрытие hot-path.** `tests/test_get_recommendations.py`: list+
  limit, series collapse, cache populate, cache hit пропускает scoring
  (spy), invalidate + recompute, 404.
- [x] **CI с Postgres+pgvector.** Job `test-postgres` в
  `.github/workflows/ci.yml`: services `pgvector/pgvector:pg16`,
  `CREATE EXTENSION vector`, `alembic upgrade head`, прогон критичных
  тестов на реальном PG.
- [x] **ruff = 0** по репо; per-file-ignores E402 для tests/alembic/scripts.
- [x] **Кросс-платформенный README/CLAUDE.md** (macOS/Linux + Windows).

### Cleanup и рефакторинг

- [x] **`utcnow_naive` в `app/core/utils.py`.** Раньше идентичный helper
  был продублирован в 7 файлах (recommendation_service, memory, copilot,
  hybrid, dedup, bayesian, analytics). Все импортируют из одного места.
- [x] **Удалён dead код.** `_user_profile_snapshot` в ai_recommendation_service.py
  возвращал `{}` и нигде не использовался.
- [x] **Логирование вместо `print`.** В scheduler/digest.py всё на `logging`.
- [x] **Pydantic deprecations.** В нашем коде `.dict()` нет (всё на
  `model_validate`/`model_dump`); шум от langchain заглушён в
  `pyproject.toml::filterwarnings`.

---

## 🟠 Реалистичный задел (можно сделать спринтом)

### Наблюдаемость
- [ ] **Метрики `/recommendations`, `/ingestion`, LLM-цепочки.** Сейчас
  тайминги есть только в request-log на уровне всего запроса. Хорошо бы
  явные счётчики: `recommendation_cache_hits`, `llm_provider_calls{name}`,
  `ingest_normalized{source}`. Минимум — JSON-логи и Prometheus-экспортер
  через `prometheus-fastapi-instrumentator`.
- [ ] **Healthcheck на реальный invoke.** Сейчас `/health` проверяет
  только конфиг LLM-обёртки. Можно периодически (раз/мин) делать
  «warmup ping» Gemini с минимальным token-output, кэшировать результат
  с TTL, и в `/health` отдавать живой статус.

### Качество и надёжность LLM
- [ ] **Параллельная Gemini-probe.** Сейчас `_probe_gemini_model` идёт
  последовательно: на 6 моделей по 8 с timeout — теоретический worst-case
  48 с. `asyncio.gather` + первый 200 → 5-8 с в худшем.
- [ ] **Multi-key Gemini rotation.** Второй Google-аккаунт = свои 1500 RPD
  на 1.5-flash. `_LLMChain` уже умеет per-provider, расширить до
  per-(provider, key). +30 строк.
- [ ] **Honor `retry-after` от Groq/Gemini.** SDK ChatGroq уже ретраит, но
  при «не выйдет до 30 мин» лучше пропустить звено явно вместо ожидания.
- [ ] **`/admin/llm/reprobe` под shared-secret.** Сейчас открытый
  (whitelist по умолчанию пуст — middleware прикроет, но точно стоит
  пометить как admin-only).

### Данные
- [x] **Строгая валидация остальных LLM-полей.** В
  `agent.py::_normalize_enum_field`: closed-domain для
  `format`/`event_type`/`seniority` (свалится в дефолт при значении
  вне домена), open-domain для `city`/`level` (slug, но фильтруем
  malformed: длиннее 32 / пробелы / слеши). +6 тестов в
  `test_enum_validation.py`.
- [x] **Idempotent ingestion.** `_merge_existing_event` в
  `ingestion_service.py`: при повторном попадании на тот же event
  обновляются ТОЛЬКО поля, которые стали информативнее (был
  `format=unknown` → стал `online`; пустой `source_url` → URL пришёл;
  `start_at=None` → пришла валидная дата; описание стало длиннее на 20%+).
  Embedding/series_slug не пересчитываются — title тот же. +9 тестов
  в `test_ingestion_idempotent.py`.

### Магистерская-track (короткие)
- [x] **Глубокий синк прозы docs/*.docx.** В `regenerate_docs.py`
  обновлены ключевые блоки: 3.1 «Свежий пакет правок» переписан под
  июнь 2026 (read-only /recommendations, TTL-кэш, multi-provider LLM
  chain, security middleware, prompt safety, series anti-flood,
  enum-валидация, idempotent ingestion, BIGINT, hard-cap, локализация).
  3.3 — описание /health и LLM-цепочки. 3.6 — обновлено число тестов
  и описание CI с PG-job. Глоссарий — Gemini-цепочка вместо
  одношот-Groq. `.docx` перегенерированы.

---

## 🟡 Безопасность и operations (отложенное)

- [ ] **Rate-limiting на API.** Нет защиты от breakdown'а через спам в
  `/copilot` (дорогой LLM-вызов). Минимум — `slowapi` per-`telegram_id`,
  N req/min.
- [ ] **Audit-log пользовательских действий.** Кто что лайкнул, когда,
  с какого rid — для отладки рекомендаций и для академического разбора
  в магистерской.
- [ ] **Secrets через секрет-менеджер.** Сейчас всё в `.env`. На проде
  нужны как минимум разделение по средам (dev/staging/prod) и rotation
  без рестарта.
- [ ] **Backup стратегия Supabase.** Supabase делает daily-снэпшоты, но
  скрипт восстановления и проверка восстановимости — отдельно.

---

## 🟢 Данные / продукт

- [ ] **Распознавание организаторов.** Сейчас в нормализаторе нет
  понятия «кто проводит». Из URL/описания часто можно вытащить →
  получится свойство `events.organizer_slug` + сигнал репутации.
- [ ] **Качество событий по внешним сигналам.** Репутация спикеров,
  оценки прошлых мероприятий организатора, активность в чате —
  дополнительные входы к LLM-quality_score.
- [x] **Локализованные форматы дат.** В API теперь возвращается
  `start_at` (ISO) рядом со строковой `date`. В боте
  `app/bot/utils.py::format_event_date` парсит `start_at`,
  конвертирует в `Europe/Moscow` (`zoneinfo`) и форматирует как
  «1 июня 2026, 22:00 Moscow». Fallback на строку `date`, потом на
  «—». +5 тестов в `test_date_localization.py`.

---

## 🚀 Крупные направления (магистерская)

Это не «фиксы», а исследовательские главы.

- [ ] **Learning-to-rank.** Веса 9 компонент сейчас захардкожены в
  `config.py`. Обучать их (logistic / LambdaMART / xgboost ranker) на
  накопленном feedback'е. У нас уже есть `eval_offline.py` (precision@k,
  nDCG); добавить training-loop и сравнение «hand-tuned vs learned».
  Магистерская: «hybrid recsys с обучаемыми весами компонент».
- [ ] **Cross-encoder reranker.** Поверх top-N от hybrid — bge-reranker
  или mE5-base для финального переранжирования. Заметный +precision@k
  на неоднозначных запросах. Цена — latency: 10-20 ms на event.
- [ ] **Социально-коллаборативный слой и GNN.** GNN сейчас выключен из-за
  разреженности графа. С ростом пользователей граф «user-like-event»
  плотнеет → можно реактивировать LightGCN/PinSAGE и сравнить с cosine-
  baseline. «N человек с похожими интересами идут» как UX-фича.
- [ ] **Активное обучение для cold-start.** Вместо пассивного `/bio` —
  2-3 точечных вопроса (Thompson sampling по темам в `user_topic_stats`),
  чтобы быстро сузить распределение.
- [ ] **Гео-осведомлённость.** Для offline-событий — расстояние/время в
  пути от города пользователя как сигнал; «события рядом в эти выходные».
- [ ] **Мультимодальность.** Парсинг афиш/постеров через CLIP/Florence-2,
  обогащение события из изображения. Для источников с бедным текстом.
- [ ] **Календарь и умные напоминания.** Экспорт в Google Calendar / ICS,
  push «событие завтра» с учётом таймзоны.
- [ ] **Веб-дашборд админа.** Мониторинг ingestion (статусы raw_events,
  failed), каталога событий, пользователей, метрик рекомендера, кривых
  CTR — вместо curl по эндпоинтам.
- [ ] **A/B-эксперименты.** Holdout-группа + трекинг CTR/save-rate.
  Обязательно для академического обоснования «новый рекомендер лучше».
- [ ] **Выделенный векторный стор.** При сотнях тысяч событий — вынести
  вектора в Qdrant/Milvus (HNSW), отделить retrieval от основной БД.
