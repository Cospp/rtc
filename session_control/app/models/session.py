from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


SessionStatus = Literal["requested", "assigned", "connecting", "streaming", "failed", "closed"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    stream_profile: str = Field(default="480p", min_length=1)
    transport: str = Field(default="udp", min_length=1)


class SessionRecord(BaseModel):
    session_id: str
    client_id: str
    status: SessionStatus
    stream_profile: str
    transport: str
    created_at: str
    worker_id: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    client_id: str
    status: SessionStatus
    ttl_seconds: int
    worker_id: str | None = None


def build_session_record(request: SessionRequest) -> SessionRecord:
    return SessionRecord(
        session_id=str(uuid4()),
        client_id=request.client_id,
        status="requested",
        stream_profile=request.stream_profile,
        transport=request.transport,
        created_at=utc_now_iso(),
        worker_id=None,
    )