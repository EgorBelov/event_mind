import contextlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.api.services.event_service import _attach_event_topics
from app.db.models.event import Event
from app.db.models.raw_event import RawEvent


def load_raw_events(db: Session, file_path: str = "data/events_raw.json") -> dict:
    """Загрузить data/events_raw.json в таблицу raw_events."""
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл {file_path} не найден")

    with path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    loaded = 0
    skipped = 0

    for item in raw_data:
        title = item.get("title", "")
        existing = db.query(RawEvent).filter(RawEvent.title == title).first()
        if existing:
            skipped += 1
            continue

        raw_event = RawEvent(
            title=title,
            raw_description=item.get("raw_description", ""),
            source_url=item.get("source_url"),
            status="raw",
        )
        db.add(raw_event)
        loaded += 1

    db.commit()
    return {"loaded": loaded, "skipped": skipped}


def normalize_raw_events(
    db: Session, statuses: tuple[str, ...] = ("raw",)
) -> dict:
    """Прогнать raw-события заданных статусов через EventNormalizerAgent.

    По умолчанию обрабатываются только `raw`. Для повторной обработки
    провалившихся (например, после сброса дневного лимита Groq) передаётся
    `statuses=("failed",)` — см. retry_failed_events / endpoint /retry-failed.
    События, превысившие MAX_NORMALIZE_RETRIES попыток, пропускаются как
    безнадёжные (у `raw` retry_count=0, поэтому фильтр им не мешает).
    """
    raw_events = (
        db.query(RawEvent)
        .filter(
            RawEvent.status.in_(list(statuses)),
            RawEvent.retry_count < MAX_NORMALIZE_RETRIES,
        )
        .all()
    )
    raw_ids = [r.id for r in raw_events]
    normalized, non_it, failed = _normalize_by_ids(db, raw_ids)
    return {"normalized": normalized, "non_it": non_it, "failed": failed, "picked": len(raw_ids)}


def retry_failed_events(db: Session) -> dict:
    """Повторно прогнать события со статусом 'failed'.

    Типичный кейс: нормализация упала на rate-limit'е Groq (429). После
    восстановления квоты этот вызов добивает остаток. На успехе статус
    станет normalized/non_it, иначе останется failed с обновлённым error.
    """
    return normalize_raw_events(db, statuses=("failed",))


def load_rss_events(
    db: Session,
    limit_per_feed: int = 20,
    feed_urls: list[str] | None = None,
) -> dict:
    """Скачать события из RSS/Atom-лент, нормализовать и записать в `events`.

    Если `feed_urls` не передан, берётся `settings.rss_feeds_list`.
    """
    from app.core.config import settings
    from app.ingestion.sources.rss import fetch_rss_events

    urls = feed_urls if feed_urls is not None else settings.rss_feeds_list
    if not urls:
        return {
            "source": "rss",
            "feeds": 0,
            "fetched": 0,
            "new": 0,
            "skipped": 0,
            "normalized": 0,
            "non_it": 0,
            "failed": 0,
        }

    items = fetch_rss_events(urls, limit_per_feed=limit_per_feed)
    loaded = 0
    skipped = 0
    pending_ids: list[int] = []

    for item in items:
        title = item.get("title", "")
        existing = db.query(RawEvent).filter(RawEvent.title == title).first()
        if existing:
            skipped += 1
            if existing.status == "raw":
                pending_ids.append(existing.id)
            continue

        raw_event = RawEvent(
            title=title,
            raw_description=item.get("raw_description", ""),
            source_url=item.get("source_url"),
            status="raw",
        )
        db.add(raw_event)
        db.flush()
        pending_ids.append(raw_event.id)
        loaded += 1

    db.commit()

    normalized, non_it, failed = _normalize_by_ids(db, pending_ids)

    return {
        "source": "rss",
        "feeds": len(urls),
        "fetched": loaded + skipped,
        "new": loaded,
        "skipped": skipped,
        "normalized": normalized,
        "non_it": non_it,
        "failed": failed,
    }


def load_habr_events(db: Session, limit: int = 20) -> dict:
    """Скачать события с Habr, сложить в raw_events, нормализовать AI-агентом и записать в events."""
    from app.ingestion.sources.habr import fetch_habr_events
    items = fetch_habr_events(limit=limit)
    return _load_and_normalize(db, items, source="habr")


def load_kudago_events(db: Session, limit: int = 20) -> dict:
    """Скачать события из KudaGo (открытый JSON API) и нормализовать."""
    from app.ingestion.sources.kudago import fetch_kudago_events
    items = fetch_kudago_events(limit=limit)
    return _load_and_normalize(db, items, source="kudago")


