import json

from langchain_core.prompts import ChatPromptTemplate

from app.agents.recommendation.llm import llm
from app.agents.event_normalization.state import EventNormalizationState
from app.core.topics import ALLOWED_TOPICS


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json"):
        text = text.removeprefix("```json").removesuffix("```").strip()
    elif text.startswith("```"):
        text = text.removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


_SYSTEM_PROMPT = f"""
Ты EventNormalizerAgent для системы рекомендаций IT-событий.

Твоя задача:
1. Проанализировать сырое описание события.
2. Извлечь и нормализовать поля.
3. Если формат, город, уровень или темы не указаны явно — вывести их из описания.
4. Не придумывать факты, если данных недостаточно.
5. Вернуть ТОЛЬКО валидный JSON без markdown и пояснений.

Допустимые значения:
format: online | offline | hybrid | unknown
city: moscow | spb | kazan | ekb | any | unknown
level: beginner | middle | advanced | unknown
topics: {', '.join(ALLOWED_TOPICS)}
event_type: meetup | conference | webinar | workshop | hackathon | lecture | unknown

Правила:
- Если событие онлайн, city = "any".
- Если вебинар/трансляция/онлайн-встреча → format = "online".
- Если физический адрес/площадка/офис → format = "offline".
- Если указан и онлайн, и офлайн → format = "hybrid".
- Если город нельзя определить → city = "unknown".
- Если уровень нельзя определить → level = "unknown".
- topics — список из допустимых значений выше.
- description — короткое и чистое описание.

ВАЖНО — фильтрация не-IT событий:
- Это система ТОЛЬКО для IT-специалистов.
- Если событие не относится к IT (маркетинг, HR, PR, спорт, искусство, медицина,
  юриспруденция, финансы без IT-составляющей) → верни topics как [].
- Примеры НЕ-IT: премии за маркетинг, HR-конференции, PR-мероприятия, ретейл, производство.
- Примеры IT: конференции по разработке, DevOps, AI/ML, кибербезопасности,
  продуктовые митапы, хакатоны, аналитика данных.
"""

_USER_PROMPT = """
Сырое событие:
{raw_event}

Верни JSON строго в формате:
{{
  "title": "...",
  "description": "...",
  "format": "online/offline/hybrid/unknown",
  "city": "moscow/spb/kazan/ekb/any/unknown",
  "level": "beginner/middle/advanced/unknown",
  "date": "...",
  "topics": ["..."],
  "event_type": "meetup/conference/webinar/workshop/hackathon/lecture/unknown",
  "target_audience": "...",
  "source_url": "..."
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
    normalized["topics"] = [t for t in normalized.get("topics", []) if t in ALLOWED_TOPICS]

    return {"normalized_event": normalized}
