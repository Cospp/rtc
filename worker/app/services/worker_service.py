import asyncio
import json
import logging
from datetime import datetime, timezone

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
        self._media_sessions: dict[str, dict] = {}

    async def _persist_media_stats(self, session_id: str, *, force: bool = False) -> None:
        state = self._media_sessions.get(session_id)
        if state is None:
            return

        now = datetime.now(timezone.utc)
        last_persisted_at = state.get("last_persisted_at")
        if not force and last_persisted_at:
            try:
                last_persisted = datetime.fromisoformat(last_persisted_at)
            except ValueError:
                last_persisted = None
            if last_persisted is not None:
                elapsed = (now - last_persisted).total_seconds()
                if elapsed < settings.worker_heartbeat_interval_seconds:
                    return

        payload = {
            "session_id": session_id,
            "worker_id": settings.worker_id,
            "total_packets": state["packets"],
            "total_bytes": state["bytes"],
            "last_ingested_at": state["last_ingested_at"],
            "last_persisted_at": now.isoformat(),
        }
        ttl_seconds = settings.worker_ttl_seconds + (
            settings.worker_heartbeat_interval_seconds * 3
        )
        await self.worker_repository.redis.set(
            f"session-media-worker:{session_id}",
            json.dumps(payload),
            ex=ttl_seconds,
        )
        state["last_persisted_at"] = payload["last_persisted_at"]

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
                if current_status in {WorkerStatus.RESERVED, WorkerStatus.ACTIVE} and assigned_session_id:
                    session_exists = await self.session_repository.exists(assigned_session_id)

                    if not session_exists:
                        await self._persist_media_stats(assigned_session_id, force=True)
                        self._media_sessions.pop(assigned_session_id, None)
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

    async def bind_media_session(self, session_id: str) -> dict:
        state = self._media_sessions.setdefault(
            session_id,
            {
                "session_id": session_id,
                "packets": 0,
                "bytes": 0,
                "last_ingested_at": None,
                "last_persisted_at": None,
            },
        )
        logger.info(
            "Worker media session bound | worker_id=%s session_id=%s",
            settings.worker_id,
            session_id,
        )
        return state

    async def ingest_media(self, session_id: str, payload: bytes) -> dict:
        state = await self.bind_media_session(session_id)
        state["packets"] += 1
        state["bytes"] += len(payload)
        state["last_ingested_at"] = utc_now_iso()
        await self._persist_media_stats(
            session_id,
            force=(state["packets"] == 1),
        )

        logger.info(
            "Worker media ingest | worker_id=%s session_id=%s packets=%s bytes=%s payload_size=%s",
            settings.worker_id,
            session_id,
            state["packets"],
            state["bytes"],
            len(payload),
        )

        return {
            "worker_id": settings.worker_id,
            "session_id": session_id,
            "packets": state["packets"],
            "bytes": state["bytes"],
            "last_ingested_at": state["last_ingested_at"],
        }
