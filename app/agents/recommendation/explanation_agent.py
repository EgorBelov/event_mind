from langchain_core.prompts import ChatPromptTemplate

from app.agents.recommendation.llm import llm
from app.agents.recommendation.state import RecommendationState


def explanation_agent(state: RecommendationState):
    ranked_event_ids = state.get("ranked_event_ids", [])
    events_by_id = {e["id"]: e for e in state["events"]}

    ranked_cards = []
    for item in ranked_event_ids:
        event_id = item.get("event_id")
        event = events_by_id.get(event_id)
        if not event:
            continue
        ranked_cards.append({
            "event_id": event_id,
            "title": event["title"],
            "description": event["description"],
            "format": event["format"],
            "city": event["city"],
            "level": event["level"],
            "date": event["date"],
            "topics": event["topics"],
            "explanation": item.get("reason", "Подобрано AI-агентом."),
            "score": f"{item.get('score', '?')}/10",
        })

    prompt = ChatPromptTemplate.from_messages([
        ("system", """
Ты ExplanationAgent.
Твоя задача — красиво и понятно объяснить пользователю рекомендации.
Пиши дружелюбно, как Telegram-бот.
Без слишком академичного стиля.
"""),
        ("user", """
Рейтинг событий:
{ranked_events}

Сформируй финальный ответ пользователю.
Формат:

🎯 Я подобрал для тебя события:

1. Название события
Почему подходит: ...
Оценка: ...

2. ...

В конце добавь короткую фразу:
"Можешь поставить 👍 или 👎, чтобы я лучше понял твои интересы."
""")
    ])

    result = llm.invoke(
        prompt.format_messages(ranked_events=ranked_event_ids)
    )

    return {
        "ranked_cards": ranked_cards,
        "final_answer": result.content,
    }
