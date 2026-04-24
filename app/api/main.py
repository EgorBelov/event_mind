from fastapi import FastAPI

from app.api.routers import users, events, recommendations, agent_recommendations, subscriptions

app = FastAPI(title="EventMind API")

app.include_router(users.router)
app.include_router(events.router)
app.include_router(recommendations.router)
app.include_router(agent_recommendations.router)
app.include_router(subscriptions.router)

@app.get("/")
def root():
    return {"message": "EventMind API is running"}

