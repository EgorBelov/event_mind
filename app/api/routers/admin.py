from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.db.models.user import User
from app.db.models.event import Event
from app.db.models.raw_event import RawEvent
from app.db.models.interaction import Interaction

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/", response_class=HTMLResponse)
def admin_dashboard(db: Session = Depends(get_db)):
    users_count = db.query(User).count()
    events_count = db.query(Event).count()
    subscribed_count = db.query(User).filter(User.is_subscribed == 1).count()
    interactions_count = db.query(Interaction).count()

    try:
        raw_count = db.query(RawEvent).filter(RawEvent.status == "raw").count()
        normalized_count = (
            db.query(RawEvent).filter(RawEvent.status == "normalized").count()
        )
        failed_count = db.query(RawEvent).filter(RawEvent.status == "failed").count()
    except Exception:
        raw_count = normalized_count = failed_count = 0

    latest_events = (
        db.query(Event).order_by(Event.id.desc()).limit(10).all()
    )

    events_rows = "".join(
        f"<tr><td>{e.id}</td><td>{_escape(e.title)}</td><td>{_escape(e.format)}</td>"
        f"<td>{_escape(e.city)}</td><td>{_escape(e.date)}</td></tr>"
        for e in latest_events
    )

    # HTML рендерится статикой, без шаблонизатора
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>EventMind Admin</title>
<style>body{{font-family:sans-serif;padding:20px;background:#f5f5f5}}
.card{{background:white;padding:16px;border-radius:8px;margin:8px;display:inline-block;min-width:120px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.2)}}
.card h2{{margin:0;font-size:32px;color:#333}}
.card p{{margin:4px 0;color:#666;font-size:13px}}
table{{width:100%;background:white;border-collapse:collapse;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.2)}}
th,td{{padding:10px 14px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#f9f9f9;font-weight:600}}</style></head>
<body>
<h1>EventMind Admin</h1>
<div>
  <div class="card"><h2>{users_count}</h2><p>Пользователей</p></div>
  <div class="card"><h2>{events_count}</h2><p>Событий</p></div>
  <div class="card"><h2>{subscribed_count}</h2><p>Подписчиков</p></div>
  <div class="card"><h2>{interactions_count}</h2><p>Взаимодействий</p></div>
  <div class="card"><h2>{raw_count}</h2><p>Raw events</p></div>
  <div class="card"><h2>{normalized_count}</h2><p>Нормализовано</p></div>
  <div class="card"><h2>{failed_count}</h2><p>Ошибок</p></div>
</div>
<h2 style="margin-top:24px">Последние события</h2>
<table><thead><tr><th>ID</th><th>Название</th><th>Формат</th><th>Город</th><th>Дата</th></tr></thead>
<tbody>{events_rows}</tbody></table>
</body></html>"""
    return HTMLResponse(html)


def _escape(value) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
