from redis.asyncio import Redis

from shared.models.relay import RelayRecord, RelayStatus


class RelayRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def get_available_relay_ids(self) -> list[str]:
        relay_ids = await self.redis.smembers("relays:available")
        return list(relay_ids)

    async def get_relay(self, relay_id: str) -> RelayRecord | None:
        data = await self.redis.get(f"relay:{relay_id}")
        if data is None:
            return None

        return self.get_relay_from_json(data)

    def get_relay_from_json(self, payload: str) -> RelayRecord:
        return RelayRecord.model_validate_json(payload)

    async def save_relay(self, relay: RelayRecord, ttl_seconds: int) -> None:
        await self.redis.set(
            name=f"relay:{relay.relay_id}",
            value=relay.model_dump_json(),
            ex=ttl_seconds,
        )

        if relay.status == RelayStatus.WARM:
            await self.redis.sadd("relays:available", relay.relay_id)
        else:
            await self.redis.srem("relays:available", relay.relay_id)
