import json

from langchain_core.prompts import ChatPromptTemplate

from app.agents.recommendation.llm import llm
from app.agents.event_normalization.state import EventNormalizationState
from app.core.topics import (
    SEED_TOPICS,
    SEED_CITY_LABELS,
    SEED_LEVEL_LABELS,
    SEED_FORMAT_LABELS,
    slugify_code,
)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json"):
        text = text.removeprefix("```json").removesuffix("```").strip()
    elif text.startswith("```"):
        text = text.removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


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
- topics — список slug'ов. Минимум 1 для IT-событий.
- tech_stack — список конкретных технологий (["Python", "FastAPI", "Docker"]).
- seniority — "junior"/"middle"/"senior"/"any".
- quality_score (1-10) — информативность для IT-специалиста.
- hype_score (1-10) — актуальность темы в IT сейчас.

ВАЖНО — фильтрация не-IT событий:
- Если событие не относится к IT (маркетинг, HR, спорт, медицина и т.п.) → topics = [].
- Примеры НЕ-IT: PR-премии, HR-конференции, маркетинг без IT-составляющей.
- Примеры IT: DevOps-конференции, AI/ML митапы, хакатоны, аналитика данных.
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

    normalized = _extract_json(result.content)

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
        if isinstance(val, (int, float)):
            normalized[score_field] = max(1, min(10, int(val)))
        else:
            normalized[score_field] = None

    # tech_stack гарантированно должен быть списком
    if not isinstance(normalized.get("tech_stack"), list):
        normalized["tech_stack"] = []

    return {"normalized_event": normalized}


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
