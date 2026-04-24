# python app/agents/test_recommendation_agent.py
from dotenv import load_dotenv
from recommendation_agent import recommendation_agent

load_dotenv()


user_profile = {
    "name": "Егор",
    "liked_categories": ["AI", "Startups", "Python"],
    "disliked_categories": ["Marketing"],
    "liked_events": [
        "Митап по искусственному интеллекту",
        "Python backend meetup",
        "Стартап-завтрак для молодых предпринимателей"
    ],
    "description": "Интересуется ИИ, разработкой, стартапами и практическими IT-событиями."
}


events = [
    {
        "id": 1,
        "title": "AI Meetup: нейросети в бизнесе",
        "category": "AI",
        "description": "Встреча про применение ИИ в продуктах и аналитике."
    },
    {
        "id": 2,
        "title": "Python Backend Day",
        "category": "Python",
        "description": "Практический митап по FastAPI, PostgreSQL и микросервисам."
    },
    {
        "id": 3,
        "title": "Digital Marketing Conference",
        "category": "Marketing",
        "description": "Конференция про продвижение брендов и рекламу."
    },
    {
        "id": 4,
        "title": "Startup Pitch Night",
        "category": "Startups",
        "description": "Вечер презентаций стартапов, нетворкинг и инвесторы."
    }
]


if __name__ == "__main__":
    result = recommendation_agent.invoke({
        "user_profile": user_profile,
        "events": events,
        "analyzed_user": "",
        "filtered_events": [],
        "ranked_events": "",
        "final_answer": ""
    })

    print(result["final_answer"])