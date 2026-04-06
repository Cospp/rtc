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
from session_control.app.redis.relay_repository import RelayRepository
from session_control.app.redis.session_repository import SessionRepository
from session_control.app.services.relay_client import RelayBindError, RelayClient

logger = logging.getLogger(__name__)


class NoRelayAvailableError(Exception):
    pass


class NoWorkerAvailableError(Exception):
    pass


class WorkerAssignmentError(Exception):
    pass


class RelayAssignmentError(Exception):
    pass


class RelayBindingError(Exception):
    pass


class SessionService:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.session_repository = SessionRepository(redis_client)
        self.assignment_repository = AssignmentRepository(redis_client)
        self.relay_repository = RelayRepository(redis_client)
        self.relay_client = RelayClient()

    async def create_session(self, request: SessionRequest) -> SessionResponse:
        session = build_session_record(request)
        session.status = "assigned"

        try:
            (
                relay_id,
                relay_internal_endpoint,
                worker_id,
            ) = await self.assignment_repository.assign_resources_to_session(
                session_id=session.session_id,
            )
        except ResponseError as exc:
            message = str(exc)

            if "NO_WARM_RELAY" in message:
                raise NoRelayAvailableError("No warm relays available") from exc

            if "NO_WARM_WORKER" in message:
                raise NoWorkerAvailableError("No warm workers available") from exc

            if "RELAY_NOT_FOUND" in message or "RELAY_NOT_WARM" in message:
                raise RelayAssignmentError(message) from exc

            if "WORKER_NOT_FOUND" in message or "WORKER_NOT_WARM" in message:
                raise WorkerAssignmentError(message) from exc

            raise

        session.relay_id = relay_id
        session.relay_internal_endpoint = relay_internal_endpoint
        session.worker_id = worker_id

        relay = await self.relay_repository.get_relay(relay_id)
        if relay is None:
            await self.assignment_repository.release_resources(
                relay_id=session.relay_id,
                worker_id=session.worker_id,
                session_id=session.session_id,
            )
            raise RelayAssignmentError(f"Assigned relay {relay_id} not found")

        session.relay_public_endpoint = relay.public_endpoint

        await self.session_repository.save_session(
            session_id=session.session_id,
            payload=session.model_dump_json(),
            ttl_seconds=settings.session_ttl_seconds,
        )

        try:
            await self.relay_client.bind_session(
                relay_internal_endpoint=relay_internal_endpoint,
                session_id=session.session_id,
                worker_id=session.worker_id,
            )
        except RelayBindError as exc:
            await self.session_repository.delete_session(session.session_id)
            await self.assignment_repository.release_resources(
                relay_id=session.relay_id,
                worker_id=session.worker_id,
                session_id=session.session_id,
            )
            raise RelayBindingError(str(exc)) from exc

        session.status = "connecting"
        await self.session_repository.save_session(
            session_id=session.session_id,
            payload=session.model_dump_json(),
            ttl_seconds=settings.session_ttl_seconds,
        )

        logger.info(
            "Session assigned and bound | session_id=%s client_id=%s relay_id=%s worker_id=%s",
            session.session_id,
            session.client_id,
            session.relay_id,
            session.worker_id,
        )

        return SessionResponse(
            session_id=session.session_id,
            client_id=session.client_id,
            status=session.status,
            ttl_seconds=settings.session_ttl_seconds,
            relay_id=session.relay_id,
            relay_public_endpoint=session.relay_public_endpoint,
            worker_id=session.worker_id,
        )

    async def get_session_raw(self, session_id: str) -> dict | None:
        return await self.session_repository.get_session(session_id)
