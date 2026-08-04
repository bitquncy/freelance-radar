"""Configuration module for FreelanceRadar bot with Pydantic validation."""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Config(BaseSettings):
    """Application configuration with validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram Bot Configuration
    BOT_TOKEN: str = Field(..., min_length=1, description="Telegram bot token")
    OWNER_CHAT_ID: int = Field(..., gt=0, description="Telegram user ID of the owner")

    # AI Configuration (OpenAI or OpenRouter)
    OPENAI_API_KEY: str = Field(
        default="", description="OpenAI/OpenRouter API key (can be empty for testing)"
    )
    OPENAI_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Model name (e.g., gpt-4o-mini or openrouter model)",
    )
    OPENAI_BASE_URL: Optional[str] = Field(
        default=None, description="Custom base URL (e.g., https://openrouter.ai/api/v1)"
    )

    # Telegram User API (for Telethon - optional, HTTP parser is used by default)
    TELEGRAM_API_ID: Optional[int] = Field(
        default=None, description="Telegram API ID (optional)"
    )
    TELEGRAM_API_HASH: Optional[str] = Field(
        default=None, description="Telegram API hash (optional)"
    )

    # Database Configuration
    DB_PATH: str = Field(
        default="freelance_radar.db", description="SQLite database path"
    )

    # Kwork Parser Configuration
    KWORK_PROJECTS_URL: str = Field(
        default="https://kwork.ru/projects",
        description="Kwork projects URL",
    )
    KWORK_REQUEST_DELAY_MIN: float = Field(
        default=2.0, ge=0.1, description="Min request delay"
    )
    KWORK_REQUEST_DELAY_MAX: float = Field(
        default=5.0, ge=0.1, description="Max request delay"
    )
    KWORK_MAX_PAGES: int = Field(default=1, ge=1, description="Max pages to parse")
    KWORK_MAX_DETAIL_PAGES: int = Field(default=5, ge=1, description="Max detail pages")
    KWORK_DAILY_REQUEST_LIMIT: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Persistent global daily limit for Kwork HTTP pages",
    )

    # Monitoring Configuration
    MONITOR_INTERVAL_MINUTES: int = Field(
        default=15, ge=1, description="Monitor interval"
    )

    # Default Settings
    DEFAULT_COOLDOWN_SEC: int = Field(
        default=3600, ge=0, description="Default cooldown"
    )

    # Safe broadcast settings. The bot only posts to explicitly configured
    # destinations where it already has permission to send messages.
    BROADCAST_RATE_LIMIT: int = Field(
        default=10, ge=1, le=25, description="Maximum broadcast messages per second"
    )
    BROADCAST_BATCH_SIZE: int = Field(
        default=10, ge=1, le=25, description="Maximum targets processed concurrently"
    )
    BROADCAST_MAX_RETRIES: int = Field(
        default=3, ge=0, le=5, description="Retries for transient Telegram errors"
    )
    BROADCAST_PROGRESS_INTERVAL: int = Field(
        default=5, ge=5, le=60, description="Seconds between progress message edits"
    )
    BROADCAST_MIN_CHAT_INTERVAL_SEC: int = Field(
        default=3600,
        ge=60,
        description="Minimum interval between broadcast posts to one chat",
    )
    BROADCAST_TIMEZONE: str = Field(
        default="Asia/Yekaterinburg",
        description="Timezone used by broadcast scheduling UX",
    )

    # User-Agent for HTTP requests
    USER_AGENT: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        description="User-Agent header",
    )

    # --- FreelanceRadar V2 (AGENTS.md) ---
    RADAR_V2_ENABLED: bool = Field(
        default=False,
        description="Enable the V2 multi-tenant layer (AGENTS.md spec)",
    )
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///freelance_radar_v2.db",
        description="V2 database URL (PostgreSQL in production, AGENTS.md §4.2)",
    )
    ENVIRONMENT: str = Field(default="development")
    BOT_REPLICAS: int = Field(default=1, ge=1)
    REDIS_URL: Optional[str] = Field(
        default=None, description="Redis URL (dedup cache/queue, optional)"
    )
    OPENROUTER_API_KEY: str = Field(
        default="", description="OpenRouter API key (falls back to OPENAI_API_KEY)"
    )
    OPENROUTER_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1", description="OpenRouter base URL"
    )
    EXTRACTION_MODEL: str = Field(
        default="openai/gpt-4o-mini",
        description="Cheap model for per-listing extraction (AGENTS.md §6.1)",
    )
    GENERATION_MODEL: str = Field(
        default="anthropic/claude-3.5-sonnet",
        description="Strong model for proposal generation (AGENTS.md §6.1)",
    )
    TELETHON_API_ID: Optional[int] = Field(
        default=None, description="Telethon API id (dedicated account, §8)"
    )
    TELETHON_API_HASH: Optional[str] = Field(
        default=None, description="Telethon API hash"
    )
    TELETHON_SESSION_NAME: Optional[str] = Field(
        default=None, description="Telethon session name (never committed)"
    )
    YOOKASSA_SHOP_ID: Optional[str] = Field(
        default=None, description="ЮKassa shop id (site checkout, reserved)"
    )
    YOOKASSA_SECRET_KEY: Optional[str] = Field(
        default=None, description="ЮKassa secret key (site checkout, reserved)"
    )
    # Telegram Payments provider token (BotFather → Payments → ЮKassa).
    # Empty = payments disabled, manual /grant invoicing remains (MVP §14).
    PAYMENT_PROVIDER_TOKEN: str = Field(
        default="", description="Telegram Payments provider token (ЮKassa)"
    )
    PAYMENT_CURRENCY: str = Field(default="RUB", description="Invoice currency")

    @field_validator("KWORK_REQUEST_DELAY_MAX")
    @classmethod
    def delay_max_greater_than_min(cls, v: float, info) -> float:
        if (
            "KWORK_REQUEST_DELAY_MIN" in info.data
            and v < info.data["KWORK_REQUEST_DELAY_MIN"]
        ):
            raise ValueError(
                "KWORK_REQUEST_DELAY_MAX must be >= KWORK_REQUEST_DELAY_MIN"
            )
        return v

    @field_validator("PAYMENT_CURRENCY")
    @classmethod
    def payment_currency_is_rub(cls, value: str) -> str:
        value = value.upper()
        if value != "RUB":
            raise ValueError("Only RUB is supported by the current price table")
        return value

    def validate(self) -> None:
        """Validate that all required fields are set."""
        errors = []
        if not self.BOT_TOKEN:
            errors.append("BOT_TOKEN is not set")
        if not self.OWNER_CHAT_ID:
            errors.append("OWNER_CHAT_ID is not set")
        # OPENAI_API_KEY is optional for testing.
        if self.ENVIRONMENT.casefold() == "production":
            if not self.DATABASE_URL.startswith(("postgresql", "postgres://")):
                errors.append("DATABASE_URL must use PostgreSQL in production")
            if not self.REDIS_URL:
                errors.append("REDIS_URL is required in production")
            if self.BOT_REPLICAS != 1:
                errors.append("BOT_REPLICAS must be 1 in production")
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


# Legacy compatibility
BOT_TOKEN = get_config().BOT_TOKEN
OWNER_CHAT_ID = get_config().OWNER_CHAT_ID
OPENAI_API_KEY = get_config().OPENAI_API_KEY
OPENAI_MODEL = get_config().OPENAI_MODEL
OPENAI_BASE_URL = get_config().OPENAI_BASE_URL
TELEGRAM_API_ID = get_config().TELEGRAM_API_ID
TELEGRAM_API_HASH = get_config().TELEGRAM_API_HASH
DB_PATH = get_config().DB_PATH
KWORK_PROJECTS_URL = get_config().KWORK_PROJECTS_URL
KWORK_REQUEST_DELAY_MIN = get_config().KWORK_REQUEST_DELAY_MIN
KWORK_REQUEST_DELAY_MAX = get_config().KWORK_REQUEST_DELAY_MAX
KWORK_MAX_PAGES = get_config().KWORK_MAX_PAGES
KWORK_MAX_DETAIL_PAGES = get_config().KWORK_MAX_DETAIL_PAGES
KWORK_DAILY_REQUEST_LIMIT = get_config().KWORK_DAILY_REQUEST_LIMIT
MONITOR_INTERVAL_MINUTES = get_config().MONITOR_INTERVAL_MINUTES
DEFAULT_COOLDOWN_SEC = get_config().DEFAULT_COOLDOWN_SEC
BROADCAST_RATE_LIMIT = get_config().BROADCAST_RATE_LIMIT
BROADCAST_BATCH_SIZE = get_config().BROADCAST_BATCH_SIZE
BROADCAST_MAX_RETRIES = get_config().BROADCAST_MAX_RETRIES
BROADCAST_PROGRESS_INTERVAL = get_config().BROADCAST_PROGRESS_INTERVAL
BROADCAST_MIN_CHAT_INTERVAL_SEC = get_config().BROADCAST_MIN_CHAT_INTERVAL_SEC
BROADCAST_TIMEZONE = get_config().BROADCAST_TIMEZONE
USER_AGENT = get_config().USER_AGENT


def validate_config() -> None:
    """Validate configuration."""
    get_config().validate()
