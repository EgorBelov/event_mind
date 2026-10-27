"""Параметры пайплайна ingestion."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from eventmind.domain.events.dedup import DedupPolicy


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    normalize_batch_size: int = 20
    max_normalize_retries: int = 3
    # текст для эмбеддинга события: raw | summary | both (P1 №15, эксперимент H4)
    embedding_text_mode: Literal["raw", "summary", "both"] = "raw"
    # семантическая дедупликация между источниками (P1 №8)
    semantic_dedup: bool = True
    dedup_policy: DedupPolicy = field(default_factory=DedupPolicy)
    dedup_candidates: int = 5
