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

    # Ingestion: список RSS/Atom-лент через запятую.
    # Пример: RSS_FEEDS="https://example.com/feed.xml,https://other.org/rss"
    rss_feeds: str = ""

    # Периодический ingestion через APScheduler (часы между запусками)
    ingest_interval_hours: int = 6
    # Включать ли периодический ingestion вместе с digest-планировщиком
    ingest_enabled: bool = True
    # Лимит событий с Habr за один тик планировщика
    ingest_habr_limit: int = 20
    # Лимит событий на одну RSS-ленту за тик
    ingest_rss_limit_per_feed: int = 20

    @property
    def rss_feeds_list(self) -> list[str]:
        return [u.strip() for u in self.rss_feeds.split(",") if u.strip()]


settings = Settings()

# Удобные re-export'ы для legacy-импортов
BOT_TOKEN: str = settings.bot_token
DATABASE_URL: str = settings.database_url
API_HOST: str = settings.api_host
