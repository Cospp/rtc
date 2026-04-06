from redis.asyncio import Redis

from shared.models.worker import WorkerRecord, WorkerStatus


class WorkerRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def get_worker(self, worker_id: str) -> WorkerRecord | None:
        data = await self.redis.get(f"worker:{worker_id}")
        if data is None:
            return None

        return self.get_worker_from_json(data)

    def get_worker_from_json(self, payload: str) -> WorkerRecord:
        return WorkerRecord.model_validate_json(payload)

    async def save_worker(self, worker: WorkerRecord, ttl_seconds: int) -> None:
        await self.redis.set(
            name=f"worker:{worker.worker_id}",
            value=worker.model_dump_json(),
            ex=ttl_seconds,
        )

        if worker.status == WorkerStatus.WARM:
            await self.redis.sadd("workers:warm", worker.worker_id)
        else:
            await self.redis.srem("workers:warm", worker.worker_id)
