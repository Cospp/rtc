from fastapi import APIRouter, HTTPException

from session_control.app.models.session import SessionRequest, SessionResponse
from session_control.app.redis.redis_client import get_redis
from session_control.app.services.session_service import (
    NoWorkerAvailableError,
    SessionService,
    WorkerAssignmentError,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse)
async def create_session(request: SessionRequest) -> SessionResponse:
    redis_client = await get_redis()
    service = SessionService(redis_client)

    try:
        return await service.create_session(request)
    except NoWorkerAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WorkerAssignmentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict:
    redis_client = await get_redis()
    service = SessionService(redis_client)

    session = await service.get_session_raw(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return session