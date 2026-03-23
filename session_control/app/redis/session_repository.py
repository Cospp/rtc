import json

from redis.asyncio import Redis


class SessionRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def save_session(self, session_id: str, payload: str, ttl_seconds: int) -> None:
        await self.redis.set(
            name=f"session:{session_id}",
            value=payload,
            ex=ttl_seconds,
        )

    async def get_session(self, session_id: str) -> dict | None:
        data = await self.redis.get(f"session:{session_id}")
        if data is None:
            return None
        return json.loads(data)