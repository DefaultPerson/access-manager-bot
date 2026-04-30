from environs import Env
from pydantic import ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Ignore extra fields from .env
    )

    # Required settings
    BOT_TOKEN: str = Field(..., description="Telegram bot API token")
    ADMIN_IDS: str = Field(
        ..., description="Comma-separated list of admin Telegram user IDs"
    )
    SUPPORT_URL: str = Field(..., description="Support URL")
    HEALTH_PORT: int = Field(8080, description="Health check port")

    # PostgreSQL settings
    POSTGRES_USER: str = Field(..., description="PostgreSQL username")
    POSTGRES_PASSWORD: str = Field(..., description="PostgreSQL password")
    POSTGRES_HOST: str = Field("localhost", description="PostgreSQL host")
    POSTGRES_PORT: int = Field(5432, description="PostgreSQL port")
    POSTGRES_DB: str = Field(..., description="PostgreSQL database name")

    # Redis settings
    REDIS_HOST: str = Field("localhost", description="Redis host")
    REDIS_PORT: int = Field(6379, description="Redis port")
    REDIS_DB: int = Field(0, description="Redis database number")

    # Logging settings
    LOG_CHAT_ID: int = Field(..., description="Telegram chat ID for admin logs")
    LOG_THREAD_ID: int | None = Field(
        None, description="Telegram thread ID for admin logs"
    )
    LOG_LEVEL: str = Field(
        "INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )

    # Application settings
    DEFAULT_LANG: str = Field("ru", description="Default language code (ru, en, ua)")
    GRACE_PERIOD_MINUTES: int = Field(
        180, description="Grace period for compliance violations in minutes (default 180 = 3h)"
    )

    # Scheduler settings
    COMPLIANCE_SCAN_TIME: str = Field(
        "03:00", description="Time (UTC) for daily compliance scan in HH:MM format"
    )
    GRACE_WATCHER_INTERVAL_MINUTES: int = Field(
        5, description="Interval in minutes for grace expiry watcher"
    )
    GRACE_RESTORATION_INTERVAL_MINUTES: int = Field(
        1, description="Interval in minutes for grace restoration watcher (auto-restore when users rejoin)"
    )

    # Broadcast settings (aiogram-broadcast)
    BROADCAST_RPS_DELAY: float = Field(
        0.05,
        description="Delay (seconds) between broadcast messages — 0.05 ≈ 20 msg/sec (Telegram cap is ~30)",
    )
    BROADCAST_MAX_RETRIES: int = Field(
        3, description="Max retries on transient TelegramAPIError during broadcast"
    )

    @property
    def admin_ids_list(self) -> list[int]:
        """Parse ADMIN_IDS into list of integers."""
        try:
            return [
                int(uid.strip()) for uid in self.ADMIN_IDS.split(",") if uid.strip()
            ]
        except ValueError as e:
            raise ValidationError(f"Invalid ADMIN_IDS format: {e}") from e

    @property
    def POSTGRES_DSN(self) -> str:  # noqa: N802 — env-style constant alias
        """Generate PostgreSQL connection string from components."""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def REDIS_DSN(self) -> str:  # noqa: N802 — env-style constant alias
        """Generate Redis connection string from components."""
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def compliance_scan_hour(self) -> int:
        """Parse hour from COMPLIANCE_SCAN_TIME."""
        try:
            hour, _ = self.COMPLIANCE_SCAN_TIME.split(":")
            return int(hour)
        except (ValueError, AttributeError) as e:
            raise ValidationError(f"Invalid COMPLIANCE_SCAN_TIME format (expected HH:MM): {e}") from e

    @property
    def compliance_scan_minute(self) -> int:
        """Parse minute from COMPLIANCE_SCAN_TIME."""
        try:
            _, minute = self.COMPLIANCE_SCAN_TIME.split(":")
            return int(minute)
        except (ValueError, AttributeError) as e:
            raise ValidationError(f"Invalid COMPLIANCE_SCAN_TIME format (expected HH:MM): {e}") from e


def load_settings() -> Settings:
    """Load and validate settings from environment."""
    env = Env()
    env.read_env()
    try:
        return Settings()
    except ValidationError as e:
        print(f"Configuration error: {e}")
        raise


# Global settings instance
settings = load_settings()
