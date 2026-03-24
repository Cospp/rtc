from redis.asyncio import Redis

from worker.app.core.config import settings
from shared.models.worker import WorkerRecord, WorkerStatus


class WorkerRepository:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def upsert_worker(self, worker: WorkerRecord) -> None:
        key = f"worker:{worker.worker_id}"
        await self.redis.set(
            name=key,
            value=worker.model_dump_json(),
            ex=settings.worker_ttl_seconds,
        )

        # Worker hält den Warm-Index selbst aktuell
        if worker.status == WorkerStatus.WARM:
            await self.redis.sadd("workers:warm", worker.worker_id)
        else:
            await self.redis.srem("workers:warm", worker.worker_id)

    async def get_worker(self, worker_id: str) -> WorkerRecord | None:
        key = f"worker:{worker_id}"
        data = await self.redis.get(key)
        if data is None:
            return None

        return WorkerRecord.model_validate_json(data)