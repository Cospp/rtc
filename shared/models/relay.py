from enum import Enum
from pydantic import BaseModel
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RelayStatus(str, Enum):
    STARTING = "starting"
    WARM = "warm"
    FULL = "full"
    DEGRADED = "degraded"
    DEAD = "dead"


class RelayRecord(BaseModel):
    relay_id: str
    status: RelayStatus
    public_endpoint: str | None = None
    internal_endpoint: str
    last_heartbeat: str
    current_sessions: int
    max_sessions: int
