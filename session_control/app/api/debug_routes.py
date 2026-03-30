from fastapi import APIRouter, HTTPException, Query

from session_control.app.redis.redis_client import get_redis
from session_control.app.services.worker_debug_service import (
    NoWorkerInPoolError,
    WorkerDebugService,
    WorkerKillError,
)

router = APIRouter(tags=["debug"])


@router.post("/debug/workers/kill-random")
async def kill_random_worker(
    pool: str = Query(..., pattern="^(warm|reserved)$"),
) -> dict:
    redis_client = await get_redis()
    service = WorkerDebugService(redis_client)

    try:
        return await service.kill_random_worker(pool)
    except NoWorkerInPoolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkerKillError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
