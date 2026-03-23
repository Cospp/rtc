import json
import logging

from redis.asyncio import Redis

from session_control.app.core.config import settings
from session_control.app.models.session import (
    SessionRequest,
    SessionResponse,
    build_session_record,
)

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def create_session(self, request: SessionRequest) -> SessionResponse:
        session = build_session_record(request)

        redis_key = f"session:{session.session_id}"
        payload = session.model_dump_json()

        await self.redis.set(
            name=redis_key,
            value=payload,
            ex=settings.session_ttl_seconds,
        )

        logger.info(
            "Session created | session_id=%s client_id=%s status=%s",
            session.session_id,
            session.client_id,
            session.status,
        )

        return SessionResponse(
            session_id=session.session_id,
            client_id=session.client_id,
            status=session.status,
            ttl_seconds=settings.session_ttl_seconds,
        )

    async def get_session_raw(self, session_id: str) -> dict | None:
        redis_key = f"session:{session_id}"
        data = await self.redis.get(redis_key)

        if data is None:
            return None

        return json.loads(data)