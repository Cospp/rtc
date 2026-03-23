from redis.asyncio import Redis


class SessionRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def exists(self, session_id: str) -> bool:
        key = f"session:{session_id}"
        return bool(await self.redis.exists(key))