def load_luma_events(db: Session, limit_per_calendar: int = 20) -> dict:
    """Скачать события с Lu.ma (ICS-фиды из settings.luma_calendars)."""
    from app.ingestion.sources.luma import fetch_luma_events
    items = fetch_luma_events(limit_per_calendar=limit_per_calendar)
    return _load_and_normalize(db, items, source="luma")


def load_meetup_events(db: Session, limit_per_group: int = 20) -> dict:
    """Скачать события с Meetup (требуется MEETUP_TOKEN/MEETUP_GROUPS)."""
    from app.ingestion.sources.meetup import fetch_meetup_events
    items = fetch_meetup_events(limit_per_group=limit_per_group)
    return _load_and_normalize(db, items, source="meetup")


def load_telegram_events(db: Session, limit_per_channel: int = 20) -> dict:
    """Скачать события из Telegram-каналов (требуется telethon + креды)."""
    from app.ingestion.sources.tg_channels import fetch_telegram_events
    items = fetch_telegram_events(limit_per_channel=limit_per_channel)
    return _load_and_normalize(db, items, source="telegram")


def load_timepad_events(db: Session, limit: int = 20) -> dict:
    """Скачать события из Timepad (JSON API, требуется TIMEPAD_TOKEN)."""
    from app.ingestion.sources.timepad import fetch_timepad_events
    items = fetch_timepad_events(limit=limit)
    return _load_and_normalize(db, items, source="timepad")


def load_all_events(db: Session, limit: int = 20) -> dict:
    """Прогнать ВСЕ источники ingestion по очереди и собрать сводку.

    Источники: habr, rss, kudago, luma, meetup, telegram. Каждый изолирован
    в try/except + db.rollback() при сбое — отсутствие конфигурации или падение
    одного источника не прерывает остальные (та же философия, что в hybrid-
    скоринге). Возвращает per-source результаты + агрегированные totals.

    Тяжёлая операция: на каждое новое событие идёт LLM-нормализация, так что
    при больших limit запрос может выполняться минуты.
    """
    import logging

    logger = logging.getLogger(__name__)

    # (имя, вызов) — порядок = очередь выполнения. Timepad ставим первым:
    # у него самые чистые данные, идёт быстрее всего и заполняет «золотой»
    # пул events до того, как пойдёт более шумный поток с RSS/Habr.
    sources: list[tuple[str, callable]] = [
        ("timepad", lambda: load_timepad_events(db, limit=limit)),
        ("habr", lambda: load_habr_events(db, limit=limit)),
        ("rss", lambda: load_rss_events(db, limit_per_feed=limit)),
        ("kudago", lambda: load_kudago_events(db, limit=limit)),
        ("luma", lambda: load_luma_events(db, limit_per_calendar=limit)),
        ("meetup", lambda: load_meetup_events(db, limit_per_group=limit)),
        ("telegram", lambda: load_telegram_events(db, limit_per_channel=limit)),
    ]

    per_source: list[dict] = []
    totals = {"new": 0, "skipped": 0, "normalized": 0, "non_it": 0, "failed": 0}

    for name, fn in sources:
        try:
            res = fn()
            res.setdefault("source", name)
            res["ok"] = True
        except Exception as e:
            logger.exception("ingestion source '%s' failed", name)
            # Сессия могла «отравиться» на середине транзакции — откатываем,
            # иначе следующий источник упадёт с PendingRollbackError.
            with contextlib.suppress(Exception):
                db.rollback()
            res = {"source": name, "ok": False, "error": str(e)[:300]}
        per_source.append(res)
        for k in totals:
            totals[k] += int(res.get(k, 0) or 0)

    return {"sources": per_source, "totals": totals}


def _load_and_normalize(db: Session, items: list[dict], source: str) -> dict:
    """Универсальная обёртка: items → raw_events → normalize → events."""
    loaded = 0
    skipped = 0
    pending_ids: list[int] = []

    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        existing = db.query(RawEvent).filter(RawEvent.title == title).first()
        if existing:
            skipped += 1
            if existing.status == "raw":
                pending_ids.append(existing.id)
            continue
        raw_event = RawEvent(
            title=title,
            raw_description=item.get("raw_description", ""),
            source_url=item.get("source_url"),
            status="raw",
        )
        db.add(raw_event)
        db.flush()
        pending_ids.append(raw_event.id)
        loaded += 1

    db.commit()
    normalized, non_it, failed = _normalize_by_ids(db, pending_ids)
    return {
        "source": source,
        "fetched": loaded + skipped,
        "new": loaded,
        "skipped": skipped,
        "normalized": normalized,
        "non_it": non_it,
        "failed": failed,
    }


