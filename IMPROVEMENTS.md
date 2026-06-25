# EventMind — бэклог технических доработок

Живой список улучшений. Сделанные — `[x]` для исторического трека (что
сделано, как, какой ценой). Открытые — `[ ]`, разделены на «реалистично
сделать в ближайшем спринте» (🟠🟡🟢) и «крупные направления под
магистерскую» (🚀).

Состояние на **5 июня 2026**, ветка `dev`. 369 тестов, ruff = 0.

---

## ✅ Сделано

### Фикс «лента показывает 1 событие» (2026-06-25)

- [x] **Рассинхрон `embedding_vec`.** `pgvector_top_k_events` отбирает
  кандидатов `WHERE embedding_vec IS NOT NULL`, но колонка была заполнена
  лишь у 3/113 событий → весь пул = 3, после `upcoming_only` оставалось 1.
  Корень: `embedding_vec` НЕ замаплена в ORM-модели `Event` (только JSON
  `embedding`), поэтому `_write_embedding`'s `hasattr(obj, "embedding_vec")`
  всегда False — вектор молча не писался при ingestion. А backfill-джоб
  и `ensure_event_embeddings` искали пробелы только по JSON-колонке.
  - **Данные:** backfill `UPDATE events SET embedding_vec = CAST(embedding
    AS vector)` для 110 событий (= `python -m scripts.backfill_pgvector`).
  - **Код:** `_write_embedding(obj, vec, db=...)` теперь пишет
    `embedding_vec` прямым raw-UPDATE по `id` на PG (колонка не в ORM);
    `ensure_event_embeddings` и ingestion прокидывают `db`.
  - **Код:** `backfill_event_embeddings_once` после JSON-backfill зовёт
    `_backfill_table` — лечит рассинхрон vec даже без новых событий.

### Ревью руководителя 2026-06-04 → правки (2026-06-05)

- [x] **Copilot скрыт в боте.** Роутер `app/bot/handlers/copilot.py` не
  подключается в `app/bot/main.py`; упоминания убраны из меню, /help,
  тура и кнопки «Спросить Copilot» в поиске. API-эндпоинты и таблица
  `copilot_sessions` остались — UX доработаем отдельно.
- [x] **Ссылки на источник во всех местах рендера.** Хелпер
  `app/bot/utils.py::event_url_line(event)` — HTML-якорь с экранированным
  href. Прошито в recommendations, search, profile/saved, trending,
  similar, deep-link.
- [x] **Единая кнопка «📖 Подробнее» вместо «Почему / Подробнее».**
  Новый эндпоинт `GET /events/{id}/explain` + сервис
  `event_explain_service.py`: LLM пишет человеческий пересказ без скоров
  и метрик, in-memory кэш TTL 6 ч. `recommendation_keyboard` отдаёт
  одну кнопку, callback `explain:{event_id}`.
- [x] **Фикс «00 UTC» в датах.** `format_event_date` теперь смотрит на
  raw `start_at` ДО `astimezone(MSK)` — если часы/минуты нулевые, время
  не показываем (раньше «1 июня 2026, 03:00 Moscow» при полночи UTC от
  отсутствующих часов в источнике). Голая ISO-строка тоже переводится в
  «16 июня 2026».
- [x] **Кнопка «Пропустить тур» не исчезала.** В `cb_start_setup` удаляем
  сообщение тура перед стартом настройки тем — кнопка пропускается
  вместе с сообщением.
