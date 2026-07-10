"""CLI офлайн-эвала: печатает таблицу метрик и (опц.) пишет JSON.

    python -m eval.run                 # печать таблицы
    python -m eval.run --json out.json # + машиночитаемый результат

Полностью детерминирован (seed=42) — цифры воспроизводимы для отчёта/CI.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from eval.harness import KS, EvalReport, run_evaluation


def format_table(report: EvalReport) -> str:
    lines = [
        f"=== EventMind offline eval (leave-one-out, seed={report.seed}) ===",
        f"users={report.n_users}  events={report.n_events}",
        "",
        f"{'variant':14} " + " ".join(f"R@{k:<3}" for k in KS) + " "
        + " ".join(f"nDCG@{k:<2}" for k in KS)
        + f" {'MAP':>6} {'cover':>6} {'divers':>6}",
        "-" * 96,
    ]
    for r in report.results:
        recalls = " ".join(f"{r.recall[k]:<4.2f}" for k in KS)
        ndcgs = " ".join(f"{r.ndcg[k]:<6.3f}" for k in KS)
        lines.append(
            f"{r.variant:14} {recalls} {ndcgs} "
            f"{r.map:>6.3f} {r.coverage_at_10:>6.2f} {r.diversity_at_10:>6.3f}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="EventMind offline recommender eval")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json", type=str, default=None, help="путь для JSON-результата")
    args = parser.parse_args()

    report = run_evaluation(seed=args.seed)
    print(format_table(report))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, ensure_ascii=False, indent=2)
        print(f"\n[saved] {args.json}")


if __name__ == "__main__":
    main()
