"""Тесты конфигурации APScheduler: ingestion должен стартовать сразу."""
from datetime import datetime

import pytest

from app.scheduler import digest


@pytest.fixture
def enable_ingest(monkeypatch):
    monkeypatch.setattr(digest.settings, "ingest_enabled", True)
    monkeypatch.setattr(digest.settings, "ingest_interval_hours", 6)


def _jobs(scheduler) -> dict:
    return {j.id: j for j in scheduler.get_jobs()}


def test_ingest_jobs_present_when_enabled(enable_ingest):
    jobs = _jobs(digest.build_scheduler())

    assert set(jobs) == {"daily_digest", "ingest_habr", "ingest_rss"}


def test_ingest_jobs_run_on_startup(enable_ingest):
    jobs = _jobs(digest.build_scheduler())
    now = datetime.now().timestamp()

    habr_at = jobs["ingest_habr"].next_run_time
    rss_at = jobs["ingest_rss"].next_run_time

    assert habr_at is not None and rss_at is not None
    # habr — практически сейчас, rss — с небольшим сдвигом (~30 c)
    assert habr_at.timestamp() <= now + 5
    assert now <= rss_at.timestamp() <= now + 90
    # rss не должен стартовать одновременно с habr
    assert rss_at.timestamp() > habr_at.timestamp()


def test_digest_not_run_on_startup(enable_ingest):
    jobs = _jobs(digest.build_scheduler())

    # next_run_time не задан явно → у pending-задачи атрибут не выставлен
    # вовсе (вычислится только при .start()), то есть рассылка не уходит
    # при каждом рестарте процесса
    assert getattr(jobs["daily_digest"], "next_run_time", None) is None


def test_ingestion_disabled_leaves_only_digest(monkeypatch):
    monkeypatch.setattr(digest.settings, "ingest_enabled", False)

    jobs = _jobs(digest.build_scheduler())

    assert set(jobs) == {"daily_digest"}
