import datetime as _dt
import json
import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from app.agents.event_normalization.state import EventNormalizationState
from app.agents.recommendation.llm import llm
from app.core.topics import (
    SEED_CITY_LABELS,
    SEED_FORMAT_LABELS,
    SEED_LEVEL_LABELS,
    SEED_TOPICS,
    slugify_code,
)

logger = logging.getLogger(__name__)

# Принимаем строго YYYY-MM-DD (опционально с T<time>): берём только дату-префикс.
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ]|$)")
# Разумный диапазон: события прошлого года и до 3 лет вперёд. LLM иногда
# галлюцинирует «1970» или «2099» — это явный мусор, не пускаем в БД.
_DATE_YEAR_MIN = 2020
_DATE_YEAR_MAX = 2035


def _validate_iso_date(raw) -> str:
    """Привести date от LLM к строгому YYYY-MM-DD или вернуть "".

    LLM просят `YYYY-MM-DD`, но без валидации в БД попадало «лето 2026»,
    «2026-13-45», `null` и т.п. — события молча получали start_at=None и
    выпадали из freshness/сортировки. Здесь:
    - вытаскиваем дату-префикс regex'ом (терпим `2026-05-29T18:00`);
    - календарно валидируем через `date()` — отбрасываем 30 февраля;
    - проверяем год в [2020..2035] — отсекаем явные галлюцинации.
    Невалидные значения логируем (DEBUG) и возвращаем пустую строку, чтобы
    раздел freshness честно показал «дата неизвестна», а не врал нулём.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    m = _ISO_DATE_RE.match(s)
    if not m:
        logger.debug("normalizer: rejecting non-ISO date %r", s)
        return ""
    try:
        d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        logger.debug("normalizer: rejecting invalid calendar date %r", s)
        return ""
    if not (_DATE_YEAR_MIN <= d.year <= _DATE_YEAR_MAX):
        logger.debug("normalizer: rejecting out-of-range date %r", s)
        return ""
    return d.isoformat()


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text.removeprefix("```json").removesuffix("```").strip()
    elif text.startswith("```"):
        text = text.removeprefix("```").removesuffix("```").strip()
    return text


def _extract_json(text: str) -> dict:
    return json.loads(_strip_fences(text))


def _extract_json_array(text: str) -> list:
    data = json.loads(_strip_fences(text))
    if not isinstance(data, list):
        raise ValueError("expected JSON array from batch normalizer")
    return data


# Списки ниже — *предпочтительные* значения. LLM призывается переиспользовать
# их, но незнакомые slug'и принимаются и сохраняются, чтобы словарь мог
# расти вместе с новыми источниками.
_PREFERRED_TOPICS = ", ".join(SEED_TOPICS)
_PREFERRED_CITIES = ", ".join(SEED_CITY_LABELS.keys())
_PREFERRED_LEVELS = ", ".join(SEED_LEVEL_LABELS.keys())
_PREFERRED_FORMATS = ", ".join(SEED_FORMAT_LABELS.keys())


_SYSTEM_PROMPT = f"""
Ты EventNormalizerAgent для системы рекомендаций IT-событий.

Твоя задача:
1. Проанализировать сырое описание события.
2. Извлечь и нормализовать поля.
3. Если формат, город, уровень или темы не указаны явно — вывести их из описания.
4. Не придумывать факты, если данных недостаточно.
5. Вернуть ТОЛЬКО валидный JSON без markdown и пояснений.

Предпочитаемые значения (используй их, когда подходят):
format: {_PREFERRED_FORMATS}
city: {_PREFERRED_CITIES}
level: {_PREFERRED_LEVELS}
topics: {_PREFERRED_TOPICS}
event_type: meetup | conference | webinar | workshop | hackathon | lecture | unknown
seniority: junior | middle | senior | any

ВАЖНО про новые значения:
- Если событие явно НЕ попадает в перечисленные topics/city/level, ты можешь
  создать новый код в формате короткого латинского slug в snake_case
  (например topic "mlops", city "novosibirsk", level "expert").
