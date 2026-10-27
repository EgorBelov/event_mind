"""Параметры пайплайна ingestion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    normalize_batch_size: int = 20
    max_normalize_retries: int = 3
    # текст для эмбеддинга события: raw | summary | both (P1 №15, эксперимент H4)
    embedding_text_mode: Literal["raw", "summary", "both"] = "raw"
