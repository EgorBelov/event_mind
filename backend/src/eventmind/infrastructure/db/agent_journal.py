"""`SqlAlchemyAgentJournal` — журнал агента в БД + Prometheus-метрики."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventmind.application.ports.agent import AgentTurnRecord
from eventmind.infrastructure.db.models import AgentToolCallModel
from eventmind.infrastructure.telemetry.metrics import (
    AGENT_TOOL_CALLS_TOTAL,
    AGENT_TURN_DURATION_SECONDS,
    AGENT_TURNS_TOTAL,
)


class SqlAlchemyAgentJournal:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, turn: AgentTurnRecord) -> None:
        AGENT_TURNS_TOTAL.labels(turn.channel, turn.stop_reason).inc()
        AGENT_TURN_DURATION_SECONDS.labels(turn.channel).observe(turn.latency_ms / 1000)
        for call in turn.tool_calls:
            AGENT_TOOL_CALLS_TOTAL.labels(call.tool, call.status).inc()
        if not turn.tool_calls:
            return
        async with self._session_factory() as session:
            session.add_all(
                AgentToolCallModel(
                    user_id=turn.user_id,
                    session_id=turn.session_id,
                    channel=turn.channel,
                    step=call.step,
                    tool=call.tool,
                    arguments=call.arguments,
                    status=call.status,
                    error=call.error,
                    latency_ms=call.latency_ms,
                    stop_reason=turn.stop_reason,
                )
                for call in turn.tool_calls
            )
            await session.commit()
