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
    # Shared-secret между ботом и API. Если пустой — авторизация выключена
    # (dev/тесты). На проде обязан быть задан в .env (читается middleware).
    api_shared_secret: str = ""

    # LLM-провайдеры. Цепочка: Gemini (если ключ задан) → Groq 70b → Groq 8b.
    # Первый в цепочке держит основную нагрузку, остальные подхватывают на
    # rate-limit/сбое. Подробнее — app/agents/recommendation/llm.py.

    # Google Gemini (рекомендуемый primary). Ключ — https://aistudio.google.com/app/apikey.
    # google_model пуст по умолчанию: на free-tier Google режет лимиты конкретной
    # модели без предупреждения (видели 20 RPD на 2.5-flash). llm.py делает
    # автопробу по списку кандидатов и берёт первую отвечающую 200 — выбранная
    # модель кэшируется до перезапуска. Чтобы зафиксировать модель руками
    # (платный tier, специфическая capability) — задай GOOGLE_MODEL в .env.
    google_api_key: str = ""
    google_model: str = ""

    # Groq: бесплатный, очень быстрый, но дневной лимит 100k токенов на 70b —
    # держим как fallback, чтобы не зависеть от одного провайдера.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # Резервная модель Groq: если 70b упала, переключаемся на 8b — меньше
    # параметров → дешевле/доступнее.
    groq_fallback_model: str = "llama-3.1-8b-instant"
    # Общая температура (применяется ко всем провайдерам в цепочке).
    groq_temperature: float = 0.4
    groq_max_retries: int = 2

    # Dev-флаги
    debug: bool = False

    # Ingestion: список RSS/Atom-лент через запятую.
    # Пример: RSS_FEEDS="https://example.com/feed.xml,https://other.org/rss"
    rss_feeds: str = ""

    # Дополнительные источники (см. app/ingestion/sources/*.py)
    luma_calendars: str = ""        # ICS-URL'ы Lu.ma через запятую
    meetup_token: str = ""          # OAuth Pro-token
    meetup_groups: str = ""         # urlname'ы групп через запятую
    tg_api_id: int | None = None
    tg_api_hash: str = ""
    tg_ingest_channels: str = ""    # @channel_user_1,@channel_user_2

    # Периодический ingestion через APScheduler (часы между запусками)
    ingest_interval_hours: int = 6
    # Включать ли периодический ingestion вместе с digest-планировщиком
    ingest_enabled: bool = True

    # ── Digest scheduler ────────────────────────────────────────────────
    # Интервал рассылки дайджеста в минутах. По умолчанию 24 ч.
    # Для разработки можно поставить, например, DIGEST_INTERVAL_MINUTES=10.
    digest_interval_minutes: int =  24 * 60
    # Запускать ли первый дайджест сразу при старте scheduler'а.
    # На проде = false, чтобы каждый рестарт не слал повторную рассылку.
    digest_run_on_startup: bool = False
    # Лимит событий с Habr за один тик планировщика
    ingest_habr_limit: int = 20
    # Лимит событий на одну RSS-ленту за тик
    ingest_rss_limit_per_feed: int = 20

    # ── Ranking weights (multi-objective hybrid_score) ──────────────────
    score_rule_weight: float = 0.5
    score_cosine_weight: float = 10.0
    score_bayes_weight: float = 5.0
    score_quality_weight: float = 0.5      # quality_score ∈ 1..10 → до +5
    score_hype_weight: float = 0.3         # hype_score ∈ 1..10 → до +3
    score_freshness_weight: float = 2.0    # freshness ∈ 0..1 → до +2
    score_skill_gap_weight: float = 3.0    # skill-gap ∈ 0..1 → до +3
    freshness_half_life_days: float = 30.0 # экспоненциальный decay

    # ── Diversity (MMR) ─────────────────────────────────────────────────
    mmr_lambda: float = 0.7                # 1.0 = pure relevance, 0.0 = pure diversity
    mmr_enabled: bool = True

    # ── Bayesian temporal decay ─────────────────────────────────────────
    bayes_decay_per_day: float = 0.995     # γ — медленный decay

    # ── Semantic deduplication ──────────────────────────────────────────
    dedup_enabled: bool = True
    dedup_threshold: float = 0.92          # cosine ≥ threshold → дубль

    # ── Recommendation cache (TTL в БД) ─────────────────────────────────
    # Кэш per-user снимает повторный пересчёт hybrid-скоринга на холодном
    # GET /recommendations (особенно ощутимо под Supabase). Инвалидируется
    # на feedback / edit профиля / analyze-bio.
    recommendation_cache_enabled: bool = True
    recommendation_cache_ttl_minutes: int = 15

    # ── LinUCB contextual bandit ────────────────────────────────────────
    bandit_enabled: bool = True
    bandit_weight: float = 2.0             # вес UCB-компонента в hybrid
    bandit_alpha: float = 1.0              # exploration coefficient

    # ── GNN (LightGCN) ──────────────────────────────────────────────────
    gnn_enabled: bool = False              # выключено по умолчанию (требует датасет)
    gnn_weight: float = 3.0
    gnn_embedding_dim: int = 32

    # ── Long-term memory agent ──────────────────────────────────────────
    memory_enabled: bool = True
    memory_min_salience: float = 4.0       # фильтр шумных заметок
    memory_compact_threshold: int = 50     # после стольких заметок — сжимаем

    @property
    def rss_feeds_list(self) -> list[str]:
        return [u.strip() for u in self.rss_feeds.split(",") if u.strip()]


settings = Settings()

# Удобные re-export'ы для legacy-импортов
BOT_TOKEN: str = settings.bot_token
DATABASE_URL: str = settings.database_url
API_HOST: str = settings.api_host