- Используй существующие значения, когда они подходят — не плоди дубли
  ("ml" вместо "ai_ml" недопустимо).
- city для онлайн-событий = "any", если место не указано → "unknown".
- format: вебинар/трансляция → "online"; физический адрес → "offline";
  оба формата → "hybrid".
- date — дата начала строго в формате YYYY-MM-DD (для диапазона — дата начала);
  если дата неизвестна → "" (пустая строка).
- topics — список slug'ов. Минимум 1 для IT-событий.
- tech_stack — список конкретных технологий (["Python", "FastAPI", "Docker"]).
- seniority — "junior"/"middle"/"senior"/"any".
- quality_score (1-10) — информативность для IT-специалиста.
- hype_score (1-10) — актуальность темы в IT сейчас.

ВАЖНО — ФИЛЬТРАЦИЯ НЕ-IT СОБЫТИЙ (строгий режим):

Правило отсечения: если событие НЕ про разработку ПО / данные / инфраструктуру /
кибербезопасность / IT-продукт / IT-инжиниринг — `topics = []` (даже если в
описании есть слова «инновации», «технологии», «диджитал», «AI» без сути).

❌ НЕ IT (`topics = []`), даже если звучит «технологично»:
- PR / маркетинг / SMM / контент-стратегия без разработки
- HR / эйчар / рекрутинг (включая «нанимаем айтишников»)
- продажи / сейлз / B2B-конференции без технического стека
- лидерство, soft skills, коучинг, психология, продуктивность
- мода, дизайн интерьеров, фитнес, спорт, медицина (если без IT-фокуса)
- бухгалтерия / финансы / инвестиции / трейдинг без AI/ML-составляющей
- криптовалюты как актив (без разработки), NFT-арт
- юриспруденция, образование как процесс (если не EdTech-разработка)
- бизнес-завтраки, нетворкинг-вечеринки, премии, конкурсы без технической программы

✅ IT (минимум одна тема в `topics`):
- разработка ПО (backend/frontend/mobile/embedded), архитектура
- DevOps, SRE, облака, инфраструктура, observability
- AI/ML/LLM/Data Science/Data Engineering/MLOps
- кибербезопасность, AppSec, pentest
- продукт-менеджмент / системный анализ / QA — только если про IT-продукт
- хакатоны, CTF, codefest'ы, IT-конференции и митапы

ПРАВИЛО ГРАНИЦЫ: «AI в маркетинге» / «no-code для бухгалтеров» — IT, если
программа реально содержит технический контент (модели, инструменты,
интеграции). Если только лозунги «использовать ИИ» без сути — НЕ-IT.

Примеры решений:
- «Конференция PR-2026: новые медиа» → `topics = []`
- «HR-Tech Forum» (только про подбор и адаптацию) → `topics = []`
- «MeetUp DevOps Moscow: Kubernetes, Argo CD, observability» → `topics=["devops"]`
- «AI в e-commerce: рекомендации и поиск, доклады инженеров» → `topics=["ai_ml","backend"]`
- «PyCon Russia» → `topics=["backend","ai_ml"]` (с учётом программы)
"""

_USER_PROMPT = """
Сырое событие:
{raw_event}

