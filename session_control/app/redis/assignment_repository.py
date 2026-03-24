from redis.asyncio import Redis

from session_control.app.redis.lua_scripts import ASSIGN_WORKER_TO_SESSION_LUA


class AssignmentRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def assign_worker_to_session(
        self,
        session_id: str,
    ) -> str:
        worker_id = await self.redis.eval(
            ASSIGN_WORKER_TO_SESSION_LUA,
            1,
            "workers:warm",
            session_id,
        )

        return worker_id