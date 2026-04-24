from app.agents.recommendation import recommendation_graph


user_profile = {
    "name": "Егор",
    "liked_categories": ["AI", "Python", "Startups"],
    "disliked_categories": ["Marketing"],
    "liked_events": [
        "Митап по искусственному интеллекту",
        "Python backend meetup",
        "Стартап-завтрак"
    ],
    "description": "Интересуется ИИ, backend-разработкой, стартапами и практическими IT-событиями."
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
        "description": "Конференция про рекламу, продвижение брендов и digital-маркетинг."
    },
    {
        "id": 4,
        "title": "Startup Pitch Night",
        "category": "Startups",
        "description": "Вечер презентаций стартапов, нетворкинг и инвесторы."
    }
]


if __name__ == "__main__":
    result = recommendation_graph.invoke({
        "user_profile": user_profile,
        "events": events,

        "user_analysis": "",
        "events_analysis": "",
        "ranked_events": "",
        "final_answer": "",
    })

    print(result["final_answer"])