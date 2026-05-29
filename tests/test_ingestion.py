"""Offline-тесты RSS-источника и сервиса ingestion.

Сеть не задействуется: `feedparser.parse` подменяется так, чтобы парсить
локальные XML-строки реальным feedparser'ом, а LLM-нормализация
(`_normalize_by_ids`) заглушается.
"""
import json

import feedparser
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.services import ingestion_service
from app.db.base import Base
from app.db.models.event import Event
from app.db.models.raw_event import RawEvent
from app.ingestion.sources.rss import fetch_rss_events


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _rss(*items: str) -> str:
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>Test Feed</title>'
        f"{body}</channel></rss>"
    )


def _item(title: str, link: str, desc: str = "", pub: str = "") -> str:
    parts = [f"<title>{title}</title>"] if title else []
    if link:
        parts.append(f"<link>{link}</link>")
    if desc:
        parts.append(f"<description>{desc}</description>")
    if pub:
        parts.append(f"<pubDate>{pub}</pubDate>")
    return "<item>" + "".join(parts) + "</item>"


@pytest.fixture
def fake_feeds(monkeypatch):
    """url -> XML; feedparser парсит строку реально, без сети."""
    mapping: dict[str, str] = {}
    real_parse = feedparser.parse  # до подмены, иначе рекурсия

    def fake_parse(url, **kwargs):
        return real_parse(mapping.get(url, "<broken><not-xml"))

    monkeypatch.setattr(
        "app.ingestion.sources.rss.feedparser.parse", fake_parse
    )
    return mapping


# ── fetch_rss_events ──────────────────────────────────────────────────────────

def test_fetch_rss_basic_shape(fake_feeds):
    fake_feeds["http://a/feed"] = _rss(
        _item("Python Meetup", "https://ev/1", "Митап по Python",
              "Mon, 18 May 2026 10:00:00 GMT"),
        _item("Go Conf", "https://ev/2", "Go conference"),
    )

    res = fetch_rss_events(["http://a/feed"])

    assert len(res) == 2
    first = res[0]
    assert first["title"] == "Python Meetup"
    assert first["source_url"] == "https://ev/1"
    assert "Митап по Python" in first["raw_description"]
    assert "2026" in first["raw_description"]  # pubDate попал в описание


def test_fetch_rss_dedup_link_across_feeds(fake_feeds):
    fake_feeds["http://a"] = _rss(_item("E1", "https://ev/1"))
    fake_feeds["http://b"] = _rss(
        _item("E1 dup", "https://ev/1"),  # тот же link
        _item("E3", "https://ev/3"),
    )

    res = fetch_rss_events(["http://a", "http://b"])

    links = sorted(r["source_url"] for r in res)
    assert links == ["https://ev/1", "https://ev/3"]


def test_fetch_rss_limit_per_feed(fake_feeds):
    fake_feeds["http://a"] = _rss(
        _item("A", "https://ev/a"),
        _item("B", "https://ev/b"),
        _item("C", "https://ev/c"),
    )

    res = fetch_rss_events(["http://a"], limit_per_feed=2)

    assert len(res) == 2


def test_fetch_rss_skips_entry_without_title_or_link(fake_feeds):
    fake_feeds["http://a"] = _rss(
        _item("", "https://ev/notitle"),       # нет title
        _item("No link", ""),                   # нет link
        _item("Good", "https://ev/good"),
    )

    res = fetch_rss_events(["http://a"])

    assert [r["title"] for r in res] == ["Good"]


def test_fetch_rss_broken_feed_skipped_others_survive(fake_feeds):
    fake_feeds["http://broken"] = "totally not xml <<<"
    fake_feeds["http://ok"] = _rss(_item("Alive", "https://ev/alive"))

    res = fetch_rss_events(["http://broken", "http://ok"])

    assert [r["title"] for r in res] == ["Alive"]


