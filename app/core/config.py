"""Application configuration via Pydantic BaseSettings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram
    bot_token: str = ""

    # Database
    database_url: str = "sqlite:///./eventmind.db"

    # API
    api_host: str = "http://localhost:8000"

    # Groq / LLM
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Dev flags
    debug: bool = False


settings = Settings()

# Convenience re-exports for legacy imports
BOT_TOKEN: str = settings.bot_token
DATABASE_URL: str = settings.database_url
API_HOST: str = settings.api_host