- [x] **Поиск по дате/городу/типу/формату на естественном языке (#6).**
  Новый сервис `app/api/services/nl_search_service.py`:
  `with_structured_output` → схема `SearchFilters` (`date_from`, `date_to`,
  `city`, `event_type`, `format`, `topics`, `free_text`). LRU-кэш по
  нормализованному запросу. Канонизация city/event_type/format через
  `canonicalize_city` и closed-домены нормализатора. До 5 строгих
  совпадений; при 0 — relax-fallback (free_text → topics → format →
  event_type → city → date), показываем 1 ближайшее + CTA в рекомендации.
  Эндпоинт `GET /events/nl-search`. Прошёл два регрес-бага: 422 из-за
  порядка маршрутов (был ниже `/{event_id}`) и NULL-сейф у даты, из-за
  которого статьи без `start_at` пролезали под любой временной запрос.
- [x] **Фильтр прошедших событий.** Общий хелпер
  `app/db/event_filters.py::upcoming_only(grace_hours=6)`, прошит в
  recommendations, search (keyword + semantic + similar), retrieval
  (copilot). БД ничего не удаляет — interactions/история продолжают
  учить bayesian/bandit. NULL-сейф (события без даты остаются).
- [x] **«Избранное» из поиска (#8).** Под каждым результатом NL-поиска
  кнопка ⭐ → callback `search_save:{id}` → реюзает `Interaction(action='save')`.
- [x] **Sticky waiting в поиске.** TTL 5 мин → 60 мин, после первого
  запроса state НЕ сбрасывается — можно писать запросы один за другим.
  `_touch_waiting` продлевает TTL на каждый успешный поиск. Под
  последним результатом — inline-кнопка «🔍 Новый поиск» как явный якорь.
- [x] **CI без SQLite-job.** Оставлен только `test` на pgvector/pg16,
  прогоняется полный suite (раньше — только критичные тесты). На
  Supabase везде, дублирование себя не оправдало.

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

### Offline-эвал и научная часть отчёта

- [x] **Синтетический бенчмарк для leave-one-out.** `scripts/eval_offline_synthetic.py`:
  изолированная in-memory SQLite, фиксированный `seed=42`, 20 пользователей ×
  80 событий × 8 тем. У каждого user'а доминирующая тема (вес 10) + 0-1 побочная;
  префилл event-embedding'ов одним батчем. Закрывает дыру: продакшн-БД ещё не
  накопила ≥3 positive-сигнала на пользователя, требуемых для leave-one-out на
  реальных данных. Результаты — Таблица 4.2 отчёта.
- [x] **LLM-судья на синтетике.** `scripts/llm_judge_synthetic.py`:
  переиспользует `build_synthetic_db()`, top-K считает напрямую через
  `score_event_for_user` / `hybrid_score` / `posterior_mean` (без полного
  `get_recommendations_for_user`-пайплайна). Прямые `SystemMessage`/`HumanMessage`
  (без `ChatPromptTemplate` — JSON-промпт ломал placeholder-синтаксис). Результаты
  — Таблица 4.3 отчёта.
- [x] **Цифры в Главе 4 отчёта.** Recall@10 / nDCG@10 / relevance / diversity
  для rule / hybrid / bayesian вставлены как таблицы 4.2 и 4.3. §715 объясняет
  trade-off «релевантность ↔ разнообразие», компенсируемый MMR-rerank в основном
  конвейере (отсылка на 3.5.6).
- [x] **Научный аудит отчёта.** Закрыты критические замечания К-1 (170 тестов
  → 285), К-2 (LightGCN: `gnn_enabled=False`), К-4 (LinUCB не «вероятностная
  адаптация»). Удалены вода и повторы в Главе 1 (§134, §248, 7 буллет-списков
  в 1.3.x), сжаты 1.5, 3.5.7. Научная новизна (§157) переформулирована в
  3 чётких пункта; практическая значимость (§163) — конкретно про шесть
  источников и двухуровневое объяснение. Полный текст рецензии и бэкап
  отчёта сохранены.

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
- [ ] **Расширить бенчмарк до N≥30 пользователей.** Текущий синтетический
  LLM-судья гонится на 6 пользователях из-за rate-limit Gemini free-tier
  (15 RPM на gemini-3.1-flash-lite). Нужно: либо несколько API-ключей с
  ротацией, либо пауза 4 сек между запросами + увеличение `max_users`
  до 30-50 для усреднения. Это уменьшит дисперсию и сделает таблицу 4.3
  более статистически убедительной для академической части.
- [ ] **Доверительные интервалы по метрикам.** Сейчас в таблицах 4.2/4.3
  только средние. Добавить 95% confidence interval (bootstrap по
  пользователям, 1000 итераций) — стандарт академического жанра.

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
