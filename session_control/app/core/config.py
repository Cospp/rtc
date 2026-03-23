from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "session-control"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_debug: bool = True

    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_connect_timeout_seconds: float = 2.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()