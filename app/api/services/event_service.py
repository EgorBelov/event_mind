import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.db.models.topic import Topic, EventTopic
from app.core.topics import topic_title, slugify_code


def _get_or_create_topic(db: Session, code: str) -> Topic:
    code = slugify_code(code) or code
    topic = db.query(Topic).filter(Topic.code == code).first()
    if not topic:
        topic = Topic(code=code, title=topic_title(code))
        db.add(topic)
        db.flush()
    return topic


def _attach_event_topics(db: Session, event: Event, topic_codes: list[str]) -> None:
    for code in topic_codes:
        topic = _get_or_create_topic(db, code)
        exists = (
            db.query(EventTopic)
            .filter(EventTopic.event_id == event.id, EventTopic.topic_id == topic.id)
            .first()
        )
        if not exists:
            db.add(EventTopic(event_id=event.id, topic_id=topic.id))
    db.flush()


def get_event_topic_codes(event: Event) -> list[str]:
    return [et.topic.code for et in (event.event_topics or []) if et.topic]


def load_events_from_json(db: Session, file_path: str = "data/events.json") -> int:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл {file_path} не найден")

    with path.open("r", encoding="utf-8") as f:
        events_data = json.load(f)

    count = 0
    for item in events_data:
        if db.query(Event).filter(Event.title == item["title"]).first():
            continue

        event = Event(
            title=item["title"],
            description=item["description"],
            format=item["format"],
            city=item["city"],
            level=item["level"],
            date=item["date"],
            source_url=item.get("source_url"),
        )
        db.add(event)
        db.flush()
        _attach_event_topics(db, event, item.get("topics", []))
        count += 1

    db.commit()
    return count


def get_all_events(db: Session) -> list[Event]:
    return db.query(Event).all()
