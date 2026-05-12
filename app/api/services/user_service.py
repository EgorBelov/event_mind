from sqlalchemy.orm import Session

from app.db.models.user import User
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.topic import Topic, UserTopic
from app.api.schemas.user import UserCreate
from app.core.topics import TOPIC_TITLES
from app.recommender.user_model import (
    build_initial_topic_weights,
    dump_topic_weights,
    parse_topic_weights,
    sync_topic_weights_with_topics,
)


def _get_or_create_topic(db: Session, code: str) -> Topic:
    topic = db.query(Topic).filter(Topic.code == code).first()
    if not topic:
        topic = Topic(code=code, title=TOPIC_TITLES.get(code, code))
        db.add(topic)
        db.flush()
    return topic


def _replace_user_topics(db: Session, user: User, topic_codes: list[str]) -> None:
    db.query(UserTopic).filter(UserTopic.user_id == user.id).delete()
    db.flush()
    for code in topic_codes:
        topic = _get_or_create_topic(db, code)
        db.add(UserTopic(user_id=user.id, topic_id=topic.id))
    db.flush()


def get_user_topic_codes(user: User) -> list[str]:
    return [ut.topic.code for ut in (user.user_topics or []) if ut.topic]


def create_or_update_user(db: Session, user_data: UserCreate) -> User:
    user = db.query(User).filter(User.telegram_id == user_data.telegram_id).first()

    if user:
        user.username = user_data.username
        user.preferred_format = user_data.preferred_format
        user.city = user_data.city
        current_weights = parse_topic_weights(user.topic_weights)
        synced_weights = sync_topic_weights_with_topics(current_weights, user_data.topics)
        user.topic_weights = dump_topic_weights(synced_weights)
        _replace_user_topics(db, user, user_data.topics)
    else:
        user = User(
            telegram_id=user_data.telegram_id,
            username=user_data.username,
            preferred_format=user_data.preferred_format,
            city=user_data.city,
            topic_weights=dump_topic_weights(build_initial_topic_weights(user_data.topics)),
        )
        db.add(user)
        db.flush()
        _replace_user_topics(db, user, user_data.topics)

    db.commit()
    db.refresh(user)
    return user


def get_user_by_telegram_id(db: Session, telegram_id: int) -> User | None:
    return db.query(User).filter(User.telegram_id == telegram_id).first()


def get_user_stats(db: Session, telegram_id: int) -> dict:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"success": False, "message": "User not found"}

    interactions = db.query(Interaction).filter(Interaction.user_id == user.id).all()
    likes = sum(1 for i in interactions if i.action == "like")
    dislikes = sum(1 for i in interactions if i.action == "dislike")
    saves = sum(1 for i in interactions if i.action == "save")

    weights = parse_topic_weights(user.topic_weights)
    top_topics = [
        {"topic": t, "score": s}
        for t, s in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]

    last_interactions = (
        db.query(Interaction)
        .filter(Interaction.user_id == user.id)
        .order_by(Interaction.id.desc())
        .limit(5)
        .all()
    )

    last_actions: list[dict] = []
    if last_interactions:
        event_ids = [i.event_id for i in last_interactions]
        titles = {e.id: e.title for e in db.query(Event).filter(Event.id.in_(event_ids)).all()}
        last_actions = [
            {"event_id": i.event_id, "event_title": titles.get(i.event_id, f"event #{i.event_id}"), "action": i.action}
            for i in last_interactions
        ]

    return {
        "success": True,
        "likes_count": likes,
        "dislikes_count": dislikes,
        "saves_count": saves,
        "top_topics": top_topics,
        "last_actions": last_actions,
    }


def analyze_bio_and_update_topics(db: Session, telegram_id: int, bio_text: str) -> dict:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return {"success": False, "message": "User not found"}

    extracted = _extract_topics_from_bio(bio_text)
    if not extracted:
        return {"success": False, "message": "Не удалось извлечь темы из текста.", "extracted_topics": []}

    current_weights = parse_topic_weights(user.topic_weights)
    synced = sync_topic_weights_with_topics(current_weights, extracted)
    for t in extracted:
        synced[t] = max(synced.get(t, 3), 4)
    user.topic_weights = dump_topic_weights(synced)

    _replace_user_topics(db, user, extracted)
    db.commit()
    db.refresh(user)
    return {"success": True, "extracted_topics": extracted, "message": "Темы обновлены на основе bio."}


def _extract_topics_from_bio(bio_text: str) -> list[str]:
    from app.core.topics import ALLOWED_TOPICS
    import json as _json
    try:
        from langchain_core.prompts import ChatPromptTemplate
        from app.agents.recommendation.llm import llm

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "Ты помогаешь профилировать пользователя. На основе текста верни JSON-массив тем строго из: "
             f"{', '.join(ALLOWED_TOPICS)}. Только валидный JSON-массив."),
            ("user", "Bio: {bio}\n\nВерни JSON-массив, например: [\"ai_ml\", \"backend\"]"),
        ])
        response = llm.invoke(prompt.format_messages(bio=bio_text))
        text = response.content.strip().strip("`").removeprefix("json").strip()
        raw = _json.loads(text)
        if isinstance(raw, list):
            extracted = [t for t in raw if isinstance(t, str) and t in ALLOWED_TOPICS]
            if extracted:
                return list(dict.fromkeys(extracted))
    except Exception:
        pass
    return _keyword_topics_from_text(bio_text)


def _keyword_topics_from_text(text: str) -> list[str]:
    lowered = (text or "").lower()
    rules: dict[str, list[str]] = {
        "ai_ml": ["ai", "ml", "ии", "нейрон", "machine learning", "deep learning"],
        "data_science": ["data science", "ds", "анализ данных", "data scientist"],
        "business_analytics": ["business analyst", "бизнес-анал", "ba", "bi"],
        "backend": ["backend", "бэкенд", "fastapi", "django", "python", "java", "go"],
        "frontend": ["frontend", "фронтенд", "react", "vue", "next", "typescript"],
        "product": ["product", "продакт", "пм", "продуктовый"],
        "cybersecurity": ["security", "безопасност", "кибер", "infosec"],
        "devops": ["devops", "kubernetes", "docker", "k8s", "ci/cd", "облач"],
    }
    found: list[str] = []
    for topic, keywords in rules.items():
        if any(kw in lowered for kw in keywords):
            found.append(topic)
    return found
