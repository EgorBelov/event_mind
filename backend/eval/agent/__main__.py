"""CLI оценки агента (A6). Нужны ключи LLM в `.env`; для `simulate` — ещё
корпус и разметка из `eval/real` (`events.jsonl`, `labels.jsonl`) и extra `ml`.

    python -m eval.agent toolcalls                      # точность вызовов
    python -m eval.agent toolcalls --repeats 3          # + стабильность
    python -m eval.agent simulate --personas 12 --turns 3 --judge
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from eval.agent.simulate import (
    PersonaRun,
    UserSimulator,
    format_report,
    run_cold,
    run_dialog,
    run_form,
    summarize,
    unjudged_pairs,
)
from eval.agent.toolcalls import format_report as format_toolcalls
from eval.agent.toolcalls import load_dataset, run_toolcalls
from eval.agent.toolcalls import summarize as summarize_toolcalls
from eval.agent.world import (
    QueryEmbedding,
    Stack,
    World,
    build_stack,
    corpus_event_to_entity,
)
from eval.real.data import Label, append_label, load_events, load_labels, load_personas
from eval.real.encoders import ENCODERS, EmbeddingCache, sentence_transformer_encode_fn
from eval.real.judge import judge_pool
from eval.real.systems import event_text
from eventmind.config import get_settings
from eventmind.infrastructure.llm.providers import create_llm_chain


def _save(path: str | None, payload: object) -> None:
    if path:
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"\n[saved] {path}")


async def _toolcalls(args: argparse.Namespace) -> None:
    llm = create_llm_chain(get_settings())
    dataset = load_dataset()
    results = []
    for _ in range(args.repeats):
        report = await run_toolcalls(llm, dataset, limit=args.limit)
        results.extend(report.cases)
    report = summarize_toolcalls(results)
    print(format_toolcalls(report))
    _save(args.json, asdict(report))


async def _simulate(args: argparse.Namespace) -> None:
    settings = get_settings()
    llm = create_llm_chain(settings)
    spec = ENCODERS[args.encoder]
    encode = sentence_transformer_encode_fn(spec)
    cache = EmbeddingCache(spec)

    corpus = load_events()
    vectors = await cache.passages([event_text(ev) for ev in corpus], encode)
    events = [corpus_event_to_entity(ev, vec) for ev, vec in zip(corpus, vectors, strict=True)]
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)

    async def encode_query(text: str) -> list[float]:
        return (await cache.queries([text], encode))[0]

    embedding = QueryEmbedding(encode_query, len(vectors[0]) if vectors else 0)
    personas = load_personas()
    if args.ids:
        wanted = set(args.ids.split(","))
        personas = [p for p in personas if p.id in wanted]
    personas = random.Random(args.seed).sample(personas, min(args.personas, len(personas)))

    def stack() -> Stack:
        return build_stack(World(events, now=now), agent_llm=llm, gateway=llm, embedding=embedding)

    runs: list[PersonaRun] = []
    for persona in sorted(personas, key=lambda p: p.id):
        cold = await run_cold(stack())
        form = await run_form(stack(), persona)
        turns = await run_dialog(stack(), UserSimulator(llm, persona), turns=args.turns)
        runs.append(PersonaRun(persona_id=persona.id, cold=cold, form=form, turns=turns))
        print(f"[{persona.id}] готово: {len(turns)} реплик")

    labels = load_labels()
    if args.judge:
        pool = unjudged_pairs(runs, _rels(labels))
        by_id = {ev.id: ev for ev in corpus}
        done, failed = await judge_pool(
            llm,
            pool,
            {p.id: p for p in personas},
            by_id,
            labels,
            judge_name=f"agent-sim:{args.encoder}",
            on_label=append_label,
        )
        print(f"[judge] размечено {done}, ошибок {failed}")
        labels = load_labels()

    report = summarize(runs, _rels(labels))
    print(format_report(report))
    _save(args.json, {"report": asdict(report), "runs": [asdict(r) for r in runs]})


def _rels(labels: dict[tuple[str, int], Label]) -> dict[str, dict[int, int]]:
    rels: dict[str, dict[int, int]] = {}
    for (pid, eid), label in labels.items():
        rels.setdefault(pid, {})[eid] = label.relevance
    return rels


def main() -> None:
    parser = argparse.ArgumentParser(description="EventMind: оценка диалогового агента (A6)")
    sub = parser.add_subparsers(dest="command", required=True)

    tc = sub.add_parser("toolcalls", help="точность выбора инструмента и аргументов")
    tc.add_argument("--limit", type=int, default=None)
    tc.add_argument("--repeats", type=int, default=1, help="повторов набора (стабильность)")
    tc.add_argument("--json", type=str, default=None)

    sim = sub.add_parser("simulate", help="симуляция пользователей: диалог vs анкета")
    sim.add_argument("--personas", type=int, default=12)
    sim.add_argument("--ids", type=str, default="", help="id персон через запятую")
    sim.add_argument("--turns", type=int, default=3)
    sim.add_argument("--encoder", choices=sorted(ENCODERS), default="minilm")
    sim.add_argument("--now", type=str, default="", help="«сегодня» для корпуса, ISO-8601")
    sim.add_argument("--judge", action="store_true", help="доразметить новые пары судьёй")
    sim.add_argument("--seed", type=int, default=42)
    sim.add_argument("--json", type=str, default=None)

    args = parser.parse_args()
    asyncio.run(_toolcalls(args) if args.command == "toolcalls" else _simulate(args))


if __name__ == "__main__":
    main()
