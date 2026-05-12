"""Tests for app/recommender/user_model.py"""
import json
import pytest

from app.recommender.user_model import (
    build_initial_topic_weights,
    apply_feedback_to_weights,
    parse_topics,
    dump_topic_weights,
)


def test_build_initial_topic_weights():
    topics = ["ai_ml", "backend", "product"]
    weights = build_initial_topic_weights(topics)
    assert set(weights.keys()) == set(topics)
    for val in weights.values():
        assert val == 3  # DEFAULT_TOPIC_WEIGHT


def test_apply_feedback_like():
    weights = {"ai_ml": 3, "backend": 3}
    updated = apply_feedback_to_weights(weights, ["ai_ml"], "like")
    assert updated["ai_ml"] == 6   # 3 + LIKE_BONUS(3)
    assert updated["backend"] == 3  # unchanged


def test_apply_feedback_dislike():
    weights = {"ai_ml": 3, "backend": 3}
    updated = apply_feedback_to_weights(weights, ["ai_ml"], "dislike")
    assert updated["ai_ml"] == 1   # 3 - DISLIKE_PENALTY(2)
    assert updated["backend"] == 3  # unchanged


def test_apply_feedback_save():
    weights = {"ai_ml": 3}
    updated = apply_feedback_to_weights(weights, ["ai_ml"], "save")
    assert updated["ai_ml"] == 4   # 3 + SAVE_BONUS(1)


def test_parse_topics_string():
    result = parse_topics("ai_ml,backend,product")
    assert result == {"ai_ml", "backend", "product"}


def test_parse_topics_string_empty():
    assert parse_topics("") == set()
    assert parse_topics(None) == set()


def test_parse_topics_list():
    result = parse_topics(["ai_ml", "backend", "product"])
    assert result == {"ai_ml", "backend", "product"}


def test_parse_topics_list_empty():
    assert parse_topics([]) == set()
