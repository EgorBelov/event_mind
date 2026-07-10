from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.utils import utcnow_naive
from app.db.dependencies import get_db
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.user import User
from app.recommender.scoring import _get_event_topic_codes
from app.recommender.user_model import parse_topic_weights

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/topics")
def analytics_topics(db: Session = Depends(get_db)):
    """Самые лайкнутые / сохранённые темы и распределение весов тем по юзерам."""
    interactions = db.query(Interaction).all()
    event_topics_map: dict[int, list[str]] = {}
    if interactions:
        event_ids = list({i.event_id for i in interactions})
        for e in db.query(Event).filter(Event.id.in_(event_ids)).all():
            event_topics_map[e.id] = list(_get_event_topic_codes(e))

    liked_counter: Counter[str] = Counter()
    saved_counter: Counter[str] = Counter()
    disliked_counter: Counter[str] = Counter()

    for i in interactions:
        topics = event_topics_map.get(i.event_id, [])
        if i.action == "like":
            liked_counter.update(topics)
        elif i.action == "save":
            saved_counter.update(topics)
        elif i.action == "dislike":
            disliked_counter.update(topics)

    weight_totals: dict[str, float] = {}
    weight_counts: dict[str, int] = {}
    for u in db.query(User).all():
        for topic, value in parse_topic_weights(u.topic_weights).items():
            weight_totals[topic] = weight_totals.get(topic, 0) + float(value)
            weight_counts[topic] = weight_counts.get(topic, 0) + 1

    avg_weights = {t: round(weight_totals[t] / weight_counts[t], 2) for t in weight_totals}

    return {
        "most_liked_topics": liked_counter.most_common(10),
        "most_saved_topics": saved_counter.most_common(10),
        "most_disliked_topics": disliked_counter.most_common(10),
        "avg_topic_weights": avg_weights,
    }


@router.get("/interactions")
def analytics_interactions(db: Session = Depends(get_db)):
    """Сумма интеракций по типам действий + топ событий по числу интеракций."""
    interactions = db.query(Interaction).all()

    by_action: Counter[str] = Counter()
    by_event: Counter[int] = Counter()
    for i in interactions:
        by_action[i.action] += 1
        by_event[i.event_id] += 1

    top_event_ids = [eid for eid, _ in by_event.most_common(10)]
    top_events_data = []
    if top_event_ids:
        events_by_id = {e.id: e for e in db.query(Event).filter(Event.id.in_(top_event_ids)).all()}
        for eid in top_event_ids:
            e = events_by_id.get(eid)
            if e:
                top_events_data.append({"event_id": e.id, "title": e.title, "interactions": by_event[eid]})

    return {"total": sum(by_action.values()), "by_action": dict(by_action), "top_events": top_events_data}


@router.get("/trending")
def analytics_trending(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Горячие события и темы по свежим сигналам взаимодействий.

    Формула score: likes×3 + saves×2 + dislikes×0 (с учётом свежести).
    """
    cutoff = utcnow_naive() - timedelta(days=days)

    # Только свежие интеракции (created_at >= cutoff)
    interactions = (
        db.query(Interaction)
        .filter(Interaction.created_at >= cutoff)
        .all()
    )

    # Fallback: если за окно ничего не нашлось — берём все интеракции
    if not interactions:
        interactions = db.query(Interaction).all()

    event_score: dict[int, float] = {}
    topic_counter: Counter[str] = Counter()

    event_ids_seen = {i.event_id for i in interactions}
    events_map = {e.id: e for e in db.query(Event).filter(Event.id.in_(event_ids_seen)).all()}

    for i in interactions:
        weight = 3.0 if i.action == "like" else (2.0 if i.action == "save" else 0.0)
        event_score[i.event_id] = event_score.get(i.event_id, 0.0) + weight

        event = events_map.get(i.event_id)
        if event and i.action in ("like", "save"):
            topic_counter.update(_get_event_topic_codes(event))

    # Топ событий по score
    top_ids = sorted(event_score, key=event_score.get, reverse=True)[:limit]
    hot_events = []
    for eid in top_ids:
        e = events_map.get(eid)
        if e:
            hot_events.append({
                "event_id": e.id,
                "title": e.title,
                "format": e.format,
                "city": e.city,
                "date": e.date,
                "topics": list(_get_event_topic_codes(e)),
                "hype_score": getattr(e, "hype_score", None),
                "trending_score": round(event_score[eid], 1),
            })

    return {
        "period_days": days,
        "hot_events": hot_events,
        "trending_topics": topic_counter.most_common(8),
    }
