import logging

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from session_control.app.core.config import settings
from session_control.app.models.session import (
    SessionRequest,
    SessionResponse,
    build_session_record,
)
from session_control.app.redis.assignment_repository import AssignmentRepository
from session_control.app.redis.session_repository import SessionRepository

logger = logging.getLogger(__name__)


class NoWorkerAvailableError(Exception):
    pass


class WorkerAssignmentError(Exception):
    pass


class SessionService:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.session_repository = SessionRepository(redis_client)
        self.assignment_repository = AssignmentRepository(redis_client)

    async def create_session(self, request: SessionRequest) -> SessionResponse:
        session = build_session_record(request)
        session.status = "assigned"

        try:
            worker_id, _worker_payload = await self.assignment_repository.assign_worker_to_session(
                session_id=session.session_id,
            )
        except ResponseError as exc:
            message = str(exc)

            if "NO_WARM_WORKER" in message:
                raise NoWorkerAvailableError("No warm workers available") from exc

            if "WORKER_NOT_FOUND" in message or "WORKER_NOT_WARM" in message:
                raise WorkerAssignmentError(message) from exc

            raise

        session.worker_id = worker_id

        await self.session_repository.save_session(
            session_id=session.session_id,
            payload=session.model_dump_json(),
            ttl_seconds=settings.session_ttl_seconds,
        )

        logger.info(
            "Session assigned atomically | session_id=%s client_id=%s worker_id=%s",
            session.session_id,
            session.client_id,
            session.worker_id,
        )

        return SessionResponse(
            session_id=session.session_id,
            client_id=session.client_id,
            status=session.status,
            ttl_seconds=settings.session_ttl_seconds,
            worker_id=session.worker_id,
        )

    async def get_session_raw(self, session_id: str) -> dict | None:
        return await self.session_repository.get_session(session_id)