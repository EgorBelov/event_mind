"""Tests for app/recommender/scoring.py"""
import json
import pytest

from app.recommender.scoring import score_event_for_user


class MockTopic:
    def __init__(self, code):
        self.code = code


class MockUserTopic:
    def __init__(self, code):
        self.topic = MockTopic(code)


class MockEventTopic:
    def __init__(self, code):
        self.topic = MockTopic(code)


class MockUser:
    def __init__(self, topics, preferred_format, city, topic_weights_dict=None):
        self.user_topics = [MockUserTopic(t) for t in topics]
        self.preferred_format = preferred_format
        self.city = city
        self.topic_weights = json.dumps(topic_weights_dict or {})


class MockEvent:
    def __init__(self, topics, format, city):
        self.event_topics = [MockEventTopic(t) for t in topics]
        self.format = format
        self.city = city


def test_score_matching_topic_and_format_and_city():
    user = MockUser(
        topics=["ai_ml", "backend"],
        preferred_format="online",
        city="moscow",
        topic_weights_dict={"ai_ml": 5, "backend": 3},
    )
    event = MockEvent(topics=["ai_ml"], format="online", city="moscow")

    score = score_event_for_user(user, event)
    # topic_weight(ai_ml)=5 + common_topic_bonus=2 + format_match=3 + city_match=2 = 12
    assert score == 12


def test_score_no_overlap():
    user = MockUser(
        topics=["ai_ml"],
        preferred_format="online",
        city="moscow",
        topic_weights_dict={},
    )
    event = MockEvent(topics=["backend"], format="offline", city="spb")

    score = score_event_for_user(user, event)
    assert score == 0


def test_score_any_city():
    user = MockUser(
        topics=["ai_ml"],
        preferred_format="online",
        city="any",
        topic_weights_dict={"ai_ml": 3},
    )
    event = MockEvent(topics=["ai_ml"], format="online", city="moscow")

    score = score_event_for_user(user, event)
    # topic_weight=3 + common_bonus=2 + format=3 + city_any=1 = 9
    assert score == 9


def test_score_event_city_any():
    user = MockUser(
        topics=[],
        preferred_format="offline",
        city="moscow",
        topic_weights_dict={},
    )
    event = MockEvent(topics=[], format="offline", city="any")

    score = score_event_for_user(user, event)
    # format_match=3 + city_event_any=1 = 4
    assert score == 4
