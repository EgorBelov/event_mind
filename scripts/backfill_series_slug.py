"""Backfill events.series_slug для уже существующих записей.

Запуск:
    .venv/bin/python -m scripts.backfill_series_slug

Идемпотентно: обновляет только события, у которых series_slug пустой.
Безопасно гонять повторно (например, после правки compute_series_slug).
"""
from __future__ import annotations

from app.db.models.event import Event
from app.db.session import SessionLocal
from app.recommender.series import compute_series_slug


def main() -> None:
    db = SessionLocal()
    try:
        events = db.query(Event).filter(Event.series_slug.is_(None)).all()
        updated = skipped = 0
        for ev in events:
            slug = compute_series_slug(ev.title, ev.city)
            if slug:
                ev.series_slug = slug
                updated += 1
            else:
                skipped += 1
        db.commit()
        print(f"[backfill:series] total={len(events)} updated={updated} skipped={skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
