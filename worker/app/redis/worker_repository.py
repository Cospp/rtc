from worker.app.core.config import settings
from worker.app.models.worker import WorkerRecord


class WorkerRepository:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def upsert_worker(self, worker: WorkerRecord) -> None:
        key = f"worker:{worker.worker_id}"
        await self.redis.set(
            name=key,
            value=worker.model_dump_json(),
            ex=settings.worker_ttl_seconds,
        )

    async def get_worker(self, worker_id: str) -> str | None:
        key = f"worker:{worker_id}"
        return await self.redis.get(key)