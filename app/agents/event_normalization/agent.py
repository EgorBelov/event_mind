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
    canonicalize_city,
    slugify_code,
)

logger = logging.getLogger(__name__)

# Принимаем строго YYYY-MM-DD (опционально с T<time>): берём только дату-префикс.
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ]|$)")
# Разумный диапазон: события прошлого года и до 3 лет вперёд. LLM иногда
# галлюцинирует «1970» или «2099» — это явный мусор, не пускаем в БД.
_DATE_YEAR_MIN = 2020
_DATE_YEAR_MAX = 2035


# ── Строгий домен enum-полей ──────────────────────────────────────────────
# format/event_type/seniority — closed-domain в нашем UI и логике скоринга.
# city/level — open-domain (новые slug'и могут появляться вместе с источниками),
# но если LLM вернёт что-то явно мусорное (длинная строка с пробелами, мат, и т.п.) —
# выкидываем в "unknown", чтобы не плодить мусорные значения в БД.
_ALLOWED_FORMAT: frozenset[str] = frozenset({"online", "offline", "hybrid", "any", "unknown"})
_ALLOWED_EVENT_TYPE: frozenset[str] = frozenset({
    "meetup", "conference", "webinar", "workshop",
    "hackathon", "lecture", "unknown",
})
_ALLOWED_SENIORITY: frozenset[str] = frozenset({"junior", "middle", "senior", "any"})
# city/level не closed, но slug должен быть «нормальный» (короткий, snake_case).
_OPEN_SLUG_MAX_LEN = 32


def _normalize_enum_field(
    value, *, allowed: frozenset[str] | None, default: str, label: str
) -> str:
    """Привести значение к допустимому домену.

    - None/пустое → default.
    - Не-строка → default.
    - Closed domain (`allowed` задан) и значение вне него → default + лог.
    - Open domain (`allowed=None`) — slug длиной > _OPEN_SLUG_MAX_LEN или
      с пробелами/невалидными символами → default + лог.
    """
    if value is None or not isinstance(value, str):
        return default
    v = value.strip()
    if not v:
        return default
    if allowed is not None:
        if v in allowed:
            return v
        logger.debug("normalizer: rejecting %s=%r (not in domain)", label, v)
        return default
    # Open domain: уже прошёл через slugify_code, но всё равно ловим аномалии.
    if len(v) > _OPEN_SLUG_MAX_LEN or any(ch in v for ch in (" ", "/", "\\", "\n", "\t")):
        logger.debug("normalizer: rejecting %s=%r (malformed slug)", label, v)
        return default
    return v


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
  (например topic "mlops", city "barnaul", level "expert").
- Используй существующие значения, когда они подходят — не плоди дубли
  ("ml" вместо "ai_ml" недопустимо).
- format: вебинар/трансляция → "online"; физический адрес → "offline";
  оба формата → "hybrid".

ПРАВИЛА ИЗВЛЕЧЕНИЯ ГОРОДА (важно для UI и фильтрации):
- Ищи город в полях `location`, `address`, `venue`, а также в заголовке/
  описании по шаблонам: «г. X», «в X», «X, ул. ...», «X office», «hosted in X».
- Для офлайн-событий ВСЕГДА пытайся определить конкретный город из адреса —
  не сваливай в "unknown", если в тексте есть улица/площадка/метро.
- Для онлайн-событий: если организатор привязан к конкретному городу (например
  «Moscow Python Meetup онлайн») — используй город организатора, не "any".
- "any" — только если событие глобально-онлайн без привязки к городу.
- "unknown" — только если ни в одном поле города нет и определить нельзя.
- Используй ИМЕННО эти канонические slug-и для семи крупнейших IT-городов
  (UI знает русские лейблы только для них):
    Москва           → "moscow"        Санкт-Петербург  → "spb"
    Новосибирск      → "novosibirsk"   Екатеринбург     → "ekb"
    Казань           → "kazan"         Нижний Новгород  → "nizhny_novgorod"
    Челябинск        → "chelyabinsk"   Самара           → "samara"
    Уфа              → "ufa"           Ростов-на-Дону   → "rostov"
    Краснодар        → "krasnodar"     Воронеж          → "voronezh"
    Пермь            → "perm"          Томск            → "tomsk"
    Иннополис        → "innopolis"     Сочи             → "sochi"
    Владивосток      → "vladivostok"
- НЕ эмить альтернативные написания для городов из таблицы выше: "msk",
  "moskva", "piter", "saint_petersburg", "yekaterinburg" и подобные —
  ЗАПРЕЩЕНЫ, используй ТОЛЬКО канонический slug.
