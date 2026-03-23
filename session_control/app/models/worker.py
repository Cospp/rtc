from typing import Literal

from pydantic import BaseModel


WorkerStatus = Literal["starting", "warm", "reserved", "active", "dead"]


class WorkerRecord(BaseModel):
    worker_id: str
    status: WorkerStatus
    endpoint: str
    last_heartbeat: str
    assigned_session_id: str | None = None