from __future__ import annotations

import functools
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables.

    All fields can be overridden via env vars (uppercase field name).
    ``STRIPE_API_KEY`` is required; the run will fail fast with a
    ``ValidationError`` if it is absent, which is intentional — no silent
    fallback to an empty key that would produce confusing Stripe 401 errors.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    stripe_api_key: SecretStr
    db_path: Path = Field(default=Path("./orders.db"))
    # Stripe caps list endpoints at 100 items per page.
    stripe_page_size: int = Field(default=100, ge=1, le=100)
    max_retries: int = Field(default=5, ge=0)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached after first call)."""
    return Settings()