def test_fetch_rss_parse_exception_does_not_crash(monkeypatch):
    def boom(url, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("app.ingestion.sources.rss.feedparser.parse", boom)

    assert fetch_rss_events(["http://x"]) == []


def test_fetch_rss_ignores_empty_url_entries(fake_feeds):
    fake_feeds["http://a"] = _rss(_item("Solo", "https://ev/solo"))

    res = fetch_rss_events(["", "   ", "http://a"])

    assert [r["title"] for r in res] == ["Solo"]


# ── load_rss_events ───────────────────────────────────────────────────────────

@pytest.fixture
def stub_normalize(monkeypatch):
    """Заглушка LLM-нормализации: считает, сколько id пришло."""
    monkeypatch.setattr(
        ingestion_service,
        "_normalize_by_ids",
        lambda db, ids: (len(ids), 0, 0),
    )


def test_load_rss_empty_feeds_returns_empty(db):
    res = ingestion_service.load_rss_events(db, feed_urls=[])

    assert res["feeds"] == 0
    assert res["new"] == 0
    assert res["normalized"] == 0
    assert db.query(RawEvent).count() == 0


def test_load_rss_creates_raw_events(db, monkeypatch, stub_normalize):
    monkeypatch.setattr(
        "app.ingestion.sources.rss.fetch_rss_events",
        lambda urls, limit_per_feed=20: [
            {"title": "Ev A", "raw_description": "d", "source_url": "u1"},
            {"title": "Ev B", "raw_description": "d", "source_url": "u2"},
        ],
    )

    res = ingestion_service.load_rss_events(db, feed_urls=["http://x"])

    assert res["feeds"] == 1
    assert res["new"] == 2
    assert res["skipped"] == 0
    assert res["normalized"] == 2  # обе строки ушли в нормализацию
    assert db.query(RawEvent).count() == 2


def test_load_rss_dedup_by_title_skips_existing(db, monkeypatch, stub_normalize):
    db.add(RawEvent(title="Dup", raw_description="x", status="normalized"))
    db.commit()

    monkeypatch.setattr(
        "app.ingestion.sources.rss.fetch_rss_events",
        lambda urls, limit_per_feed=20: [
            {"title": "Dup", "raw_description": "d", "source_url": "u1"},
            {"title": "Fresh", "raw_description": "d", "source_url": "u2"},
        ],
    )

    res = ingestion_service.load_rss_events(db, feed_urls=["http://x"])

    assert res["new"] == 1
    assert res["skipped"] == 1
    # уже normalized — повторно в нормализацию не уходит, только Fresh
    assert res["normalized"] == 1
    assert db.query(RawEvent).count() == 2


def test_load_rss_requeues_existing_raw(db, monkeypatch, stub_normalize):
    db.add(RawEvent(title="Pending", raw_description="x", status="raw"))
    db.commit()

    monkeypatch.setattr(
        "app.ingestion.sources.rss.fetch_rss_events",
        lambda urls, limit_per_feed=20: [
            {"title": "Pending", "raw_description": "d", "source_url": "u1"},
            {"title": "Fresh", "raw_description": "d", "source_url": "u2"},
        ],
    )

    res = ingestion_service.load_rss_events(db, feed_urls=["http://x"])

    assert res["new"] == 1
    assert res["skipped"] == 1
    # «висящая» raw-строка + новая Fresh → обе нормализуются
    assert res["normalized"] == 2


# ── embedding при нормализации ────────────────────────────────────────────────

@pytest.fixture
def fake_normalizer(monkeypatch):
    """Подменяет LLM-агента нормализации детерминированным IT-событием."""
    def fake_agent(state):
        return {
            "normalized_event": {
                "title": "AI Conf",
                "description": "About AI",
                "format": "online",
                "city": "any",
                "level": "beginner",
                "date": "2026-06-01",
                "topics": ["ai_ml"],
            }
        }

    monkeypatch.setattr(
        "app.agents.event_normalization.agent.event_normalizer_agent",
        fake_agent,
    )


def test_normalize_persists_event_embedding(db, monkeypatch, fake_normalizer):
    # модель не грузим — стаб вектора
    monkeypatch.setattr(
        "app.recommender.embeddings.build_event_embedding",
        lambda event: [0.1, 0.2, 0.3],
    )
    db.add(RawEvent(title="AI Conf raw", raw_description="x", status="raw"))
    db.commit()
    raw = db.query(RawEvent).first()

    status = ingestion_service._normalize_single(db, raw)

    assert status == "normalized"
    event = db.query(Event).filter(Event.title == "AI Conf").first()
    assert event is not None
    assert json.loads(event.embedding) == [0.1, 0.2, 0.3]


def test_normalize_survives_embedding_failure(db, monkeypatch, fake_normalizer):
    def boom(event):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("app.recommender.embeddings.build_event_embedding", boom)
    db.add(RawEvent(title="AI Conf raw", raw_description="x", status="raw"))
    db.commit()
    raw = db.query(RawEvent).first()

    status = ingestion_service._normalize_single(db, raw)

    # сбой эмбеддинга не должен ронять нормализацию
    assert status == "normalized"
    event = db.query(Event).filter(Event.title == "AI Conf").first()
    assert event is not None
    assert event.embedding is None


# ── батч-нормализация + early-stop на rate-limit ──────────────────────────


def test_normalize_by_ids_batch_creates_events(db, monkeypatch):
    """Батч-путь: один вызов event_normalizer_agent_batch на пачку → N событий."""
    def fake_batch(payloads):
        return [
            {
                "title": f"Event {i}",
                "description": "desc",
                "format": "online",
                "city": "any",
                "level": "beginner",
                "date": "2026-06-01",
                "topics": ["ai_ml"],
            }
            for i, _ in enumerate(payloads)
        ]

    monkeypatch.setattr(
        "app.agents.event_normalization.agent.event_normalizer_agent_batch", fake_batch
    )
    monkeypatch.setattr(
        "app.recommender.embeddings.build_event_embedding", lambda e: [0.1, 0.2, 0.3]
    )
    # отключаем semantic-dedup, иначе одинаковые стаб-векторы схлопнутся в дубли
    monkeypatch.setattr(
        "app.recommender.dedup.find_semantic_duplicate", lambda *a, **kw: None
    )
    for i in range(3):
        db.add(RawEvent(title=f"raw {i}", raw_description="x", status="raw"))
    db.commit()
    ids = [r.id for r in db.query(RawEvent).all()]

    normalized, non_it, failed = ingestion_service._normalize_by_ids(db, ids, batch_size=5)

    assert (normalized, non_it, failed) == (3, 0, 0)
    assert db.query(Event).count() == 3
    assert all(r.status == "normalized" for r in db.query(RawEvent).all())
    # date "2026-06-01" распарсилась в start_at (DateTime) для freshness
    assert all(e.start_at is not None for e in db.query(Event).all())


def test_normalize_by_ids_rate_limit_leaves_raw(db, monkeypatch):
    """На rate-limit обработка прерывается, события остаются 'raw' (не 'failed')."""
    def boom(payloads):
        raise RuntimeError("Error code: 429 - rate_limit_exceeded: tokens per day (TPD)")

    monkeypatch.setattr(
        "app.agents.event_normalization.agent.event_normalizer_agent_batch", boom
    )
    for i in range(3):
        db.add(RawEvent(title=f"raw {i}", raw_description="x", status="raw"))
    db.commit()
    ids = [r.id for r in db.query(RawEvent).all()]

    normalized, non_it, failed = ingestion_service._normalize_by_ids(db, ids, batch_size=5)

    assert (normalized, non_it, failed) == (0, 0, 0)
    assert db.query(Event).count() == 0
    # ключевое: остались raw, а не failed → доберутся следующим /normalize
    assert all(r.status == "raw" for r in db.query(RawEvent).all())


def test_retry_count_increments_and_caps(db, monkeypatch):
    """Каждый провал нормализации инкрементит retry_count; после
    MAX_NORMALIZE_RETRIES событие retry-failed больше не подбирает."""
    def boom_batch(payloads):
        raise ValueError("bad json")  # не rate-limit → деградация до per-event

    def boom_single(state):
        raise ValueError("llm broke")  # не rate-limit → _mark_failed

    monkeypatch.setattr(
        "app.agents.event_normalization.agent.event_normalizer_agent_batch", boom_batch
    )
    monkeypatch.setattr(
        "app.agents.event_normalization.agent.event_normalizer_agent", boom_single
    )
    db.add(RawEvent(title="X", raw_description="d", status="raw"))
    db.commit()

    # 1-я попытка (raw → failed), retry_count=1
    ingestion_service.normalize_raw_events(db)
    r = db.query(RawEvent).first()
    assert r.status == "failed" and r.retry_count == 1

    # ещё две retry-failed → 2, 3
    ingestion_service.retry_failed_events(db)
    db.refresh(r)
    assert r.retry_count == 2
    ingestion_service.retry_failed_events(db)
    db.refresh(r)
    assert r.retry_count == 3

    # retry_count >= MAX(3) → больше не подбирается
    res = ingestion_service.retry_failed_events(db)
    assert res["picked"] == 0
    db.refresh(r)
    assert r.retry_count == 3
