from redis.asyncio import Redis

from session_control.app.redis.lua_scripts import (
    ASSIGN_RELAY_AND_WORKER_TO_SESSION_LUA,
    RELEASE_RELAY_AND_WORKER_LUA,
)


class AssignmentRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def assign_resources_to_session(
        self,
        session_id: str,
    ) -> tuple[str, str, str]:
        relay_id, relay_internal_endpoint, worker_id = await self.redis.eval(
            ASSIGN_RELAY_AND_WORKER_TO_SESSION_LUA,
            2,
            "relays:available",
            "workers:warm",
            session_id,
        )

        return relay_id, relay_internal_endpoint, worker_id

    async def release_resources(
        self,
        relay_id: str | None,
        worker_id: str | None,
        session_id: str,
    ) -> None:
        await self.redis.eval(
            RELEASE_RELAY_AND_WORKER_LUA,
            2,
            "relays:available",
            "workers:warm",
            relay_id or "",
            worker_id or "",
            session_id,
        )
