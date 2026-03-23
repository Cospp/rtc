import logging

from redis.asyncio import Redis

from session_control.app.core.config import settings
from session_control.app.models.session import (
    SessionRequest,
    SessionResponse,
    build_session_record,
)
from session_control.app.models.worker import WorkerRecord
from session_control.app.redis.session_repository import SessionRepository
from session_control.app.redis.worker_repository import WorkerRepository

logger = logging.getLogger(__name__)


class NoWorkerAvailableError(Exception):
    pass


class SessionService:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.session_repository = SessionRepository(redis_client)
        self.worker_repository = WorkerRepository(redis_client)

    async def create_session(self, request: SessionRequest) -> SessionResponse:
        warm_worker_ids = await self.worker_repository.get_warm_worker_ids()
        if not warm_worker_ids:
            raise NoWorkerAvailableError("No warm workers available")

        selected_worker_id = warm_worker_ids[0]
        worker = await self.worker_repository.get_worker(selected_worker_id)

        if worker is None:
            raise NoWorkerAvailableError("Selected worker no longer exists")

        session = build_session_record(request)
        session.status = "assigned"
        session.worker_id = worker.worker_id

        worker.status = "reserved"
        worker.assigned_session_id = session.session_id

        await self.session_repository.save_session(
            session_id=session.session_id,
            payload=session.model_dump_json(),
            ttl_seconds=settings.session_ttl_seconds,
        )

        await self.worker_repository.save_worker(
            worker=worker,
            ttl_seconds=settings.session_ttl_seconds,
        )

        logger.info(
            "Session assigned | session_id=%s client_id=%s worker_id=%s",
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