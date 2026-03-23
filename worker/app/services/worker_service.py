import asyncio
import json
import logging

from worker.app.core.config import settings
from worker.app.models.worker import WorkerRecord, utc_now_iso
from worker.app.redis.worker_repository import WorkerRepository

logger = logging.getLogger(__name__)


class WorkerService:
    def __init__(self, repository: WorkerRepository) -> None:
        self.repository = repository
        self._heartbeat_task: asyncio.Task | None = None

    def build_worker_record(
        self,
        status: str = "warm",
        assigned_session_id: str | None = None,
        endpoint: str | None = None,
    ) -> WorkerRecord:
        return WorkerRecord(
            worker_id=settings.worker_id,
            status=status,
            endpoint=endpoint or f"{settings.worker_host}:{settings.worker_port}",
            last_heartbeat=utc_now_iso(),
            assigned_session_id=assigned_session_id,
        )

    async def register_worker(self) -> None:
        worker = self.build_worker_record(status="warm")
        await self.repository.upsert_worker(worker)

        logger.info(
            "Worker registered | worker_id=%s status=%s endpoint=%s",
            worker.worker_id,
            worker.status,
            worker.endpoint,
        )

    async def heartbeat_loop(self) -> None:
        while True:
            existing_raw = await self.repository.get_worker(settings.worker_id)

            if existing_raw is None:
                # Falls der Key fehlt, initial wieder als warm anlegen
                worker = self.build_worker_record(status="warm")
            else:
                existing = json.loads(existing_raw)

                worker = self.build_worker_record(
                    status=existing.get("status", "warm"),
                    assigned_session_id=existing.get("assigned_session_id"),
                    endpoint=existing.get("endpoint"),
                )

            await self.repository.upsert_worker(worker)

            logger.info(
                "Worker heartbeat | worker_id=%s status=%s assigned_session_id=%s",
                worker.worker_id,
                worker.status,
                worker.assigned_session_id,
            )

            await asyncio.sleep(settings.worker_heartbeat_interval_seconds)

    async def start_heartbeat(self) -> None:
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self.heartbeat_loop())

    async def stop_heartbeat(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None