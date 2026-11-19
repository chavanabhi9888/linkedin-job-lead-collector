"""Application settings, loaded from environment variables / .env (never hard-coded)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain import TimeFilter


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # Application
    app_env: str = "development"
    log_level: str = "INFO"
    log_json: bool = True
    api_key: SecretStr | None = None

    # Database
    # No credentials in code: set DATABASE_URL in .env (Postgres). Falls back to a local SQLite file.
    database_url: str = "sqlite+pysqlite:///data/leads.db"

    # Lead source selection ("linkedin" | "json_file")
    lead_source: str = "linkedin"
    json_source_path: Path | None = None

    # LinkedIn browser source
    linkedin_email: str | None = None
    linkedin_password: SecretStr | None = None
    linkedin_storage_state: Path = Path("data/linkedin_state.json")
    browser_headless: bool = True
    nav_timeout_ms: int = 30_000
    min_action_delay_s: float = 3.0
    max_action_delay_s: float = 7.0
    max_scrolls: int = 25
    max_retries: int = 3
    screenshot_dir: Path = Path("data/screenshots")

    # Defaults for scheduled / unspecified runs
    default_keyword: str = "Python Developer"
    default_location: str = "Pune, India"
    default_time_filter: TimeFilter = TimeFilter.PAST_24H
    default_max_posts: int = 50

    # Scheduler
    scheduler_enabled: bool = False
    scheduler_cron: str = "0 9 * * *"
    scheduler_timezone: str = "Asia/Kolkata"

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("api_key", "linkedin_password", "linkedin_email", "json_source_path", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    @model_validator(mode="after")
    def _check_delays(self) -> "Settings":
        if self.min_action_delay_s < 0 or self.max_action_delay_s < self.min_action_delay_s:
            raise ValueError("MAX_ACTION_DELAY_S must be >= MIN_ACTION_DELAY_S >= 0")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
