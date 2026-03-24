import asyncio
import logging

from worker.app.core.config import settings
from shared.models.worker import WorkerRecord, WorkerStatus, utc_now_iso
from worker.app.redis.session_repository import SessionRepository
from worker.app.redis.worker_repository import WorkerRepository

logger = logging.getLogger(__name__)


class WorkerService:
    def __init__(
        self,
        worker_repository: WorkerRepository,
        session_repository: SessionRepository,
    ) -> None:
        self.worker_repository = worker_repository
        self.session_repository = session_repository
        self._heartbeat_task: asyncio.Task | None = None

    def build_worker_record(
        self,
        status: WorkerStatus = WorkerStatus.WARM,
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
        worker = self.build_worker_record(status=WorkerStatus.WARM)
        await self.worker_repository.upsert_worker(worker)

        logger.info(
            "Worker registered | worker_id=%s status=%s endpoint=%s",
            worker.worker_id,
            worker.status,
            worker.endpoint,
        )

    async def heartbeat_loop(self) -> None:
        while True:
            existing = await self.worker_repository.get_worker(settings.worker_id)

            if existing is None:
                worker = self.build_worker_record(status=WorkerStatus.WARM)
            else:
                current_status = existing.status
                assigned_session_id = existing.assigned_session_id
                endpoint = existing.endpoint

                # Release-Logik
                if current_status == WorkerStatus.RESERVED and assigned_session_id:
                    session_exists = await self.session_repository.exists(assigned_session_id)

                    if not session_exists:
                        logger.info(
                            "Releasing worker because assigned session expired | worker_id=%s session_id=%s",
                            settings.worker_id,
                            assigned_session_id,
                        )
                        current_status = WorkerStatus.WARM
                        assigned_session_id = None

                worker = self.build_worker_record(
                    status=current_status,
                    assigned_session_id=assigned_session_id,
                    endpoint=endpoint,
                )

            await self.worker_repository.upsert_worker(worker)

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