Верни JSON строго в формате:
{{
  "title": "...",
  "description": "...",
  "format": "online/offline/hybrid/unknown",
  "city": "<slug города или any/unknown>",
  "level": "<slug уровня или unknown>",
  "date": "...",
  "topics": ["<slug темы>", "..."],
  "event_type": "meetup/conference/webinar/workshop/hackathon/lecture/unknown",
  "target_audience": "...",
  "source_url": "...",
  "tech_stack": ["..."],
  "seniority": "junior/middle/senior/any",
  "quality_score": 7,
  "hype_score": 8
}}
"""


def event_normalizer_agent(state: EventNormalizationState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("user", _USER_PROMPT),
    ])

    result = llm.invoke(
        prompt.format_messages(
            raw_event=json.dumps(state["raw_event"], ensure_ascii=False)
        )
    )

    normalized = _postprocess_normalized(_extract_json(result.content))
    return {"normalized_event": normalized}


def _postprocess_normalized(normalized: dict) -> dict:
    """Привести сырой LLM-JSON к каноничному виду: slugify полей, clamp score'ов,
    гарантия типов. Общий код для одиночной и батч-нормализации."""
    # Прогоняем все свободные строки от LLM через slugify — это гарантирует
    # единый формат словаря (snake_case) независимо от того, как выглядели
    # исходные данные.
    normalized["topics"] = _slug_list(normalized.get("topics", []))
    for field in ("format", "city", "level", "event_type", "seniority"):
        if normalized.get(field):
            normalized[field] = slugify_code(normalized[field]) or normalized[field]

    # Зажимаем score'ы в допустимый диапазон 1..10
    for score_field in ("quality_score", "hype_score"):
        val = normalized.get(score_field)
        if isinstance(val, int | float):
            normalized[score_field] = max(1, min(10, int(val)))
        else:
            normalized[score_field] = None

    # tech_stack гарантированно должен быть списком
    if not isinstance(normalized.get("tech_stack"), list):
        normalized["tech_stack"] = []

    # Строгая валидация даты: мусорные значения от LLM в events.date не пускаем —
    # либо валидная YYYY-MM-DD, либо пустая строка.
    normalized["date"] = _validate_iso_date(normalized.get("date"))

    return normalized


_BATCH_SYSTEM_PROMPT = _SYSTEM_PROMPT + """

РЕЖИМ ПАКЕТНОЙ ОБРАБОТКИ:
Тебе придёт JSON-массив сырых событий, у каждого есть числовое поле "idx".
Верни СТРОГО JSON-массив той же длины и в том же порядке — по одному объекту
на каждое входное событие. В каждый объект СКОПИРУЙ его "idx" из входа.
Никакого текста и markdown вне массива.
"""

_BATCH_USER_PROMPT = """
Сырые события (JSON-массив):
{raw_events}

Верни JSON-массив, по объекту на событие, каждый строго в формате:
{{
  "idx": <число из входа>,
  "title": "...",
  "description": "...",
  "format": "online/offline/hybrid/unknown",
  "city": "<slug города или any/unknown>",
  "level": "<slug уровня или unknown>",
  "date": "...",
  "topics": ["<slug темы>", "..."],
  "event_type": "meetup/conference/webinar/workshop/hackathon/lecture/unknown",
  "target_audience": "...",
  "source_url": "...",
  "tech_stack": ["..."],
  "seniority": "junior/middle/senior/any",
  "quality_score": 7,
  "hype_score": 8
}}
"""


def event_normalizer_agent_batch(raw_events: list[dict]) -> list[dict]:
    """Нормализовать НЕСКОЛЬКО событий одним LLM-вызовом (экономия токенов).

    Возвращает список normalized-dict той же длины и порядка, что вход.
    Бросает исключение при сбое LLM, невалидном JSON или несоответствии длины —
    вызывающая сторона (ingestion) делает per-event fallback.
    """
    if not raw_events:
        return []

    payload = [{"idx": i, **ev} for i, ev in enumerate(raw_events)]
    prompt = ChatPromptTemplate.from_messages([
        ("system", _BATCH_SYSTEM_PROMPT),
        ("user", _BATCH_USER_PROMPT),
    ])
    result = llm.invoke(
        prompt.format_messages(raw_events=json.dumps(payload, ensure_ascii=False))
    )
    data = _extract_json_array(result.content)

    # Сопоставляем по idx; при отсутствии — позиционно.
    by_idx: dict[int, dict] = {}
    for obj in data:
        if isinstance(obj, dict) and isinstance(obj.get("idx"), int):
            by_idx[obj["idx"]] = obj

    out: list[dict] = []
    for i in range(len(raw_events)):
        item = by_idx.get(i)
        if item is None:
            if i < len(data) and isinstance(data[i], dict):
                item = data[i]
            else:
                raise ValueError(f"batch normalize: missing item idx={i}")
        item.pop("idx", None)
        out.append(_postprocess_normalized(item))
    return out


def _slug_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            continue
        slug = slugify_code(v)
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out
