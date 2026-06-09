from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://runforfan:runforfan@localhost:5432/runforfan"
    auto_create_schema: bool = True
    demo_seed: bool = True
    upload_dir: Path = Path("backend/app/storage/uploads")
    secret_key: str = "dev-secret-change-me"
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    frontend_url: str = "http://127.0.0.1:5173/app/"
    telegram_login_code_ttl_seconds: int = 300
    llm_timeout: int = 45
    allow_private_llm_base_urls: bool = False
    derived_metrics_backfill_on_startup: bool = True
    derived_metrics_backfill_startup_limit: int = 500
    daily_training_load_backfill_on_startup: bool = True
    daily_training_load_backfill_days: int = 28
    daily_training_load_backfill_user_limit: int = 100

    model_config = SettingsConfigDict(
        env_prefix="RUNFORFAN_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