def _is_rate_limit_error(exc: Exception) -> bool:
    """Похоже ли исключение на rate-limit/квоту Groq (429, TPD, too many requests)."""
    s = str(exc).lower()
    return (
        "rate limit" in s
        or "rate_limit" in s
        or "429" in s
        or "too many requests" in s
        or "tokens per day" in s
        or "quota" in s
    )


# Сколько раз пытаемся нормализовать «упавшее» событие, прежде чем считать
# его безнадёжным (retry-failed его больше не подбирает).
MAX_NORMALIZE_RETRIES = 3


def _mark_failed(raw: RawEvent, exc: Exception) -> None:
    """Пометить raw-событие как failed + инкрементировать счётчик попыток."""
    raw.status = "failed"
    raw.error = str(exc)
    raw.retry_count = (raw.retry_count or 0) + 1


def _persist_normalized(db: Session, raw: RawEvent, item: dict) -> str:
    """Сохранить нормализованный dict как Event (или пометить non_it/дубль).

    Возвращает 'normalized' | 'non_it'. Бросает исключение при ошибке БД —
    вызывающая сторона решает, помечать ли raw как failed. Общий код для
    одиночной и батч-нормализации.
    """
    topics = item.get("topics", [])

    if not topics:
        raw.status = "non_it"
        raw.error = None
        return "non_it"

    existing = db.query(Event).filter(Event.title == item["title"]).first()

    # Семантическая дедупликация: если по title не нашли, проверим
    # по эмбеддингу. Это ловит парафразы и кросс-источниковые дубли.
    if not existing:
        try:
            from app.recommender.dedup import find_semantic_duplicate
            candidate_text = f"{item['title']} {item['description']}"
            existing = find_semantic_duplicate(db, candidate_text)
        except Exception:
            existing = None

    # Boundary-валидация даты: даже если кто-то отдаст dict в обход агента,
    # мусор в events.date не попадёт. Defence in depth с _validate_iso_date
    # в самом агенте.
    from app.agents.event_normalization.agent import _validate_iso_date
    from app.recommender.hybrid import _parse_event_date
    date_str = _validate_iso_date(item.get("date", ""))
    new_source_url = item.get("source_url") or raw.source_url

    if existing:
        # Idempotent update: событие уже есть в каталоге — оно могло «переехать»
        # (новый URL, появилась дата, поменялся формат). Безопасно мержим:
        # только перезаписываем поле, если новое значение информативнее старого.
        # Не трогаем embedding/series_slug — title не менялся, переcчёт не нужен.
        _merge_existing_event(existing, item, date_str, new_source_url)
    else:
        import json as _json
        tech_stack = item.get("tech_stack", [])
        from app.recommender.series import compute_series_slug
        event = Event(
            title=item["title"],
            description=item["description"],
            format=item["format"],
            city=item["city"],
            level=item["level"],
            date=date_str,
            start_at=_parse_event_date(date_str),
            event_type=item.get("event_type"),
            target_audience=item.get("target_audience"),
            source_url=new_source_url,
            tech_stack=_json.dumps(tech_stack, ensure_ascii=False) if tech_stack else None,
            seniority=item.get("seniority"),
            quality_score=item.get("quality_score"),
            hype_score=item.get("hype_score"),
            series_slug=compute_series_slug(item.get("title"), item.get("city")),
        )
        db.add(event)
        db.flush()
        _attach_event_topics(db, event, topics)

        # Сразу считаем вектор события, чтобы путь рекомендаций не
        # досчитывал его лениво (тот самый «холодный» провал).
        # _write_embedding пишет И JSON-колонку, И pgvector-колонку
        # embedding_vec — иначе на PG быстрый <=>-индекс пустой и каждый
        # ingestion требовал бы ручного backfill_pgvector.
        # Best-effort: при сбое embedding останется None и его
        # подхватит ensure_event_embeddings при первом запросе.
        try:
            from app.recommender.embeddings import _write_embedding, build_event_embedding
            _write_embedding(event, build_event_embedding(event), db=db)
        except Exception:
            pass

    raw.status = "normalized"
    raw.error = None
    return "normalized"


