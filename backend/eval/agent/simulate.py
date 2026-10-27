"""Симуляция пользователей: LLM-персона со скрытым профилем ↔ агент (A6).

Для каждой персоны три независимых «мира» (корпус + новый пользователь):
- **cold** — пользователь ничего не рассказал (холодный старт);
- **form** — анкета: текст «о себе» + город/формат → `UpdateUserProfile`
  (то же, что онбординг B2 и страница настроек);
- **dialog** — N реплик симулятора с агентом; модель пользователя строится
  только тем, что агент записал инструментами (профиль, настройки, оценки).

После каждой реплики диалога и для обеих базовых линий выдача берётся тем же
`GetRecommendations`, что в приложении, и оценивается nDCG@10 по разметке
LLM-судьи. Плюс: число реплик до первого релевантного события в ответе агента,
вызовы инструментов и подтверждения.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from eval.agent.world import USER_ID, Stack
from eval.real.data import RELEVANT_THRESHOLD, Persona
from eval.real.stats import bootstrap_ci, judged_at_k, mean, ndcg_at_k, wilcoxon_signed_rank
from eventmind.application.ports.llm import LLMGateway, LLMMessage

K = 10

_SIM_PROMPT = """
Ты играешь пользователя приложения, которое подбирает IT-мероприятия. Ты
переписываешься с его помощником в мессенджере.

Твой скрытый профиль (помощник его не видит; не пересказывай целиком):
<profile>
{about}
Город: {city}. Формат: {fmt}.
</profile>

Правила:
- Пиши как живой человек: 1–2 коротких предложения, без списков.
- Первой репликой попроси подобрать мероприятия, назвав одну-две детали о себе.
- Дальше отвечай на вопросы помощника и постепенно раскрывай профиль: что
  нравится, что не интересно, цели, город, формат.
- Если помощник предлагает изменить профиль или настройки — ответь одним
  словом «да», если изменение соответствует твоему профилю, иначе «нет».
- Если показанные события подходят — скажи, что понравилось; если нет —
  объясни, чего не хватает.
