from fastapi import FastAPI

from app.api.routers import users, events, recommendations

app = FastAPI(title="EventMind API")

app.include_router(users.router)
app.include_router(events.router)
app.include_router(recommendations.router)


@app.get("/")
def root():
    return {"message": "EventMind API is running"}