from redis.asyncio import Redis

from shared.models.relay import RelayRecord


class RelayRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def get_relay(self, relay_id: str) -> RelayRecord | None:
        data = await self.redis.get(f"relay:{relay_id}")
        if data is None:
            return None

        return self.get_relay_from_json(data)

    def get_relay_from_json(self, payload: str) -> RelayRecord:
        return RelayRecord.model_validate_json(payload)
