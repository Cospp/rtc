from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel


WorkerStatus = Literal["starting", "warm", "reserved", "active", "dead"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkerRecord(BaseModel):
    worker_id: str
    status: WorkerStatus
    endpoint: str
    last_heartbeat: str