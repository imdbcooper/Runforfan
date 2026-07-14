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
    telegram_bot_proxy_url: str | None = None
    telegram_polling_enabled: bool = False
    telegram_polling_timeout_seconds: int = 25
    telegram_polling_error_delay_seconds: int = 5
    frontend_url: str = "http://127.0.0.1:5173/app/"
    telegram_login_code_ttl_seconds: int = 300
    llm_timeout: int = 120
    llm_openai_max_tokens: int = 2400
    llm_image_preprocess_enabled: bool = True
    llm_image_jpeg_quality: int = 88
    llm_image_max_width: int = 1280
    import_recognition_worker_enabled: bool = True
    import_recognition_worker_poll_seconds: float = 5.0
    import_recognition_max_attempts: int = 3
    import_recognition_retry_delay_seconds: int = 45
    allow_private_llm_base_urls: bool = False
    derived_metrics_backfill_on_startup: bool = True
    derived_metrics_backfill_startup_limit: int = 500
    daily_training_load_backfill_on_startup: bool = True
    daily_training_load_backfill_days: int = 28
    daily_training_load_backfill_user_limit: int = 100
    coach_enabled: bool = False
    coach_llm_timeout: int = 20
    coach_llm_max_tokens: int = 900
    coach_turn_limit: int = 10
    coach_turn_window_minutes: int = 10
    coach_pending_turn_limit: int = 3
    coach_delivery_enabled: bool = False
    coach_delivery_worker_enabled: bool = False
    coach_delivery_poll_seconds: float = 30.0
    coach_delivery_batch_size: int = 25
    coach_delivery_max_attempts: int = 5
    coach_delivery_retry_base_seconds: int = 60

    model_config = SettingsConfigDict(
        env_prefix="RUNFORFAN_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
