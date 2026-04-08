import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./eventmind.db"
)

API_HOST = os.getenv(
    "API_HOST",
    "http://localhost:8000"
)