"""Single source of truth for topic constants across the project."""

TOPIC_TITLES: dict[str, str] = {
    "ai_ml": "AI / ML",
    "data_science": "Data Science",
    "business_analytics": "Бизнес-аналитика",
    "backend": "Backend",
    "frontend": "Frontend",
    "product": "Product",
    "cybersecurity": "Кибербезопасность",
    "devops": "DevOps",
}

ALLOWED_TOPICS: list[str] = list(TOPIC_TITLES.keys())

FORMAT_LABELS: dict[str, str] = {
    "online": "online",
    "offline": "offline",
    "hybrid": "hybrid",
    "unknown": "unknown",
}

CITY_LABELS: dict[str, str] = {
    "moscow": "Москва",
    "spb": "Санкт-Петербург",
    "kazan": "Казань",
    "ekb": "Екатеринбург",
    "any": "Любой",
    "unknown": "Не указан",
}

LEVEL_LABELS: dict[str, str] = {
    "beginner": "Начинающий",
    "middle": "Middle",
    "advanced": "Advanced",
    "unknown": "Любой",
}
