"""Конфигурация приложения через Pydantic BaseSettings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram
    bot_token: str = ""

    # База данных
    database_url: str = "sqlite:///./eventmind.db"

    # API
    api_host: str = "http://localhost:8000"

    # Groq / LLM
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Dev-флаги
    debug: bool = False


settings = Settings()

# Удобные re-export'ы для legacy-импортов
BOT_TOKEN: str = settings.bot_token
DATABASE_URL: str = settings.database_url
API_HOST: str = settings.api_host
