from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.user import User
from app.recommender.user_model import parse_topic_weights
from app.recommender.scoring import _get_event_topic_codes

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/topics")
def analytics_topics(db: Session = Depends(get_db)):
    """Most liked topics, most saved topics, and topic-weight distribution."""
    interactions = db.query(Interaction).all()
    event_topics_map: dict[int, list[str]] = {}
    if interactions:
        event_ids = list({i.event_id for i in interactions})
        events = db.query(Event).filter(Event.id.in_(event_ids)).all()
        for e in events:
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

    # Topic weights distribution (averaged across users)
    weight_totals: dict[str, float] = {}
    weight_counts: dict[str, int] = {}
    users = db.query(User).all()
    for u in users:
        weights = parse_topic_weights(u.topic_weights)
        for topic, value in weights.items():
            weight_totals[topic] = weight_totals.get(topic, 0) + float(value)
            weight_counts[topic] = weight_counts.get(topic, 0) + 1

    avg_weights = {
        t: round(weight_totals[t] / weight_counts[t], 2)
        for t in weight_totals
    }

    return {
        "most_liked_topics": liked_counter.most_common(10),
        "most_saved_topics": saved_counter.most_common(10),
        "most_disliked_topics": disliked_counter.most_common(10),
        "avg_topic_weights": avg_weights,
    }


@router.get("/interactions")
def analytics_interactions(db: Session = Depends(get_db)):
    """Total interactions by action and top events by total interactions."""
    interactions = db.query(Interaction).all()

    by_action: Counter[str] = Counter()
    by_event: Counter[int] = Counter()

    for i in interactions:
        by_action[i.action] += 1
        by_event[i.event_id] += 1

    top_event_ids = [eid for eid, _ in by_event.most_common(10)]
    top_events_data = []
    if top_event_ids:
        events = db.query(Event).filter(Event.id.in_(top_event_ids)).all()
        events_by_id = {e.id: e for e in events}
        for eid in top_event_ids:
            e = events_by_id.get(eid)
            if not e:
                continue
            top_events_data.append({
                "event_id": e.id,
                "title": e.title,
                "interactions": by_event[eid],
            })

    return {
        "total": sum(by_action.values()),
        "by_action": dict(by_action),
        "top_events": top_events_data,
    }
