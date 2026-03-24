from typing import Literal
from enum import Enum
from pydantic import BaseModel
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkerStatus(str, Enum):
    STARTING = "starting"
    WARM = "warm"
    RESERVED = "reserved"
    ACTIVE = "active"
    DEAD = "dead"


class WorkerRecord(BaseModel):
    worker_id: str
    status: WorkerStatus
    endpoint: str
    last_heartbeat: str
    assigned_session_id: str | None = None