def _merge_existing_event(event: Event, item: dict, new_date: str, new_url: str | None) -> None:
    """Idempotent-обновление существующего события из re-ingestion.

    Стратегия: новое значение перезаписывает старое ТОЛЬКО если оно
    информативнее. «Информативнее» означает:
    - URL: текущий пустой, новый — нет;
    - date/start_at: текущая пустая, новая валидная (или start_at новее);
    - format/city/level/seniority: текущий 'unknown'/'any', новый — конкретный;
    - description: пустое поле или новое существенно длиннее (+20%);
    - target_audience/event_type: были пустыми, заполнились;
    - quality_score/hype_score: были None, новые есть.

    Это закрывает кейс «то же событие, новая дата/URL/расширенное описание» —
    раньше ingestion просто `skipped` его при найденном duplicate. Embedding/
    series_slug не пересчитываем: title тот же, семантика близкая.
    """
    from app.recommender.hybrid import _parse_event_date

    if new_url and not event.source_url:
        event.source_url = new_url
    if new_date and not event.date:
        event.date = new_date
        event.start_at = _parse_event_date(new_date)
    elif new_date:
        # Если новая дата валиднее ИЛИ старее текущей по start_at — обновляем.
        # Прецедент: повторный анонс серии с уточнённой датой.
        new_start = _parse_event_date(new_date)
        if new_start is not None and (event.start_at is None or new_start != event.start_at):
            event.date = new_date
            event.start_at = new_start

    for field, neutral_values in (
        ("format", ("unknown",)),
        ("city", ("unknown", "any")),
        ("level", ("unknown", "any")),
        ("seniority", ("any",)),
        ("event_type", ("unknown",)),
    ):
        current = getattr(event, field, None)
        new_val = item.get(field)
        if new_val and current in (None, "", *neutral_values) and new_val not in neutral_values:
            setattr(event, field, new_val)

    new_desc = (item.get("description") or "").strip()
    cur_desc = (event.description or "").strip()
    if new_desc and (not cur_desc or len(new_desc) > len(cur_desc) * 1.2):
        event.description = new_desc

    new_audience = (item.get("target_audience") or "").strip()
    if new_audience and not (event.target_audience or "").strip():
        event.target_audience = new_audience

    for score_field in ("quality_score", "hype_score"):
        if getattr(event, score_field, None) is None and item.get(score_field) is not None:
            setattr(event, score_field, item[score_field])


def _normalize_single(db: Session, raw: RawEvent) -> str:
    """Нормализовать одно raw-событие: LLM-вызов + persist.

    Возвращает 'normalized' | 'non_it' | 'failed'. Rate-limit (429/квота)
    ПРОБРАСЫВАЕТСЯ наружу — чтобы батч-цикл мог остановиться рано и оставить
    необработанные события в статусе 'raw' (а не выжигать их в 'failed').
    """
    from app.agents.event_normalization.agent import event_normalizer_agent

    try:
        result = event_normalizer_agent({
            "raw_event": {
                "title": raw.title,
                "raw_description": raw.raw_description,
                "source_url": raw.source_url,
            },
            "normalized_event": {},
        })
        item = result["normalized_event"]
    except Exception as e:
        if _is_rate_limit_error(e):
            raise
        _mark_failed(raw, e)
        return "failed"

    try:
        return _persist_normalized(db, raw, item)
    except Exception as e:
        _mark_failed(raw, e)
        return "failed"


def _normalize_chunk(db: Session, chunk: list[RawEvent]) -> tuple[int, int, int, bool]:
    """Нормализовать пачку. Возвращает (normalized, non_it, failed, rate_limited).

    Сначала пробует один батч-LLM-вызов (экономия токенов). При сбое батча
    (невалидный JSON / рассинхрон длины) — деградирует до per-event. При
    rate-limit оставшиеся в пачке события НЕ трогаются (остаются 'raw'),
    rate_limited=True — сигнал верхнему циклу остановиться.
    """
    from app.agents.event_normalization.agent import event_normalizer_agent_batch

    normalized = non_it = failed = 0

    items: list[dict] | None = None
    try:
        payloads = [
            {"title": r.title, "raw_description": r.raw_description, "source_url": r.source_url}
            for r in chunk
        ]
        items = event_normalizer_agent_batch(payloads)
    except Exception as e:
        if _is_rate_limit_error(e):
            return 0, 0, 0, True
        # не rate-limit (битый JSON и т.п.) — деградируем до per-event ниже
        items = None

    # Быстрый путь: батч удался и длина совпала — persist по элементам.
    if items is not None and len(items) == len(chunk):
        for raw, item in zip(chunk, items, strict=True):
            try:
                status = _persist_normalized(db, raw, item)
            except Exception as e:
                _mark_failed(raw, e)
                status = "failed"
            normalized += status == "normalized"
            non_it += status == "non_it"
            failed += status == "failed"
        return normalized, non_it, failed, False

    # Fallback: по одному. Rate-limit здесь → стоп, остальные остаются 'raw'.
    for raw in chunk:
        try:
            status = _normalize_single(db, raw)
        except Exception as e:
            if _is_rate_limit_error(e):
                return normalized, non_it, failed, True
            _mark_failed(raw, e)
            status = "failed"
        normalized += status == "normalized"
        non_it += status == "non_it"
        failed += status == "failed"
    return normalized, non_it, failed, False


