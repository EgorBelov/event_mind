"""Данные офлайн-оценки на реальном корпусе: события, персоны, разметка.

Файлы (по умолчанию в `backend/eval/data/`):
- `personas.json`           — персоны, написанные вручную (в репозитории);
- `events.jsonl`            — снимок событий из БД (`python -m eval.real export`);
- `personas_extracted.json` — профили персон, извлечённые `ProfileExtractor`
                              (`prepare`; то же, что делает приложение);
- `labels.jsonl`            — оценки релевантности LLM-судьи (`judge`);
- `annotation_sample.csv`   — подвыборка для ручной проверки (`sample`);
- `cache/`                  — кэш эмбеддингов по энкодерам (не коммитится).
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PERSONAS_PATH = DATA_DIR / "personas.json"
EVENTS_PATH = DATA_DIR / "events.jsonl"
EXTRACTED_PATH = DATA_DIR / "personas_extracted.json"
LABELS_PATH = DATA_DIR / "labels.jsonl"
SAMPLE_PATH = DATA_DIR / "annotation_sample.csv"
CACHE_DIR = DATA_DIR / "cache"

# Релевантность считается «попаданием» при оценке судьи ≥ этого порога (шкала 0..3).
RELEVANT_THRESHOLD = 2


@dataclass(slots=True)
class CorpusEvent:
    id: int
    title: str
    description: str
    topics: list[str] = field(default_factory=list)
    format: str = "unknown"
    city: str = "unknown"
    event_type: str | None = None
    seniority: str | None = None
    start_at: str | None = None  # ISO-8601
    quality_score: int | None = None
    hype_score: int | None = None
    source: str = ""
    source_url: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    series_slug: str | None = None
    summary: str | None = None  # каноническое LLM-описание (P1 №15, эксперимент H4)


@dataclass(slots=True)
class Persona:
    id: str
    about: str
    city: str | None = None
    preferred_format: str | None = None


@dataclass(slots=True)
class ExtractedPersona:
    """Профиль персоны так, как его видит система (выжимка `ProfileExtractor`)."""

    id: str
    role: str = ""
    level: str = "any"
    stack: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    anti_interests: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    llm_ok: bool = True


@dataclass(slots=True)
class Label:
    persona_id: str
    event_id: int
    relevance: int  # 0..3
    reason: str = ""
    judge: str = ""


# ── чтение / запись ───────────────────────────────────────────────────────────
def load_personas(path: Path = PERSONAS_PATH) -> list[Persona]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Persona(**item) for item in raw]


def load_events(path: Path = EVENTS_PATH) -> list[CorpusEvent]:
    events: list[CorpusEvent] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                events.append(CorpusEvent(**json.loads(line)))
    return events


def save_events(events: Iterable[CorpusEvent], path: Path = EVENTS_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")
            count += 1
    return count


def load_extracted(path: Path = EXTRACTED_PATH) -> dict[str, ExtractedPersona]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: ExtractedPersona(**item) for item in raw}


def save_extracted(items: Iterable[ExtractedPersona], path: Path = EXTRACTED_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(p) for p in sorted(items, key=lambda p: p.id)]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_labels(path: Path = LABELS_PATH) -> dict[tuple[str, int], Label]:
    """Разметка {(persona_id, event_id): Label}; более поздняя строка перекрывает раннюю."""
    labels: dict[tuple[str, int], Label] = {}
    if not path.exists():
        return labels
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                label = Label(**json.loads(line))
                labels[(label.persona_id, label.event_id)] = label
    return labels


def append_label(label: Label, path: Path = LABELS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(label), ensure_ascii=False) + "\n")
