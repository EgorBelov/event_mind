"""Точность выбора инструмента и аргументов на наборе типовых реплик.

Формат ограничений в `agent_toolcalls.json` (поле `args` кейса):
- `"city": "perm|Пермь"` — аргумент равен одному из вариантов (город
  канонизируется, строки сравниваются без регистра);
- `"topics_any": ["ai_ml", "ml"]` — список-аргумент содержит хотя бы один
  вариант (slug'и сравниваются после `slugify_code`);
- `"present": ["add_goals|add_interests"]` — хотя бы один из аргументов задан
  и не пуст.

`tool` кейса — имя, список допустимых имён или null (инструмент не нужен:
болтовня, вопрос не по теме).
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from eventmind.application.agent.prompts import build_system_prompt
from eventmind.application.agent.tools import ALL_TOOLS
from eventmind.application.ports.llm import LLMMessage, ToolCallingLLM
from eventmind.domain.events.taxonomy import canonicalize_city, slugify_code

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "agent_toolcalls.json"
NO_TOOL = "∅"


@dataclass(slots=True)
class ToolCase:
    id: str
    message: str
    tools: list[str | None]  # допустимые инструменты (None — без инструмента)
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolDataset:
    now: datetime
    profile: dict[str, Any]
    topics: list[str]
    shown: list[dict[str, Any]]
    cases: list[ToolCase]


def load_dataset(path: Path = DATA_PATH) -> ToolDataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for item in raw["cases"]:
        tool = item["tool"]
        cases.append(
            ToolCase(
                id=item["id"],
                message=item["message"],
                tools=list(tool) if isinstance(tool, list) else [tool],
                args=dict(item.get("args") or {}),
            )
        )
    return ToolDataset(
        now=datetime.fromisoformat(raw["now"]),
        profile=raw["profile"],
        topics=raw["topics"],
        shown=raw["shown"],
        cases=cases,
    )


# ── проверка ограничений ──────────────────────────────────────────────────────
def _norm(key: str, value: Any) -> str:
    text = str(value).strip()
    if key == "city":
        return canonicalize_city(text)
    return text.casefold()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def check_constraint(key: str, expected: Any, args: dict[str, Any]) -> bool:
    if key == "present":
        return all(
            any(any(v.strip() for v in _as_list(args.get(alt))) for alt in group.split("|"))
            for group in expected
        )
    if key.endswith("_any"):
        actual = {slugify_code(v) for v in _as_list(args.get(key.removesuffix("_any")))}
        return bool(actual & {slugify_code(v) for v in expected})
    if key not in args or args[key] is None:
        return False
    variants = str(expected).split("|") if isinstance(expected, str) else [expected]
    return _norm(key, args[key]) in {_norm(key, v) for v in variants}


@dataclass(slots=True)
class CaseResult:
    id: str
    expected: list[str | None]
    got: str | None
    arguments: dict[str, Any]
    tool_ok: bool
    args_passed: int
    args_total: int
    provider: str = ""
    latency_ms: int = 0
    error: str | None = None

    @property
    def args_ok(self) -> bool:
        return self.args_passed == self.args_total

    @property
    def strict_ok(self) -> bool:
        return self.tool_ok and self.args_ok


def score_case(
    case: ToolCase, got: str | None, arguments: dict[str, Any]
) -> tuple[bool, int, int]:
    """(верный инструмент, выполнено ограничений, всего ограничений)."""
    tool_ok = got in case.tools
    if not tool_ok or got is None:
        return tool_ok, 0, len(case.args)
    passed = sum(check_constraint(k, v, arguments) for k, v in case.args.items())
    return tool_ok, passed, len(case.args)


# ── прогон ────────────────────────────────────────────────────────────────────
def _context(dataset: ToolDataset) -> list[LLMMessage]:
    """Предыдущий обмен репликами: агент уже показал события (для «второе», «первое»)."""
    listing = "\n".join(
        f"{i}) {ev['title']} — {ev['date']}, {ev['city']}, {ev['format']} (id {ev['id']})"
        for i, ev in enumerate(dataset.shown, start=1)
    )
    return [
        LLMMessage(role="user", content="Что есть интересного по бэкенду?"),
        LLMMessage(role="assistant", content=f"Нашёл несколько событий:\n{listing}"),
    ]


async def run_case(llm: ToolCallingLLM, dataset: ToolDataset, case: ToolCase) -> CaseResult:
    system = build_system_prompt(dataset.now, profile=dataset.profile, topics=dataset.topics)
    messages = [
        LLMMessage(role="system", content=system),
        *_context(dataset),
        LLMMessage(role="user", content=case.message),
    ]
    specs = [tool.spec() for tool in ALL_TOOLS]
    started = time.perf_counter()
    try:
        step = await llm.complete_with_tools(messages, specs, temperature=0.0)
    except Exception as exc:
        return CaseResult(
            id=case.id, expected=case.tools, got=None, arguments={}, tool_ok=False,
            args_passed=0, args_total=len(case.args), error=str(exc)[:300],
        )
    latency = int((time.perf_counter() - started) * 1000)
    call = step.tool_calls[0] if step.tool_calls else None
    got = call.name if call else None
    arguments = dict(call.arguments) if call else {}
    tool_ok, passed, total = score_case(case, got, arguments)
    return CaseResult(
        id=case.id, expected=case.tools, got=got, arguments=arguments, tool_ok=tool_ok,
        args_passed=passed, args_total=total, provider=step.provider, latency_ms=latency,
    )


@dataclass(slots=True)
class ToolCallReport:
    n: int
    tool_accuracy: float
    args_accuracy: float  # доля выполненных ограничений среди кейсов с верным инструментом
    strict_accuracy: float
    errors: int
    per_tool: dict[str, float]  # точность по ожидаемому (первому допустимому) инструменту
    confusion: dict[str, dict[str, int]]  # ожидаемый → {полученный: n}
    cases: list[CaseResult]


def _label(tool: str | None) -> str:
    return tool or NO_TOOL


def summarize(results: list[CaseResult]) -> ToolCallReport:
    n = len(results)
    with_tool = [r for r in results if r.tool_ok and r.args_total]
    passed = sum(r.args_passed for r in with_tool)
    total = sum(r.args_total for r in with_tool)
    by_tool: dict[str, list[bool]] = {}
    confusion: dict[str, Counter[str]] = {}
    for r in results:
        key = _label(r.expected[0])
        by_tool.setdefault(key, []).append(r.tool_ok)
        confusion.setdefault(key, Counter())[_label(r.got)] += 1
    return ToolCallReport(
        n=n,
        tool_accuracy=sum(r.tool_ok for r in results) / n if n else 0.0,
        args_accuracy=passed / total if total else 1.0,
        strict_accuracy=sum(r.strict_ok for r in results) / n if n else 0.0,
        errors=sum(r.error is not None for r in results),
        per_tool={k: sum(v) / len(v) for k, v in sorted(by_tool.items())},
        confusion={k: dict(c) for k, c in sorted(confusion.items())},
        cases=results,
    )


async def run_toolcalls(
    llm: ToolCallingLLM, dataset: ToolDataset, *, limit: int | None = None
) -> ToolCallReport:
    results = [await run_case(llm, dataset, case) for case in dataset.cases[:limit]]
    return summarize(results)


def format_report(report: ToolCallReport) -> str:
    lines = [
        f"=== Агент: точность вызовов инструментов (n={report.n}, ошибок LLM={report.errors}) ===",
        f"инструмент: {report.tool_accuracy:.3f}   аргументы: {report.args_accuracy:.3f}   "
        f"строго: {report.strict_accuracy:.3f}",
        "",
        f"{'ожидался':18} {'точность':>8}   получено",
        "-" * 70,
    ]
    for tool, acc in report.per_tool.items():
        got = ", ".join(f"{k}×{v}" for k, v in sorted(report.confusion[tool].items()))
        lines.append(f"{tool:18} {acc:>8.2f}   {got}")
    misses = [r for r in report.cases if not r.strict_ok]
    if misses:
        lines += ["", "Промахи:"]
        for r in misses:
            lines.append(
                f"  {r.id}: ждали {'/'.join(map(_label, r.expected))}, получили {_label(r.got)} "
                f"{json.dumps(r.arguments, ensure_ascii=False)}"
                + (f" — {r.error}" if r.error else "")
            )
    return "\n".join(lines)
