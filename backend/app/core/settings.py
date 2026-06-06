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
    llm_timeout: int = 45

    model_config = SettingsConfigDict(
        env_prefix="RUNFORFAN_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
