"""Параметры пайплайна ingestion."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    normalize_batch_size: int = 20
    max_normalize_retries: int = 3
