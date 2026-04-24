import json

from langchain_core.prompts import ChatPromptTemplate

from app.agents.recommendation.llm import llm
from app.agents.event_normalization.state import EventNormalizationState


ALLOWED_TOPICS = [
    "ai_ml",
    "data_science",
    "business_analytics",
    "backend",
    "frontend",
    "product",
    "cybersecurity",
    "devops",
]


def _extract_json(text: str) -> dict:
    text = text.strip()

    if text.startswith("```json"):
        text = text.removeprefix("```json").removesuffix("```").strip()
    elif text.startswith("```"):
        text = text.removeprefix("```").removesuffix("```").strip()

    return json.loads(text)


def event_normalizer_agent(state: EventNormalizationState):
    prompt = ChatPromptTemplate.from_messages([
        ("system", """
Ты EventNormalizerAgent для системы рекомендаций IT-событий.

Твоя задача:
1. Проанализировать сырое описание события.
2. Извлечь и нормализовать поля.
3. Если формат, город, уровень или темы не указаны явно — аккуратно вывести их из описания.
4. Не придумывать факты, если данных недостаточно.
5. Вернуть ТОЛЬКО валидный JSON без markdown и пояснений.

Допустимые значения:

format:
- online
- offline
- hybrid
- unknown

city:
- moscow
- spb
- kazan
- ekb
- any
- unknown

level:
- beginner
- middle
- advanced
- unknown

topics:
- ai_ml
- data_science
- business_analytics
- backend
- frontend
- product
- cybersecurity
- devops

event_type:
- meetup
- conference
- webinar
- workshop
- hackathon
- lecture
- unknown

Правила:
- Если событие онлайн, city = "any".
- Если явно указан вебинар, трансляция или онлайн-встреча, format = "online".
- Если указан физический адрес, площадка или офис, format = "offline".
- Если указан и онлайн, и офлайн формат, format = "hybrid".
- Если город нельзя определить, city = "unknown".
- Если уровень нельзя определить, level = "unknown".
- topics должен быть списком из допустимых значений.
- description сделай коротким и чистым, без мусора.
"""),
        ("user", """
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
""")
    ])

    result = llm.invoke(
        prompt.format_messages(
            raw_event=json.dumps(state["raw_event"], ensure_ascii=False)
        )
    )

    normalized = _extract_json(result.content)

    normalized["topics"] = [
        topic for topic in normalized.get("topics", [])
        if topic in ALLOWED_TOPICS
    ]

    return {
        "normalized_event": normalized
    }