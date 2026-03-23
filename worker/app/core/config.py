import os
import uuid
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    worker_id: str = Field(...)

    worker_host: str = "0.0.0.0"
    worker_port: int = 9000

    redis_url: str = Field(default="redis://redis:6379/0")
    redis_connect_timeout_seconds: float = 2.0

    worker_ttl_seconds: int = 15
    worker_heartbeat_interval_seconds: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("worker_id")
    @classmethod
    def validate_worker_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("worker_id must not be empty")
        return normalized


settings = Settings()