import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.agents.event_normalization import event_normalizer_agent


def load_events_from_json(db: Session, file_path: str = "data/events.json") -> int:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл {file_path} не найден")

    with path.open("r", encoding="utf-8") as f:
        events_data = json.load(f)

    count = 0

    for item in events_data:
        existing = db.query(Event).filter(Event.title == item["title"]).first()
        if existing:
            continue

        event = Event(
            title=item["title"],
            description=item["description"],
            format=item["format"],
            city=item["city"],
            level=item["level"],
            date=item["date"],
            topics=",".join(item["topics"]),
        )
        db.add(event)
        count += 1

    db.commit()
    return count


def load_raw_events_with_ai(db: Session, file_path: str = "data/events_raw.json") -> int:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл {file_path} не найден")

    with path.open("r", encoding="utf-8") as f:
        raw_events = json.load(f)

    count = 0

    for raw_event in raw_events:
        result = event_normalizer_agent({
            "raw_event": raw_event,
            "normalized_event": {},
        })

        item = result["normalized_event"]

        existing = db.query(Event).filter(Event.title == item["title"]).first()
        if existing:
            continue

        event = Event(
            title=item["title"],
            description=item["description"],
            format=item["format"],
            city=item["city"],
            level=item["level"],
            date=item["date"],
            topics=",".join(item["topics"]),
            source_url=item.get("source_url"),
        )

        db.add(event)
        count += 1

    db.commit()
    return count


def get_all_events(db: Session) -> list[Event]:
    return db.query(Event).all()