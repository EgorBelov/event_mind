"""Билдеры провайдеров (Gemini/Groq), async-автопроба Gemini и сборка цепочки.

Портировано из `legacy/app/agents/recommendation/llm.py`:
- Gemini через REST-транспорт + таймаут (gRPC режется по DNS на части сетапов).
- Автопроба Gemini-модели: free-tier режет квоты конкретной модели без
  предупреждения, поэтому берём первую отвечающую 200 из fallback-списка.
Модели строятся ЛЕНИВО (factory), чтобы импорт не требовал ключей.
"""
from __future__ import annotations

import httpx
import structlog

from eventmind.config import Settings
from eventmind.infrastructure.llm.breaker import CircuitBreaker, ProviderCooldown
from eventmind.infrastructure.llm.chain import ChatModel, LLMChain, ProviderLink

_logger = structlog.get_logger("eventmind.llm")

# Сверху — модели с самыми щедрыми free-tier лимитами; можно перебить GOOGLE_MODEL.
_GEMINI_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash",
)

_PROBE_TIMEOUT_S = 8.0


def _build_groq(settings: Settings, model_name: str) -> ChatModel:
    from langchain_groq import ChatGroq

    model: ChatModel = ChatGroq(
        model=model_name,
        api_key=settings.groq_api_key,
        temperature=settings.llm_temperature,
    )
    return model


def _build_gemini(settings: Settings, model_name: str) -> ChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    # transport="rest": gRPC у langchain-google-genai на части сетапов не
    # резолвит generativelanguage.googleapis.com (AdGuard/IPv6) — REST обходит.
    model: ChatModel = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=settings.google_api_key,
        temperature=settings.llm_temperature,
        transport="rest",
        timeout=settings.llm_timeout_seconds,
    )
    return model


def _gemini_candidates(settings: Settings) -> list[str]:
    candidates: list[str] = []
    if settings.google_model:
        candidates.append(settings.google_model)
    for m in _GEMINI_FALLBACK_MODELS:
        if m not in candidates:
            candidates.append(m)
    return candidates


async def probe_gemini_model(settings: Settings) -> str | None:
    """Найти первую Gemini-модель, отвечающую 200 на минимальный запрос (REST).

    None → gemini выпадает из цепочки (нет ключа или все квоты выбраны).
    """
    if not settings.google_api_key:
        return None

    body = {
        "contents": [{"parts": [{"text": "ok"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }
    base = "https://generativelanguage.googleapis.com/v1beta/models"
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
        for model in _gemini_candidates(settings):
            try:
                resp = await client.post(
                    f"{base}/{model}:generateContent",
                    params={"key": settings.google_api_key},
                    json=body,
                )
                if resp.status_code == 200:
                    _logger.info("gemini_probe_selected", model=model)
                    return model
                _logger.debug("gemini_probe_reject", model=model, status=resp.status_code)
            except Exception as exc:  # сеть/DNS — пробуем следующую модель
                _logger.debug("gemini_probe_error", model=model, error=str(exc))
    _logger.warning("gemini_probe_none_available")
    return None


def build_links(settings: Settings, *, gemini_model: str | None) -> list[ProviderLink]:
    """Сформировать звенья цепочки под текущие настройки/пробу."""

    def make_gemini() -> ChatModel:
        return _build_gemini(settings, gemini_model or "")

    def make_groq_primary() -> ChatModel:
        return _build_groq(settings, settings.groq_model)

    def make_groq_fallback() -> ChatModel:
        return _build_groq(settings, settings.groq_fallback_model)

    return [
        ProviderLink(
            name=f"gemini:{gemini_model}" if gemini_model else "gemini",
            factory=make_gemini,
            enabled=bool(settings.google_api_key and gemini_model),
        ),
        ProviderLink(
            name=f"groq:{settings.groq_model}",
            factory=make_groq_primary,
            enabled=bool(settings.groq_api_key),
        ),
        ProviderLink(
            name=f"groq:{settings.groq_fallback_model}",
            factory=make_groq_fallback,
            enabled=bool(settings.groq_api_key),
        ),
    ]


def create_llm_chain(settings: Settings) -> LLMChain:
    """Собрать LLMChain без сетевой пробы (gemini-модель = GOOGLE_MODEL/первый кандидат).

    Реальную модель Gemini уточняет `reprobe_chain` (admin-эндпоинт) —
    так старт API не зависит от сети/квот.
    """
    default_gemini = settings.google_model or (_GEMINI_FALLBACK_MODELS[0])
    gemini_model = default_gemini if settings.google_api_key else None
    breaker = CircuitBreaker(
        threshold=settings.llm_breaker_threshold,
        cooldown_seconds=settings.llm_breaker_cooldown_seconds,
    )
    cooldown = ProviderCooldown(
        threshold=settings.llm_provider_fail_threshold,
        cooldown_seconds=settings.llm_provider_cooldown_seconds,
    )
    return LLMChain(
        build_links(settings, gemini_model=gemini_model),
        breaker=breaker,
        cooldown=cooldown,
        timeout_seconds=settings.llm_timeout_seconds,
        default_temperature=settings.llm_temperature,
    )


async def reprobe_chain(chain: LLMChain, settings: Settings) -> str | None:
    """Пере-пробить Gemini-модель и заменить звенья цепочки. Возвращает выбранную модель."""
    gemini_model = await probe_gemini_model(settings)
    chain.set_links(build_links(settings, gemini_model=gemini_model))
    return gemini_model
