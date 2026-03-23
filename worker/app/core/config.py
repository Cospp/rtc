from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    worker_id: str = "worker-1"
    worker_host: str = "127.0.0.1"
    worker_port: int = 9000

    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_connect_timeout_seconds: float = 2.0

    worker_ttl_seconds: int = 15
    worker_heartbeat_interval_seconds: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()