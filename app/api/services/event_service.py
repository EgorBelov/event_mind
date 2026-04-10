import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models.event import Event


def load_events_from_json(db: Session, file_path: str = "data/events.json") -> int:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл {file_path} не найден")

    with path.open("r", encoding="utf-8") as f:
        events_data = json.load(f)

    count = 0

    for item in events_data:
        existing = (
            db.query(Event)
            .filter(
                Event.title == item["title"],
                Event.date == item["date"],
                Event.city == item["city"],
                Event.format == item["format"],
            )
            .first()
        )
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


def get_all_events(db: Session) -> list[Event]:
    return db.query(Event).all()
