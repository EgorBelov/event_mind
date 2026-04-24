from langchain_core.prompts import ChatPromptTemplate

from app.agents.recommendation.llm import llm
from app.agents.recommendation.state import RecommendationState


def explanation_agent(state: RecommendationState):
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
        prompt.format_messages(
            ranked_events=state["ranked_events"]
        )
    )

    return {
        "final_answer": result.content
    }