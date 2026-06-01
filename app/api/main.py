import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.middleware import install_middleware_and_handlers
from app.api.routers import (
    admin,
    agent_recommendations,
    analytics,
    copilot,
    events,
    ingestion,
    recommendations,
    subscriptions,
    users,
    vocabulary,
)
from app.core.config import settings
from app.core.config_validate import validate_config
from app.core.logging import setup_logging
from app.db.dependencies import get_db

setup_logging(debug=settings.debug)
logger = logging.getLogger(__name__)

# Не valid_or_exit: импорт `app.api.main` происходит во многих местах (тесты,
# alembic), и жёсткий sys.exit там лишний. Strict=False пишет WARNING — uvicorn
# на проде поднимется только если ENV заполнен. Прод-валидация — на старте
# процесса (validate_or_exit) в run-скриптах/docker-entrypoint.
validate_config("api", strict=False)

# Глобальный флаг прогрева — выставляется в lifespan и читается /health.
_EMBEDDING_READY = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Прогрев sentence-transformers модели при старте процесса.

    Без этого первый /recommendations упирается в 25-30 c загрузки модели
    (PyTorch + ~80MB весов), и бот ловит httpx-timeout. Один лишний
    embed_text('warmup') стоит ~5-10 c единоразово при boot, а все
    последующие запросы летят за <1 c.

    Best-effort: если sentence-transformers недоступен — пропускаем
    без падения API.
    """
    global _EMBEDDING_READY
    try:
        from app.recommender.embeddings import embed_text
        logger.info("Warming up sentence-transformers model…")
        embed_text("warmup")
        _EMBEDDING_READY = True
        logger.info("Embeddings model ready")
    except Exception as e:
        logger.warning("Embedding model warmup failed (will lazy-load on first request): %s", e)

    # Параллельно — probe Gemini-модели: иначе первый запрос платил бы
    # за HTTP-пробы цепочки моделей (~1-3 c). Делается через REST, в кэше
    # держится имя выбранной модели до перезапуска процесса.
    try:
        from app.agents.recommendation.llm import _resolve_gemini_model
        picked = _resolve_gemini_model()
        if picked:
            logger.info("Gemini ready: model='%s'", picked)
        else:
            logger.info("Gemini не доступна — цепочка LLM пойдёт сразу в Groq")
    except Exception as e:
        logger.warning("Gemini probe failed: %s", e)

    yield


app = FastAPI(
    title="EventMind API",
    description="AI-driven IT event recommendations",
    version="1.0.0",
    lifespan=lifespan,
)

# Request-логи с timing'ами + единый формат для HTTPException 4xx/5xx
# (raw FastAPI access-log не различает 404 как нормальную бизнес-ветку
# и пишет traceback для каждого).
install_middleware_and_handlers(app)

app.include_router(users.router)
app.include_router(events.router)
app.include_router(recommendations.router)
app.include_router(agent_recommendations.router)
app.include_router(subscriptions.router)
app.include_router(ingestion.router)
app.include_router(admin.router)
app.include_router(analytics.router)
app.include_router(copilot.router)
app.include_router(vocabulary.router)


def _check_db(db: Session) -> dict:
    """SELECT 1 + длительность в миллисекундах."""
    t0 = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000, 2)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _check_embeddings() -> dict:
    """Эмбеддинг-модель прогрета? Если нет — пробуем загрузить, не падая."""
    if _EMBEDDING_READY:
        return {"ok": True, "warmed_up": True}
    # Не прогрелись на старте — мягко пробуем сейчас, но не блокируем health.
    try:
        from app.recommender.embeddings import get_model
        get_model()
        return {"ok": True, "warmed_up": False, "lazy_loaded": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _check_llm() -> dict:
    """LLM-цепочка: проверяем что хоть один провайдер настроен,
    показываем выбранную Gemini-модель (если автопроба нашла) и Groq
    fallback'и. Полноценный invoke здесь не делаем — дорого и потенциально
    тратит TPD-лимит.
    """
    if not settings.groq_api_key and not settings.google_api_key:
        return {"ok": False, "error": "ни GROQ_API_KEY, ни GOOGLE_API_KEY не заданы"}
    try:
        from app.agents.recommendation.llm import _resolve_gemini_model, llm
        gemini_model = _resolve_gemini_model() if settings.google_api_key else None
        return {
            "ok": True,
            "gemini_model": gemini_model,
            "groq_primary": settings.groq_model if settings.groq_api_key else None,
            "groq_fallback": settings.groq_fallback_model if settings.groq_api_key else None,
            "wrapper": type(llm).__name__,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@app.get("/health", tags=["system"])
def healthcheck(db: Session = Depends(get_db)):
    """Композитный healthcheck.

    Возвращает {status: ok|degraded, components: {...}}.
    Status=ok если все компоненты ok, иначе degraded (с деталями).
    """
    components = {
        "db": _check_db(db),
        "embeddings": _check_embeddings(),
        "llm": _check_llm(),
    }
    overall_ok = all(c.get("ok") for c in components.values())
    return {
        "status": "ok" if overall_ok else "degraded",
        "components": components,
    }


@app.get("/", tags=["system"])
def root():
    return {"message": "EventMind API", "docs": "/docs", "health": "/health"}


@app.post("/admin/llm/reprobe", tags=["system"])
def reprobe_gemini():
    """Сбросить кэш автопробы Gemini и выбрать модель заново.

    Полезно после смены GOOGLE_API_KEY или когда квоты на текущую
    выбранную модель закончились и хочется переключиться на следующую
    без рестарта uvicorn.
    """
    from app.agents.recommendation.llm import (
        _resolve_gemini_model,
        reset_gemini_probe_cache,
    )
    reset_gemini_probe_cache()
    picked = _resolve_gemini_model()
    return {"selected": picked}