def _adaptive_batch_size(
    events: list[RawEvent],
    *,
    target_chars: int = 6000,
    min_size: int = 2,
    max_size: int = 10,
) -> int:
    """Подобрать batch_size по средней длине описаний.

    Раньше был жёсткий 5: на коротких telegram-постах это недоиспользовало
    бюджет токенов (можно было кидать по 10), на длинных habr-простынях —
    наоборот, переваливало за лимит и провоцировало 429. Целимся в ~6000
    символов на чанк (~1500 токенов для русского), но зажимаем в
    [min_size..max_size], чтобы не уходить ни в 1 (медленно), ни в 50
    (LLM начинает терять элементы).
    """
    if not events:
        return max_size
    avg = sum(
        len(getattr(r, "raw_description", "") or "") + len(getattr(r, "title", "") or "")
        for r in events
    ) / len(events)
    if avg <= 0:
        return max_size
    return max(min_size, min(max_size, int(target_chars / avg)))


def _normalize_by_ids(
    db: Session, raw_ids: list[int], batch_size: int | None = None
) -> tuple[int, int, int]:
    """Прогнать строки raw_events через AI-нормализатор пачками.

    Батчинг (несколько событий на один LLM-вызов) кратно экономит токены —
    без него ingestion быстро выжигал дневной лимит Groq. При rate-limit
    обработка останавливается рано: недообработанные остаются в статусе 'raw'
    и доберутся следующим вызовом /normalize.

    `batch_size=None` — выбрать адаптивно по длине описаний; явное число
    оставляет старое поведение (используется в тестах).

    Возвращает (normalized, non_it, failed).
    """
    if not raw_ids:
        return 0, 0, 0

    raw_events = db.query(RawEvent).filter(RawEvent.id.in_(raw_ids)).all()
    normalized = non_it = failed = 0

    effective_batch = (
        batch_size if batch_size is not None else _adaptive_batch_size(raw_events)
    )
    import logging
    logger = logging.getLogger(__name__)
    if batch_size is None:
        logger.info(
            "normalize: adaptive batch_size=%d for %d events",
            effective_batch, len(raw_events),
        )

    for start in range(0, len(raw_events), max(1, effective_batch)):
        chunk = raw_events[start:start + effective_batch]
        n, ni, f, rate_limited = _normalize_chunk(db, chunk)
        normalized += n
        non_it += ni
        failed += f
        if rate_limited:
            left = len(raw_events) - (start + len(chunk))
            logger.warning(
                "normalize stopped early on rate-limit; %d events left as 'raw'", left,
            )
            break

    # Safe commit: при длинных LLM-вызовах Supabase pooler может закрыть
    # SSL-сокет до того, как мы дошли сюда. Голый db.commit() в таком
    # случае ловит SSL SYSCALL EOF -> PendingRollbackError, а вышестоящий
    # load_all_events ловит «invalid transaction», и СЛЕДУЮЩИЙ источник
    # каскадом валится с тем же PendingRollbackError. Делаем rollback на
    # сбое — следующий источник стартует с чистой сессией.
    try:
        db.commit()
    except Exception as e:
        logger.warning(
            "normalize: commit failed (%s) — rolling back, statuses written до этого момента "
            "уйдут в /retry-failed", e,
        )
        with contextlib.suppress(Exception):
            db.rollback()
    return normalized, non_it, failed


def get_ingestion_status(db: Session) -> dict:
    """Счётчики raw-событий по статусам."""
    total = db.query(RawEvent).count()
    return {
        "total": total,
        "raw": db.query(RawEvent).filter(RawEvent.status == "raw").count(),
        "normalized": db.query(RawEvent).filter(RawEvent.status == "normalized").count(),
        "non_it": db.query(RawEvent).filter(RawEvent.status == "non_it").count(),
        "failed": db.query(RawEvent).filter(RawEvent.status == "failed").count(),
    }
