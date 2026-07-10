"""Поиск по событиям на естественном языке.

Пользователь пишет фразу типа «конференции по AI/ML с 3 по 10 июня в Москве».
LLM извлекает структуру `{date_from, date_to, city, event_type, topics,
free_text}`, потом мы строим SQL по полям + полнотекстовый поиск по
остатку. Если LLM не извлёк ничего конкретного — откатываемся к старому
`combined_search` (точные совпадения + семантика).

LLM-вызов кэшируется по нормализованному запросу (LRU, 256 записей) —
один и тот же запрос от разных пользователей не должен повторно жечь токены.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from functools import lru_cache

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.agents.event_normalization.agent import _ALLOWED_EVENT_TYPE, _ALLOWED_FORMAT
from app.api.services.search_service import _serialize_event, combined_search
from app.core.topics import (
    SEED_TOPIC_TITLES,
    canonicalize_city,
)
from app.db.event_filters import upcoming_only
from app.db.models.event import Event
from app.recommender.scoring import _get_event_topic_codes

logger = logging.getLogger(__name__)

# Темы, на которые LLM может маппить запросы. Берём текущий seed-словарь —
# его достаточно для покрытия 95% IT-запросов. Если LLM эмитнет тему вне
# списка, отфильтруем на постпроцессе.
_KNOWN_TOPICS: frozenset[str] = frozenset(SEED_TOPIC_TITLES.keys())


_EMPTY_FILTERS: dict = {
    "date_from": None, "date_to": None, "city": None,
    "event_type": None, "format": None, "topics": [], "free_text": "",
}


def _normalize_query(query: str) -> str:
    return " ".join((query or "").lower().split())


@lru_cache(maxsize=256)
def _extract_filters_cached(normalized_query: str, today_iso: str) -> str:
    """LLM-извлечение фильтров. Возвращает JSON-строку — для cacheability."""
    return json.dumps(_extract_filters_raw(normalized_query, today_iso))


def _extract_filters_raw(query: str, today_iso: str) -> dict:
    """Один LLM-вызов: структурированное извлечение фильтров.

    На сбой LLM возвращает пустую структуру — выше нас её увидит fallback
    на combined_search.
    """
    try:
        from pydantic import BaseModel, Field

        from app.agents.recommendation.llm import llm

        class SearchFilters(BaseModel):
            date_from: str | None = Field(
                None,
                description="ISO YYYY-MM-DD: начало диапазона дат. "
                "Если конкретная дата — date_from == date_to. null, если в запросе нет дат.",
            )
            date_to: str | None = Field(
                None,
                description="ISO YYYY-MM-DD: конец диапазона дат (включительно). null, если нет.",
            )
            city: str | None = Field(
                None,
                description="Канонический slug города из списка: moscow, spb, "
                "ekb, kazan, novosibirsk, nizhny_novgorod, chelyabinsk, samara, "
                "ufa, rostov, krasnodar, voronezh, perm, tomsk, innopolis, "
                "sochi, vladivostok. null, если город не упомянут.",
            )
            event_type: str | None = Field(
                None,
                description="Тип события из списка: meetup, conference, webinar, "
                "workshop, hackathon, lecture. null, если не упомянут.",
            )
            format: str | None = Field(
                None,
                description="Формат проведения: online, offline, hybrid. null, "
                "если не упомянут. «онлайн»/«вебинар-онлайн» → online; «оффлайн»/"
                "«очно»/«в зале» → offline; «гибрид»/«смешанный» → hybrid.",
            )
            topics: list[str] = Field(
                default_factory=list,
                description="Slug'и тем из списка: ai_ml, data_science, "
                "business_analytics, backend, frontend, product, cybersecurity, "
                "devops. Пустой список, если тема не упомянута.",
            )
            free_text: str = Field(
                "",
                description="Остаток запроса после вытаскивания всех фильтров "
                "выше. Используется как ключевые слова для title/description. "
                "Пустая строка, если весь запрос ушёл в фильтры.",
            )

        sys_prompt = (
            "Ты парсер поисковых запросов IT-мероприятий. Извлекай из "
            f"запроса пользователя структуру фильтров. Сегодня: {today_iso}.\n\n"
            "ПРАВИЛА:\n"
            "1) «конференции» → event_type=conference. «митапы» → meetup. "
            "«вебинары» → webinar. «хакатоны» → hackathon. «воркшопы» → workshop.\n"
            "2) Относительные даты считай от сегодняшней даты:\n"
            "   • «завтра» → date_from = date_to = завтра.\n"
            "   • «на следующей неделе» → пн..вс след. недели.\n"
            "   • «в июне», «летом» → весь месяц / сезон текущего года.\n"
            "   • «с 3 по 10 июня» → конкретный диапазон. Год — текущий, "
            "если месяц ещё не прошёл; иначе следующий.\n"
            "3) Города: только из списка. Транслиты (msk, moskva, piter, "
            "yekaterinburg) → каноническое (moscow, spb, ekb). Города не из "
            "списка → null.\n"
            "4) Формат: «онлайн»/«вебинар»/«дистанционно» → online; «оффлайн»/"
            "«очно»/«в зале»/«в москве лично» → offline; «гибрид» → hybrid. "
            "Внимание: «онлайн конференции» → event_type=conference + format=online, "
            "слово «онлайн» НЕ должно попадать в free_text.\n"
            "5) Темы: только из списка. Синонимы маппи: «машинное обучение»/"
            "«ИИ»→ai_ml, «безопасность»→cybersecurity, «бэкенд»→backend и т. д.\n"
            "6) free_text: остаток запроса без слов про даты, города, тип "
            "события и формат — это будет искаться по title/description. "
            "Если весь запрос разобран на фильтры — пустая строка.\n"
            "7) Если запрос не похож на поиск событий (бессмыслица, "
            "вопрос не по теме) — оставь все поля пустыми."
        )

        result = llm.with_structured_output(SearchFilters).invoke(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": query}]
        )
        return _postprocess(result if isinstance(result, dict) else result.model_dump())
    except Exception as e:
        logger.warning("nl-search LLM extract failed: %s", e)
        return dict(_EMPTY_FILTERS)


def _postprocess(raw: dict) -> dict:
    """Канонизация и валидация полей, которые вернула LLM."""
    out = dict(_EMPTY_FILTERS)

    df = _parse_iso_date(raw.get("date_from"))
    dt = _parse_iso_date(raw.get("date_to"))
    if df and dt and df > dt:
        df, dt = dt, df  # на случай инвертированного диапазона
    out["date_from"] = df.isoformat() if df else None
    out["date_to"] = dt.isoformat() if dt else None

    city_raw = raw.get("city")
    if isinstance(city_raw, str) and city_raw.strip():
        canon = canonicalize_city(city_raw.strip())
        out["city"] = canon or None

    etype = raw.get("event_type")
    if isinstance(etype, str) and etype.strip() in _ALLOWED_EVENT_TYPE:
        out["event_type"] = etype.strip()

    fmt = raw.get("format")
    if isinstance(fmt, str) and fmt.strip() in _ALLOWED_FORMAT and fmt.strip() not in {"any", "unknown"}:
        out["format"] = fmt.strip()

    topics_raw = raw.get("topics") or []
    if isinstance(topics_raw, list):
        out["topics"] = [t for t in topics_raw if isinstance(t, str) and t in _KNOWN_TOPICS]

    free = raw.get("free_text") or ""
    out["free_text"] = free.strip() if isinstance(free, str) else ""

    return out


def _parse_iso_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    try:
        return datetime.fromisoformat(v).date()
    except ValueError:
        return None


def _has_useful_filters(filters: dict) -> bool:
    """True, если LLM извлёк хоть что-то конкретное (а не просто free_text)."""
    return bool(
        filters.get("date_from") or filters.get("date_to")
        or filters.get("city") or filters.get("event_type")
        or filters.get("format") or filters.get("topics")
    )


def extract_filters(query: str, today: date | None = None) -> dict:
    """Публичный вход — обёртка над LRU-кэшем."""
    today = today or date.today()
    norm = _normalize_query(query)
    if not norm:
        return dict(_EMPTY_FILTERS)
    return json.loads(_extract_filters_cached(norm, today.isoformat()))


def _apply_filters(db: Session, filters: dict, limit: int) -> list[Event]:
    """Построить SQL-запрос по набору фильтров и вернуть события (без сериализации).

    Логика NULL для `start_at`:
    - В `upcoming_only` события без даты остаются — мы не знаем, прошли они
      или нет, лучше показать (источник просто не дал час/день).
    - При ЯВНОМ диапазоне дат (date_from/date_to) события без `start_at`
      ОТСЕИВАЕМ: пользователь сказал «в августе», статья без даты — это
      точно не «в августе», и пропускать такую было ошибкой (раньше
      запрос «события в августе» возвращал хабровские статьи без даты).
    """
    q = upcoming_only(db.query(Event))

    if filters.get("date_from"):
        start = datetime.fromisoformat(filters["date_from"])
        q = q.filter(Event.start_at.isnot(None), Event.start_at >= start)
    if filters.get("date_to"):
        end = datetime.fromisoformat(filters["date_to"])
        end_inclusive = end.replace(hour=23, minute=59, second=59)
        q = q.filter(Event.start_at.isnot(None), Event.start_at <= end_inclusive)
    if filters.get("city"):
        q = q.filter(Event.city == filters["city"])
    if filters.get("event_type"):
        q = q.filter(Event.event_type == filters["event_type"])
    if filters.get("format"):
        q = q.filter(Event.format == filters["format"])

    free_text = (filters.get("free_text") or "").strip()
    if free_text:
        like = f"%{free_text.lower()}%"
        q = q.filter(or_(Event.title.ilike(like), Event.description.ilike(like)))

    events = q.limit(limit * 3).all()

    topics_filter = set(filters.get("topics") or [])
    if topics_filter:
        events = [
            e for e in events
            if _get_event_topic_codes(e).intersection(topics_filter)
        ]
    return events[:limit]


# Порядок снятия фильтров при 0 результатов. Самые «вспомогательные» уходят
# первыми (free_text — часто шум вроде «онлайн», которое уже ушло в format).
# Дата уходит последней — если пользователь сказал «с 14 по 25», убирать её
# обиднее всего, она самая конкретная.
_RELAX_ORDER: list[str | tuple[str, str]] = [
    "free_text",
    "topics",
    "format",
    "event_type",
    "city",
    ("date_from", "date_to"),
]


def _relax_filters(filters: dict, drop_key) -> dict:
    """Вернуть новый dict фильтров с убранным ключом (или парой ключей)."""
    relaxed = dict(filters)
    keys = (drop_key,) if isinstance(drop_key, str) else drop_key
    for k in keys:
        if k == "free_text":
            relaxed[k] = ""
        elif k == "topics":
            relaxed[k] = []
        else:
            relaxed[k] = None
    return relaxed


_RELAX_LABEL_RU: dict[str, str] = {
    "free_text": "слов из текста",
    "topics": "темы",
    "format": "формата",
    "event_type": "типа события",
    "city": "города",
    "date_from": "даты",
    "date_to": "даты",
}


def _label_dropped(drop_key) -> str:
    keys = (drop_key,) if isinstance(drop_key, str) else drop_key
    # Для пары date_from+date_to не дублируем «даты, даты».
    labels = []
    for k in keys:
        lab = _RELAX_LABEL_RU.get(k, k)
        if lab not in labels:
            labels.append(lab)
    return " и ".join(labels)


def nl_search(db: Session, query: str, limit: int = 5, relax_limit: int = 1) -> dict:
    """Главная функция: фильтры из LLM → SQL → события.

    Возвращает:
      {
        "events": [...],            # сериализованные карточки
        "filters": {...},           # фильтры, по которым реально нашли
        "original_filters": {...},  # что изначально извлёк LLM
        "extracted": bool,          # удалось ли вытащить структурированные фильтры
        "fallback_used": bool,      # ушли ли в combined_search
        "relaxed": bool,            # пришлось ли снимать фильтры
        "dropped": [str, ...],      # человеческие лейблы снятых фильтров
      }

    Поведение:
    - Строгий проход → до `limit` совпадений (по умолчанию 5).
    - 0 строгих совпадений → поэтапная релаксация (free_text → topics →
      format → event_type → city → date), но выдаём только до `relax_limit`
      ближайших событий (по умолчанию 1) — это «вот близкое, остальное
      смотри в рекомендациях».
    - Совсем 0 → пустой результат с relaxed=True и списком снятого.
    """
    if not query or not query.strip():
        return {"events": [], "filters": dict(_EMPTY_FILTERS),
                "original_filters": dict(_EMPTY_FILTERS),
                "extracted": False, "fallback_used": False,
                "relaxed": False, "dropped": []}

    filters = extract_filters(query)
    if not _has_useful_filters(filters) and not filters.get("free_text"):
        # LLM вернула совсем пусто → старый поиск (ограничиваем тем же limit).
        legacy = combined_search(db, query=query, keyword_limit=3, semantic_limit=limit)
        events = (legacy.get("keyword") or []) + (legacy.get("semantic") or [])
        return {"events": events[:limit], "filters": dict(_EMPTY_FILTERS),
                "original_filters": dict(_EMPTY_FILTERS),
                "extracted": False, "fallback_used": True,
                "relaxed": False, "dropped": []}

    # Строгий проход.
    events = _apply_filters(db, filters, limit)
    if events:
        return {
            "events": [_serialize_event(e) for e in events],
            "filters": filters,
            "original_filters": filters,
            "extracted": True, "fallback_used": False,
            "relaxed": False, "dropped": [],
        }

    # Релаксация: поэтапно убираем по одному фильтру, останавливаемся на первом
    # наборе, давшем события. При успехе показываем только relax_limit штук
    # (одно ближайшее) — остальное пользователю предложим в рекомендациях.
    relaxed = dict(filters)
    dropped: list[str] = []
    for key in _RELAX_ORDER:
        keys_to_check = (key,) if isinstance(key, str) else key
        if not any(relaxed.get(k) for k in keys_to_check):
            continue
        relaxed = _relax_filters(relaxed, key)
        dropped.append(_label_dropped(key))
        if not _has_useful_filters(relaxed) and not (relaxed.get("free_text") or "").strip():
            break
        events = _apply_filters(db, relaxed, relax_limit)
        if events:
            return {
                "events": [_serialize_event(e) for e in events],
                "filters": relaxed,
                "original_filters": filters,
                "extracted": True, "fallback_used": False,
                "relaxed": True, "dropped": dropped,
            }

    # Совсем ничего — отдаём пустой результат с пометкой, что пытались релаксировать.
    return {
        "events": [], "filters": filters, "original_filters": filters,
        "extracted": True, "fallback_used": False,
        "relaxed": True, "dropped": dropped,
    }
