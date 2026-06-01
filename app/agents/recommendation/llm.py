"""LLM-wrapper с цепочкой провайдеров и автоматическим fallback'ом.

Цепочка (по убыванию приоритета):
1. **Gemini 2.0 Flash** — если задан `GOOGLE_API_KEY`. 1M токенов/день в
   free-tier — основной провайдер.
2. **Groq llama-3.3-70b** — primary Groq-модель. Быстрый, бесплатный,
   но дневной лимит 100k токенов на free.
3. **Groq llama-3.1-8b** — последний fallback. Слабее, но почти всегда
   доступен.

Контракт `_LLMChain` совместим с ChatGroq:
- `invoke(messages)` ходит по цепочке до первого успеха;
- `with_structured_output(schema)` оборачивает первый доступный звено
  (structured-output на fallback'е не дублируем — caller'ы там сами
  ловят и деградируют);
- `bind_tools(tools)` возвращает новую цепочку с привязанными
  инструментами (для langgraph-цепочек copilot'а).

Caller'ы (`copilot`, `why`, normalizer) уже завёрнуты в try/except и при
сбое возвращают rule-based ответ — мы не блокируем их полным таймаутом
через circuit-breaker, который открывается, если ВСЯ цепочка упала
N раз подряд.

ChatModel'и строятся ЛЕНИВО (при первом обращении), иначе импорт модулей
требовал бы ключей и ломал тесты/CI/любой импорт без полностью настроенного
окружения.
"""
from __future__ import annotations

import logging
import time

from dotenv import load_dotenv

from app.core.config import settings

load_dotenv()

logger = logging.getLogger(__name__)


# ─── Circuit-breaker ──────────────────────────────────────────────────────
# Защита от каскадных таймаутов: если ВСЯ цепочка LLM-провайдеров много раз
# подряд падает (rate-limit, 5xx, сеть), на cooldown_seconds открываем
# circuit — invoke сразу поднимает исключение, не дожидаясь httpx-таймаута.
# После cooldown пробуем снова.
class _CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 120.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        # half-open: первый запрос после cooldown пройдёт
        return time.monotonic() - self._opened_at < self.cooldown_seconds

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            if self._opened_at is None:
                logger.warning(
                    "LLM circuit breaker OPEN after %d consecutive failures (cooldown %ss)",
                    self._consecutive_failures, self.cooldown_seconds,
                )
            self._opened_at = time.monotonic()


_breaker = _CircuitBreaker()


class CircuitOpenError(RuntimeError):
    """Поднимается, когда circuit-breaker открыт и invoke не пытается ходить в LLM."""


# ─── Per-провайдер cooldown ───────────────────────────────────────────────
# Отдельная мини-логика поверх breaker'а: если конкретное звено в цепочке
# (например, Groq 70b на TPD-лимите) подряд 429-ит, отметим его как
# временно недоступное и будем пропускать в следующих вызовах, чтобы не
# тратить ~2 c на каждом запросе. Сбрасывается при половине cooldown'а.
_PROVIDER_COOLDOWN_S = 600.0   # 10 минут — типичная пауза для дневной квоты Groq
_PROVIDER_FAIL_THRESHOLD = 2
_provider_state: dict[str, dict] = {}


def _provider_should_skip(name: str) -> bool:
    st = _provider_state.get(name)
    if not st:
        return False
    if st["opened_at"] is None:
        return False
    if time.monotonic() - st["opened_at"] >= _PROVIDER_COOLDOWN_S:
        # cooldown истёк — даём шанс на retry
        _provider_state[name] = {"failures": 0, "opened_at": None}
        return False
    return True


def _provider_record_success(name: str) -> None:
    _provider_state[name] = {"failures": 0, "opened_at": None}


def _provider_record_failure(name: str) -> None:
    st = _provider_state.setdefault(name, {"failures": 0, "opened_at": None})
    st["failures"] += 1
    if st["failures"] >= _PROVIDER_FAIL_THRESHOLD and st["opened_at"] is None:
        st["opened_at"] = time.monotonic()
        logger.info(
            "LLM provider %s skipped for %.0fs after %d consecutive failures",
            name, _PROVIDER_COOLDOWN_S, st["failures"],
        )