- Для города ВНЕ списка — короткий латинский snake_case транслит без
  диакритики (Омск → "omsk", Барнаул → "barnaul", Минск → "minsk").
- date — дата начала строго в формате YYYY-MM-DD (для диапазона — дата начала);
  если дата неизвестна → "" (пустая строка).
- topics — список slug'ов. Минимум 1 для IT-событий.
- tech_stack — список конкретных технологий (["Python", "FastAPI", "Docker"]).
- seniority — "junior"/"middle"/"senior"/"any".
- quality_score (1-10) — информативность для IT-специалиста.
- hype_score (1-10) — актуальность темы в IT сейчас.

ВАЖНО — ФИЛЬТРАЦИЯ «ЭТО ВООБЩЕ МЕРОПРИЯТИЕ?»:

Перед фильтром по IT-тематике проверь: перед тобой действительно дискретное
мероприятие (митап / конференция / вебинар / воркшоп / хакатон / лекция /
курс с конкретными сессиями)? Или это что-то другое?

❌ НЕ мероприятие (`topics = []`), даже если про IT:
- пресс-релиз / новость компании / запуск продукта / анонс релиза
- вакансия / стажировка / «нанимаем» / job posting
- поиск партнёров / business development / приглашение к сотрудничеству
- продажа курса как платного товара без расписания сессий
- статья / обзор / интервью / подкаст-эпизод
- объявление о покупке/продаже бизнеса, инвест-раунды
- маркетинговая рассылка, реклама услуг

Маркеры «не мероприятие»: заголовок/описание содержит «приглашает к сотрудничеству»,
«ищет партнёров», «нанимаем», «open позицию», «запустили», «релиз», «анонсирует
[продукт]», «инвестирует», но НЕ содержит даты/площадки/программы/спикеров.

✅ Мероприятие (продолжаем с IT-фильтром): есть конкретная дата ИЛИ площадка
ИЛИ программа выступлений ИЛИ упоминание спикеров/тем сессий. Достаточно
ОДНОГО из этих сигналов, чтобы считать мероприятием.

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

    # Канонизация города: схлопываем алиасы (msk → moscow, piter → spb, …)
    # ДО enum-валидации, чтобы в БД не появлялось двух slug'ов для одного
    # города. Применяется только к city — для остальных полей закрытый
    # домен и так гарантирует уникальность.
    if normalized.get("city"):
        normalized["city"] = canonicalize_city(normalized["city"]) or normalized["city"]

    # Boundary-валидация enum'ов. Раньше slugify пускал в БД любые «придуманные»
    # значения LLM — теперь closed-domain поля сваливаются в дефолт, open-domain
    # ловят аномалии (длина, пробелы) и тоже схлопываются. Раздел freshness/
    # MMR/UI получают чистый словарь, нет мусорных «virtual_online_in_zoom».
    normalized["format"] = _normalize_enum_field(
        normalized.get("format"), allowed=_ALLOWED_FORMAT,
        default="unknown", label="format",
    )
    normalized["event_type"] = _normalize_enum_field(
        normalized.get("event_type"), allowed=_ALLOWED_EVENT_TYPE,
        default="unknown", label="event_type",
    )
    normalized["seniority"] = _normalize_enum_field(
        normalized.get("seniority"), allowed=_ALLOWED_SENIORITY,
        default="any", label="seniority",
    )
    normalized["city"] = _normalize_enum_field(
        normalized.get("city"), allowed=None,
        default="unknown", label="city",
    )
    normalized["level"] = _normalize_enum_field(
        normalized.get("level"), allowed=None,
        default="unknown", label="level",
    )

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

    # Defence-in-depth «событие vs не-событие». Промпт учит LLM ставить
    # topics=[] для новостей/вакансий/PR/B2B-приглашений, но на случай если
    # модель промахнётся — гасим записи без единого event-сигнала.
    # «Не событие» = ОДНОВРЕМЕННО нет даты, нет формата, нет конкретного
    # города/площадки и нет распознанного event_type. У любого реального
    # мероприятия хотя бы один из этих сигналов присутствует.
    if normalized.get("topics"):
        no_date = not normalized.get("date")
        no_format = normalized.get("format") in (None, "", "unknown")
        no_city = normalized.get("city") in (None, "", "unknown", "any")
        no_type = normalized.get("event_type") in (None, "", "unknown")
        if no_date and no_format and no_city and no_type:
            logger.debug(
                "normalizer: dropping non-event entry (no date/format/city/type): %r",
                normalized.get("title", "")[:80],
            )
            normalized["topics"] = []

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
