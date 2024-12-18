"""Centralized, environment-based configuration.

All secrets come from environment variables. No secrets are ever hard-coded.
See .env.example at the repository root for the full list.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application ---
    app_name: str = "AI Evaluator Calibration & Disagreement Analytics"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False

    # --- Database ---
    # SQLite for local development; PostgreSQL in production deployments.
    database_url: str = "sqlite:///./eval_platform.db"
    db_echo: bool = False

    # --- Auth / JWT ---
    # MUST be overridden in production. generate with: openssl rand -hex 32
    jwt_secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    refresh_token_expire_days: int = 14
    # PBKDF2 iterations for password hashing (high enough to be slow for attackers).
    password_hash_iterations: int = 600_000

    # --- Security ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_per_minute: int = 60  # sensitive endpoints (auth)
    max_upload_mb: int = 25

    # --- Optional LLM assistance (disabled by default; core works fully offline) ---
    llm_provider: str | None = None  # openai | anthropic | openrouter | openai_compatible | ollama
    llm_api_key: str | None = None  # prefer env var; never log it
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_max_tokens: int = 2048
    llm_timeout_seconds: int = 30
    llm_max_requests_per_minute: int = 20
    llm_max_cost_usd: float = 5.0  # daily budget guard
    llm_enabled: bool = False  # must be explicitly turned on
    llm_allow_evaluation_content: bool = False  # explicit consent to send prompts/responses to providers

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlite_mode(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