# ─── Билдеры конкретных моделей ───────────────────────────────────────────


def _build_groq(model_name: str):
    from langchain_groq import ChatGroq
    return ChatGroq(
        model=model_name,
        temperature=settings.groq_temperature,
        max_retries=settings.groq_max_retries,
    )


def _build_gemini(model_name: str):
    from langchain_google_genai import ChatGoogleGenerativeAI
    # transport="rest": grpcio под капотом langchain-google-genai на части
    # macOS-сетапов (AdGuard, NextDNS, IPv6-only) не может разрезолвить
    # generativelanguage.googleapis.com — гонит 10-минутный hang, хотя
    # REST к тому же домену работает мгновенно. REST-транспорт обходит gRPC.
    # timeout=45: дефолтные 600s выливаются в десятки минут зависания,
    # за которые Supabase успевает закрыть idle SSL-сокет → PendingRollbackError.
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=settings.google_api_key,
        temperature=settings.groq_temperature,
        transport="rest",
        timeout=45,
    )


# ─── Автопроба Gemini-модели ──────────────────────────────────────────────
# Free-tier Google режет квоты конкретной модели без предупреждения (видели
# 20 RPD на 2.5-flash, 0 RPD на legacy 1.5-flash, etc.). Поэтому жёсткая
# привязка к одному имени = боль. Здесь — fallback-список, в котором сверху
# модели с самыми щедрыми ограничениями (lite/preview, потом стабильные).
# Можно перебить вручную через GOOGLE_MODEL в .env — тогда автопроба
# берёт ЕЁ первым кандидатом, fallback'и идут после.
_GEMINI_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
)

_PROBE_TIMEOUT_S = 8.0
_gemini_probe_cache: dict = {"done": False, "model": None}


