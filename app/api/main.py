from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.core.logging import setup_logging
from app.core.config import settings
from app.api.routers import (
    users,
    events,
    recommendations,
    agent_recommendations,
    subscriptions,
    ingestion,
    admin,
    analytics,
    copilot,
    vocabulary,
)

setup_logging(debug=settings.debug)
logger = logging.getLogger(__name__)


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
    try:
        from app.recommender.embeddings import embed_text
        logger.info("Warming up sentence-transformers model…")
        embed_text("warmup")
        logger.info("Embeddings model ready")
    except Exception as e:
        logger.warning("Embedding model warmup failed (will lazy-load on first request): %s", e)
    yield


app = FastAPI(
    title="EventMind API",
    description="AI-driven IT event recommendations",
    version="1.0.0",
    lifespan=lifespan,
)

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


@app.get("/health", tags=["system"])
def healthcheck():
    return {"status": "ok"}


@app.get("/", tags=["system"])
def root():
    return {"message": "EventMind API", "docs": "/docs"}
