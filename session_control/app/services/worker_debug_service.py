import json
import random
import ssl
from pathlib import Path
from urllib import error, request

from redis.asyncio import Redis

from shared.models.worker import WorkerStatus, utc_now_iso
from session_control.app.core.config import settings
from session_control.app.redis.worker_repository import WorkerRepository


class NoWorkerInPoolError(Exception):
    pass


class WorkerKillError(Exception):
    pass


class WorkerDebugService:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self.worker_repository = WorkerRepository(redis_client)

    async def kill_random_worker(self, pool: str) -> dict:
        candidates = await self._get_candidates(pool)
        if not candidates:
            raise NoWorkerInPoolError(f"No workers available in pool '{pool}'")

        worker = random.choice(candidates)
        worker.status = WorkerStatus.DEAD
        worker.last_heartbeat = utc_now_iso()

        await self.worker_repository.save_worker(
            worker,
            ttl_seconds=settings.dead_worker_ttl_seconds,
        )

        delete_attempted = False
        delete_result = "not_attempted"
        if self._running_in_kubernetes():
            delete_attempted = True
            delete_result = await self._delete_worker_pod(worker.worker_id)

        return {
            "worker_id": worker.worker_id,
            "previous_pool": pool,
            "status": worker.status.value,
            "assigned_session_id": worker.assigned_session_id,
            "pod_delete_attempted": delete_attempted,
            "pod_delete_result": delete_result,
        }

    async def _get_candidates(self, pool: str) -> list:
        worker_keys = sorted(await self.redis.keys("worker:*"))
        workers = []

        for worker_key in worker_keys:
            worker_raw = await self.redis.get(worker_key)
            if worker_raw is None:
                continue

            worker = self.worker_repository.get_worker_from_json(worker_raw)
            if pool == "warm" and worker.status == WorkerStatus.WARM:
                workers.append(worker)
            if pool == "reserved" and worker.status == WorkerStatus.RESERVED:
                workers.append(worker)

        return workers

    def _running_in_kubernetes(self) -> bool:
        return bool(
            Path("/var/run/secrets/kubernetes.io/serviceaccount/token").exists()
            and Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt").exists()
        )

    async def _delete_worker_pod(self, pod_name: str) -> str:
        token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        ca_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
        token = token_path.read_text(encoding="utf-8").strip()

        host = "https://kubernetes.default.svc"
        namespace = settings.kubernetes_namespace
        url = f"{host}/api/v1/namespaces/{namespace}/pods/{pod_name}"

        req = request.Request(
            url,
            method="DELETE",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

        ssl_context = ssl.create_default_context(cafile=str(ca_path))

        try:
            with request.urlopen(req, context=ssl_context, timeout=5) as response:
                if 200 <= response.status < 300:
                    return "deleted"
                return f"unexpected_status:{response.status}"
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            try:
                payload = json.loads(body)
                message = payload.get("message", exc.reason)
            except json.JSONDecodeError:
                message = body or exc.reason
            raise WorkerKillError(f"Kubernetes pod delete failed: {message}") from exc
        except Exception as exc:
            raise WorkerKillError(f"Kubernetes pod delete failed: {exc}") from exc