def _probe_gemini_model() -> str | None:
    """Найти первую Gemini-модель, отвечающую 200 на минимальный запрос.

    Делается через REST один раз за процесс — результат кэшируется.
    Если GOOGLE_API_KEY пуст — возвращает None (Gemini выпадает из цепочки).
    Если ни одна модель не доступна (квоты по всем) — тоже None,
    тогда цепочка идёт сразу в Groq.
    """
    if not settings.google_api_key:
        return None

    import httpx

    candidates: list[str] = []
    # Если пользователь явно задал GOOGLE_MODEL — пробуем её первой
    if settings.google_model:
        candidates.append(settings.google_model)
    for m in _GEMINI_FALLBACK_MODELS:
        if m not in candidates:
            candidates.append(m)

    # Минимальный запрос: 5 output tokens — почти бесплатно по quota.
    body = {
        "contents": [{"parts": [{"text": "ok"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }
    base = "https://generativelanguage.googleapis.com/v1beta/models"
    for model in candidates:
        try:
            r = httpx.post(
                f"{base}/{model}:generateContent",
                params={"key": settings.google_api_key},
                json=body,
                timeout=_PROBE_TIMEOUT_S,
            )
            if r.status_code == 200:
                logger.info("Gemini auto-probe: selected '%s'", model)
                return model
            logger.debug(
                "Gemini auto-probe: %s -> HTTP %d", model, r.status_code,
            )
        except Exception as e:
            logger.debug("Gemini auto-probe: %s failed: %s", model, e)

    logger.warning(
        "Gemini auto-probe: ни одна модель не доступна — gemini пропускается "
        "(цепочка пойдёт сразу в Groq)",
    )
    return None


def _resolve_gemini_model() -> str | None:
    """Мемоизированная обёртка для probe — вызывается из _build_chain."""
    if not _gemini_probe_cache["done"]:
        _gemini_probe_cache["model"] = _probe_gemini_model()
        _gemini_probe_cache["done"] = True
    return _gemini_probe_cache["model"]


def reset_gemini_probe_cache() -> None:
    """Сбросить кэш probe — на случай ручного reload или после смены ключа."""
    _gemini_probe_cache["done"] = False
    _gemini_probe_cache["model"] = None


# Описание звена цепочки: имя для логов/cooldown, builder, condition (когда
# звено вообще включается — зависит от настроенных ключей).
class _ProviderLink:
    __slots__ = ("name", "build", "enabled", "_cached")

    def __init__(self, name: str, build, enabled: bool):
        self.name = name
        self.build = build
        self.enabled = enabled
        self._cached = None

    def model(self):
        if self._cached is None:
            self._cached = self.build()
        return self._cached


def _build_chain() -> list[_ProviderLink]:
    """Сформировать цепочку провайдеров согласно текущим settings.

    Gemini включается, только если автопроба нашла рабочую модель —
    иначе её звено пропускается и цепочка стартует с Groq.
    """
    gemini_model = _resolve_gemini_model()
    return [
        _ProviderLink(
            f"gemini:{gemini_model}" if gemini_model else "gemini",
            lambda m=gemini_model: _build_gemini(m) if m else None,
            enabled=bool(settings.google_api_key and gemini_model),
        ),
        _ProviderLink(
            f"groq:{settings.groq_model}",
            lambda: _build_groq(settings.groq_model),
            enabled=bool(settings.groq_api_key),
        ),
        _ProviderLink(
            f"groq:{settings.groq_fallback_model}",
            lambda: _build_groq(settings.groq_fallback_model),
            enabled=bool(settings.groq_api_key),
        ),
    ]


# ─── Основная обёртка ─────────────────────────────────────────────────────


class _LLMChain:
    """Цепочка LLM-провайдеров с одинаковым контрактом ChatGroq.

    invoke идёт по цепочке: первый, который не на cooldown и не падает,
    отдаёт ответ. Открытый circuit отрубает всё.

    `with_structured_output` навешивается на ПЕРВОЕ включённое звено
    (обычно Gemini): мы намеренно не дублируем его на fallback'е —
    при сбое схемы caller сам сваливается в rule-based ответ.
    """

    def __init__(self, tools: list | None = None) -> None:
        self._tools = tools
        self._chain: list[_ProviderLink] | None = None

    def _ensure_chain(self) -> list[_ProviderLink]:
        if self._chain is None:
            self._chain = [link for link in _build_chain() if link.enabled]
            if not self._chain:
                # На голодных тестах/CI без ключей — оставляем хотя бы пустую
                # цепочку, ошибка вылезет уже в invoke().
                logger.warning(
                    "LLM chain: ни один провайдер не настроен "
                    "(нет GOOGLE_API_KEY и GROQ_API_KEY)"
                )
        return self._chain or []

    def _bound(self, base):
        return base.bind_tools(self._tools) if self._tools else base

    def invoke(self, *args, **kwargs):
        if _breaker.is_open():
            raise CircuitOpenError("LLM circuit breaker is open — fast fail")

        chain = self._ensure_chain()
        if not chain:
            raise RuntimeError(
                "Нет настроенных LLM-провайдеров. Заполни GOOGLE_API_KEY или GROQ_API_KEY."
            )

        last_exc: Exception | None = None
        for link in chain:
            if _provider_should_skip(link.name):
                logger.debug("LLM chain: skipping %s (in cooldown)", link.name)
                continue
            try:
                model = self._bound(link.model())
                result = model.invoke(*args, **kwargs)
                _provider_record_success(link.name)
                _breaker.record_success()
                return result
            except Exception as e:
                last_exc = e
                logger.warning(
                    "LLM provider %s failed: %s; trying next in chain", link.name, e,
                )
                _provider_record_failure(link.name)
                continue

        # Все звенья упали — это сигнал для breaker'а.
        _breaker.record_failure()
        # Поднимаем последнее исключение, чтобы caller увидел причину.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM chain exhausted без exception — это баг")

    def with_structured_output(self, *args, **kwargs):
        """Structured output навешиваем на первое включённое звено.

        Не дублируем на fallback — caller'ы в try/except и сваливаются
        в rule-based ответ при сбое формата.
        """
        chain = self._ensure_chain()
        for link in chain:
            try:
                return link.model().with_structured_output(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    "structured_output build on %s failed: %s", link.name, e,
                )
                continue
        raise RuntimeError("Нет провайдера с поддержкой structured_output")

    def bind_tools(self, tools):
        # Новая цепочка с привязанными tools (тоже ленивая) — чтобы цепочка
        # с инструментами получала весь fallback.
        return _LLMChain(tools=tools)


llm = _LLMChain()
