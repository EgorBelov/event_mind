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

app = FastAPI(
    title="EventMind API",
    description="AI-driven IT event recommendations",
    version="1.0.0",
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
