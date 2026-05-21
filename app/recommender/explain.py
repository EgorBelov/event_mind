from app.recommender.user_model import parse_topic_weights
from app.recommender.scoring import _get_user_topic_codes, _get_event_topic_codes
from app.core.topics import topic_title, format_label


def explain_event_for_user(user, event, db=None) -> str:
    """Вернуть человекочитаемое объяснение (под Telegram)."""
    result = explain_event_detailed(user, event, db=db)
    return result["text"]


def explain_event_detailed(
    user,
    event,
    db=None,
    *,
    precomputed_breakdown: dict[str, float] | None = None,
) -> dict:
    """Вернуть структурированное объяснение: текст + детали.

    Ключи:
        text (str): человекочитаемое объяснение.
        topic_match (list[str]): совпавшие коды тем.
        format_match (bool): совпадение формата.
        city_match (bool): совпадение города.
        semantic_similarity (float | None): cosine-сходство, если посчитано.
        history_signals (list[str]): причины из истории взаимодействий.
    """
    reasons: list[str] = []
    details: dict = {
        "topic_match": [],
        "format_match": False,
        "city_match": False,
        "semantic_similarity": None,
        "history_signals": [],
    }

    user_topics = _get_user_topic_codes(user)
    event_topics = _get_event_topic_codes(event)
    topic_weights = parse_topic_weights(user.topic_weights)

    common_topics = list(user_topics.intersection(event_topics))
    details["topic_match"] = common_topics
    if common_topics:
        names = [topic_title(t) for t in common_topics]
        reasons.append(f"темы: {', '.join(names)}")

    weighted = [t for t in event_topics if topic_weights.get(t, 0) > 3]
    if weighted:
        names = [topic_title(t) for t in weighted]
        reasons.append(f"высокий интерес: {', '.join(names)}")

    if user.preferred_format and user.preferred_format == event.format:
        details["format_match"] = True
        reasons.append(f"формат ({format_label(event.format)})")
    elif getattr(user, "preferred_format", None) == "any":
        reasons.append("любой формат")

    if user.city and user.city == event.city:
        details["city_match"] = True
        reasons.append("совпадает город")
    elif user.city == "any" or event.city == "any":
        reasons.append("нет ограничения по городу")

    # Семантическое сходство (best-effort)
    try:
        from app.recommender.embeddings import (
            get_or_build_user_embedding,
            get_or_build_event_embedding,
            cosine_similarity,
        )
        user_emb = get_or_build_user_embedding(user)
        event_emb = get_or_build_event_embedding(event)
        sim = round(cosine_similarity(user_emb, event_emb), 3)
        details["semantic_similarity"] = sim
        if sim >= 0.5:
            reasons.append(f"семантически близко (сходство {sim:.2f})")
    except Exception:
        pass

    if db is not None:
        try:
            history = _explain_from_interactions(user, event, db)
            details["history_signals"] = history
            reasons.extend(history)
        except Exception:
            pass

    # Bayesian-сигнал: если у пользователя накопилась статистика по теме
    # и posterior mean > prior (0.5) — добавляем как признак.
    if db is not None and getattr(user, "id", None) is not None:
        try:
            from app.recommender.bayesian import load_user_stats, posterior_mean, PRIOR_ALPHA, PRIOR_BETA
            stats = load_user_stats(db, user.id)
            if stats:
                pm = posterior_mean(stats, event_topics)
                details["bayesian_posterior"] = round(pm, 3)
                if pm > PRIOR_ALPHA / (PRIOR_ALPHA + PRIOR_BETA) + 0.1:
                    reasons.append(f"подтверждено историей feedback'а (p≈{pm:.2f})")
        except Exception:
            pass

    # Counterfactual: какой компонент сильнее всего повлиял?
    # Считаем breakdown и сравниваем с «если бы этого компонента не было».
    try:
        if precomputed_breakdown is not None:
            breakdown = precomputed_breakdown
        else:
            from app.recommender.hybrid import compute_score_breakdown
            breakdown = compute_score_breakdown(user, event, db=db)
        total = sum(breakdown.values())
        details["score_breakdown"] = {k: round(v, 3) for k, v in breakdown.items()}
        if total > 0:
            ranked = sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True)
            top_component, top_value = ranked[0]
            second_value = ranked[1][1] if len(ranked) > 1 else 0.0
            # Если ведущий компонент даёт >50% разрыва — counterfactual
            if top_value > 0 and (top_value - second_value) / max(total, 1e-9) > 0.3:
                labels = {
                    "rule": "правил профиля",
                    "cosine": "семантической близости",
                    "bayesian": "истории feedback'а",
                    "quality": "высокого quality_score",
                    "hype": "актуальности темы",
                    "freshness": "близости даты",
                    "skill_gap": "соответствия твоим карьерным целям",
                    "bandit": "exploration-сигнала bandit'а",
                    "gnn": "collaborative-сигнала",
                }
                details["counterfactual"] = (
                    f"Без {labels.get(top_component, top_component)} это событие потеряло бы "
                    f"~{top_value / total * 100:.0f}% веса и опустилось бы ниже в списке."
                )
                reasons.append(details["counterfactual"])
    except Exception:
        pass

    text = "Почему рекомендовано: " + "; ".join(reasons) if reasons else "Подобрано по базовому совпадению профиля."
    details["text"] = text
    return details


def _explain_from_interactions(user, event, db) -> list[str]:
    from app.db.models.interaction import Interaction
    from app.db.models.event import Event

    reasons: list[str] = []
    event_topics = _get_event_topic_codes(event)

    interactions = db.query(Interaction).filter(Interaction.user_id == user.id).all()
    if not interactions:
        return reasons

    liked_ids = {i.event_id for i in interactions if i.action == "like"}
    saved_ids = {i.event_id for i in interactions if i.action == "save"}

    liked_topics: set[str] = set()
    saved_topics: set[str] = set()
    liked_formats: dict[str, int] = {}

    related_ids = list(liked_ids | saved_ids)
    if related_ids:
        for e in db.query(Event).filter(Event.id.in_(related_ids)).all():
            topics = _get_event_topic_codes(e)
            if e.id in liked_ids:
                liked_topics.update(topics)
                liked_formats[e.format] = liked_formats.get(e.format, 0) + 1
            if e.id in saved_ids:
                saved_topics.update(topics)

    if saved_match := saved_topics.intersection(event_topics):
        names = [topic_title(t) for t in saved_match]
        reasons.append(f"сохранял похожие темы: {', '.join(names)}")

    if liked_match := liked_topics.intersection(event_topics) - saved_match:
        names = [topic_title(t) for t in liked_match]
        reasons.append(f"лайкал похожие темы: {', '.join(names)}")

    if liked_formats:
        top_fmt = max(liked_formats, key=liked_formats.get)
        if event.format == top_fmt and liked_formats[top_fmt] >= 2:
            reasons.append(f"любит {format_label(event.format)}-формат")

    return reasons
