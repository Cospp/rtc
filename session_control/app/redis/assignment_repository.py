import json

from redis.asyncio import Redis

from session_control.app.redis.lua_scripts import ASSIGN_WORKER_TO_SESSION_LUA


class AssignmentRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def assign_worker_to_session(
        self,
        session_id: str,
        worker_ttl_seconds: int,
    ) -> tuple[str, dict]:
        result = await self.redis.eval(
            ASSIGN_WORKER_TO_SESSION_LUA,
            1,
            "workers:warm",
            session_id,
            worker_ttl_seconds,
        )

        worker_id = result[0]
        worker_payload = json.loads(result[1])

        return worker_id, worker_payload