""".strip()


def _shown_block(titles: Sequence[str]) -> str:
    return ("\n\nПоказаны события:\n" + "\n".join(f"- {t}" for t in titles)) if titles else ""


class UserSimulator:
    """Роли переставлены: реплики симулятора — assistant, ответы агента — user."""

    def __init__(self, llm: LLMGateway, persona: Persona, *, temperature: float = 0.7) -> None:
        self._llm = llm
        self._system = _SIM_PROMPT.format(
            about=persona.about,
            city=persona.city or "не важен",
            fmt=persona.preferred_format or "не важен",
        )
        self._temperature = temperature
        self.history: list[LLMMessage] = []

    async def say(self, agent_text: str | None = None, shown: Sequence[str] = ()) -> str:
        if agent_text is None:
            prompt = "Начни разговор."
        else:
            prompt = f"Помощник: {agent_text}{_shown_block(shown)}"
        self.history.append(LLMMessage(role="user", content=prompt))
        result = await self._llm.complete(
            [LLMMessage(role="system", content=self._system), *self.history],
            temperature=self._temperature,
            max_tokens=200,
        )
        text = result.text.strip() or "Подбери что-нибудь."
        self.history.append(LLMMessage(role="assistant", content=text))
        return text


@dataclass(slots=True)
class TurnLog:
    user: str
    agent: str
    shown: list[int]
    ranking: list[int]  # выдача GetRecommendations после реплики
    stop_reason: str
    tools: list[str] = field(default_factory=list)  # "tool:status"


@dataclass(slots=True)
class PersonaRun:
    persona_id: str
    cold: list[int]
    form: list[int]
    turns: list[TurnLog]


async def ranking(stack: Stack, k: int = K) -> list[int]:
    return [it.event_id for it in await stack.recommendations.execute(USER_ID)][:k]


async def run_cold(stack: Stack) -> list[int]:
    return await ranking(stack)


async def run_form(stack: Stack, persona: Persona) -> list[int]:
    """Анкета: город и формат кнопками + текст «о себе» (как онбординг B2)."""
    fmt = "" if persona.preferred_format in (None, "any") else persona.preferred_format
    await stack.world.execute(USER_ID, city=persona.city or "", preferred_format=fmt)
    await stack.update_profile.execute(USER_ID, about=persona.about)
    return await ranking(stack)


async def run_dialog(stack: Stack, simulator: UserSimulator, *, turns: int) -> list[TurnLog]:
    logs: list[TurnLog] = []
    message = await simulator.say()
    for turn in range(1, turns + 1):
        reply = await stack.agent.execute(USER_ID, message, channel="eval")
        shown = [e.id for e in reply.events if e.id is not None]
        logs.append(
            TurnLog(
                user=message,
                agent=reply.text,
                shown=shown,
                ranking=await ranking(stack),
                stop_reason=reply.stop_reason,
                tools=[f"{c.tool}:{c.status}" for c in reply.tool_calls],
            )
        )
        if turn < turns:
            message = await simulator.say(reply.text, [e.title for e in reply.events])
    return logs


# ── метрики ───────────────────────────────────────────────────────────────────
Rels = Mapping[str, Mapping[int, int]]


def turns_to_hit(turns: Sequence[TurnLog], rels: Mapping[int, int]) -> int | None:
    """Номер первой реплики, после которой агент показал релевантное событие."""
    for i, turn in enumerate(turns, start=1):
        if any(rels.get(e, 0) >= RELEVANT_THRESHOLD for e in turn.shown):
            return i
    return None


@dataclass(slots=True)
class SimulationReport:
    n_personas: int
    turns: int
    ndcg_cold: float
    ndcg_form: float
    ndcg_dialog_by_turn: list[float]
    ci_form: tuple[float, float]
    ci_dialog: tuple[float, float]
    wilcoxon_dialog_vs_form: tuple[float, float]  # (W, p)
    hit_rate: float  # доля персон, увидевших релевантное событие за N реплик
    mean_turns_to_hit: float | None
    judged_dialog: float  # доля размеченных в финальной выдаче диалога (полнота разметки)
    tool_usage: dict[str, int]
    stop_reasons: dict[str, int]
    per_persona: list[dict[str, object]]


def summarize(runs: Sequence[PersonaRun], rels: Rels, *, k: int = K) -> SimulationReport:
    def ndcg(pid: str, ranked: Sequence[int]) -> float:
        return ndcg_at_k(ranked, rels.get(pid, {}), k) or 0.0

    n_turns = max((len(r.turns) for r in runs), default=0)
    cold = [ndcg(r.persona_id, r.cold) for r in runs]
    form = [ndcg(r.persona_id, r.form) for r in runs]
    by_turn: list[list[float]] = [[] for _ in range(n_turns)]
    final: list[float] = []
    hits: list[int | None] = []
    tools: Counter[str] = Counter()
    stops: Counter[str] = Counter()
    per_persona: list[dict[str, object]] = []
    judged: list[float] = []
    for run in runs:
        pr = rels.get(run.persona_id, {})
        scores = [ndcg(run.persona_id, t.ranking) for t in run.turns]
        for i, score in enumerate(scores):
            by_turn[i].append(score)
        final.append(scores[-1] if scores else 0.0)
        if run.turns:
            judged.append(judged_at_k(run.turns[-1].ranking, pr, k))
        hit = turns_to_hit(run.turns, pr)
        hits.append(hit)
        for t in run.turns:
            stops[t.stop_reason] += 1
            tools.update(t.tools)
        per_persona.append(
            {
                "persona": run.persona_id,
                "cold": round(cold[len(per_persona)], 4),
                "form": round(form[len(per_persona)], 4),
                "dialog": [round(s, 4) for s in scores],
                "turns_to_hit": hit,
            }
        )
    reached = [h for h in hits if h is not None]
    return SimulationReport(
        n_personas=len(runs),
        turns=n_turns,
        ndcg_cold=mean(cold),
        ndcg_form=mean(form),
        ndcg_dialog_by_turn=[mean(v) for v in by_turn],
        ci_form=bootstrap_ci(form),
        ci_dialog=bootstrap_ci(final),
        wilcoxon_dialog_vs_form=wilcoxon_signed_rank(final, form) if runs else (0.0, 1.0),
        hit_rate=len(reached) / len(runs) if runs else 0.0,
        mean_turns_to_hit=mean([float(h) for h in reached]) if reached else None,
        judged_dialog=mean(judged),
        tool_usage=dict(tools.most_common()),
        stop_reasons=dict(stops.most_common()),
        per_persona=per_persona,
    )


def unjudged_pairs(runs: Sequence[PersonaRun], rels: Rels) -> dict[str, list[int]]:
    """Пул для доразметки: всё, что попало в выдачи и ответы агента без оценки судьи."""
    pool: dict[str, list[int]] = {}
    for run in runs:
        known = rels.get(run.persona_id, {})
        ids = [*run.cold, *run.form]
        for t in run.turns:
            ids += [*t.shown, *t.ranking]
        todo = [e for e in dict.fromkeys(ids) if e not in known]
        if todo:
            pool[run.persona_id] = todo
    return pool


def format_report(report: SimulationReport) -> str:
    lines = [
        f"=== Агент: симуляция пользователей (персон={report.n_personas}, "
        f"реплик={report.turns}, nDCG@{K}) ===",
        f"холодный старт : {report.ndcg_cold:.3f}",
        f"анкета         : {report.ndcg_form:.3f}  CI95 [{report.ci_form[0]:.3f}; "
        f"{report.ci_form[1]:.3f}]",
    ]
    for i, value in enumerate(report.ndcg_dialog_by_turn, start=1):
        lines.append(f"диалог, реплика {i}: {value:.3f}")
    w, p = report.wilcoxon_dialog_vs_form
    lines += [
        f"диалог (финал) CI95 [{report.ci_dialog[0]:.3f}; {report.ci_dialog[1]:.3f}]; "
        f"Уилкоксон диалог vs анкета: W={w:.1f}, p={p:.4f}",
        f"релевантное событие в ответе агента: у {report.hit_rate:.0%} персон"
        + (
            f", в среднем на реплике {report.mean_turns_to_hit:.2f}"
            if report.mean_turns_to_hit is not None
            else ""
        ),
        f"размечено в финальной выдаче диалога: {report.judged_dialog:.0%}",
        "инструменты: " + json.dumps(report.tool_usage, ensure_ascii=False),
        "остановки: " + json.dumps(report.stop_reasons, ensure_ascii=False),
    ]
    return "\n".join(lines)
