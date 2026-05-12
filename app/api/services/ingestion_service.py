import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models.raw_event import RawEvent
from app.db.models.event import Event
from app.api.services.event_service import _attach_event_topics


def load_raw_events(db: Session, file_path: str = "data/events_raw.json") -> dict:
    """Load data/events_raw.json into the raw_events table."""
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл {file_path} не найден")

    with path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    loaded = 0
    skipped = 0

    for item in raw_data:
        title = item.get("title", "")
        existing = db.query(RawEvent).filter(RawEvent.title == title).first()
        if existing:
            skipped += 1
            continue

        raw_event = RawEvent(
            title=title,
            raw_description=item.get("raw_description", ""),
            source_url=item.get("source_url"),
            status="raw",
        )
        db.add(raw_event)
        loaded += 1

    db.commit()
    return {"loaded": loaded, "skipped": skipped}


def normalize_raw_events(db: Session) -> dict:
    """Run all pending raw events through the EventNormalizerAgent."""
    raw_events = db.query(RawEvent).filter(RawEvent.status == "raw").all()
    raw_ids = [r.id for r in raw_events]
    normalized, non_it, failed = _normalize_by_ids(db, raw_ids)
    return {"normalized": normalized, "non_it": non_it, "failed": failed}


def load_habr_events(db: Session, limit: int = 20) -> dict:
    """Fetch events from Habr, save to raw_events, normalize via agent, insert into events."""
    from app.ingestion.sources.habr import fetch_habr_events

    items = fetch_habr_events(limit=limit)
    loaded = 0
    skipped = 0
    pending_ids: list[int] = []

    for item in items:
        title = item.get("title", "")
        existing = db.query(RawEvent).filter(RawEvent.title == title).first()
        if existing:
            skipped += 1
            if existing.status == "raw":
                pending_ids.append(existing.id)
            continue

        raw_event = RawEvent(
            title=title,
            raw_description=item.get("raw_description", ""),
            source_url=item.get("source_url"),
            status="raw",
        )
        db.add(raw_event)
        db.flush()
        pending_ids.append(raw_event.id)
        loaded += 1

    db.commit()

    normalized, non_it, failed = _normalize_by_ids(db, pending_ids)

    return {
        "source": "habr",
        "fetched": loaded + skipped,
        "new": loaded,
        "skipped": skipped,
        "normalized": normalized,
        "non_it": non_it,
        "failed": failed,
    }


def _normalize_single(db: Session, raw: RawEvent) -> str:
    """Normalize one raw event. Returns final status: 'normalized' | 'non_it' | 'failed'."""
    from app.agents.event_normalization.agent import event_normalizer_agent

    try:
        result = event_normalizer_agent({
            "raw_event": {
                "title": raw.title,
                "raw_description": raw.raw_description,
                "source_url": raw.source_url,
            },
            "normalized_event": {},
        })

        item = result["normalized_event"]
        topics = item.get("topics", [])

        if not topics:
            raw.status = "non_it"
            return "non_it"

        existing = db.query(Event).filter(Event.title == item["title"]).first()
        if not existing:
            import json as _json
            tech_stack = item.get("tech_stack", [])
            event = Event(
                title=item["title"],
                description=item["description"],
                format=item["format"],
                city=item["city"],
                level=item["level"],
                date=item.get("date", ""),
                event_type=item.get("event_type"),
                target_audience=item.get("target_audience"),
                source_url=item.get("source_url") or raw.source_url,
                tech_stack=_json.dumps(tech_stack, ensure_ascii=False) if tech_stack else None,
                seniority=item.get("seniority"),
                quality_score=item.get("quality_score"),
                hype_score=item.get("hype_score"),
            )
            db.add(event)
            db.flush()
            _attach_event_topics(db, event, topics)

        raw.status = "normalized"
        return "normalized"

    except Exception as e:
        raw.status = "failed"
        raw.error = str(e)
        return "failed"


def _normalize_by_ids(db: Session, raw_ids: list[int]) -> tuple[int, int, int]:
    """Run specific raw_event rows through the normalization agent.

    Returns (normalized, non_it, failed) counts.
    """
    if not raw_ids:
        return 0, 0, 0

    raw_events = db.query(RawEvent).filter(RawEvent.id.in_(raw_ids)).all()
    normalized = non_it = failed = 0

    for raw in raw_events:
        status = _normalize_single(db, raw)
        if status == "normalized":
            normalized += 1
        elif status == "non_it":
            non_it += 1
        else:
            failed += 1

    db.commit()
    return normalized, non_it, failed


def get_ingestion_status(db: Session) -> dict:
    """Return counts of raw events by status."""
    total = db.query(RawEvent).count()
    return {
        "total": total,
        "raw": db.query(RawEvent).filter(RawEvent.status == "raw").count(),
        "normalized": db.query(RawEvent).filter(RawEvent.status == "normalized").count(),
        "non_it": db.query(RawEvent).filter(RawEvent.status == "non_it").count(),
        "failed": db.query(RawEvent).filter(RawEvent.status == "failed").count(),
    }
