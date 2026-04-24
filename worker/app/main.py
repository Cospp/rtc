import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from worker.app.core.config import settings
from worker.app.redis.redis_client import close_redis, init_redis, ping_redis
from worker.app.redis.session_repository import SessionRepository
from worker.app.redis.worker_repository import WorkerRepository
from worker.app.services.worker_service import MediaSessionAccessError, WorkerService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting worker service...")

    redis_client = await init_redis()

    try:
        redis_ok = await ping_redis()
        logger.info("Worker Redis ping successful: %s", redis_ok)
    except Exception as exc:
        logger.exception("Worker Redis ping failed during startup.")
        raise RuntimeError("Redis unavailable during worker startup") from exc

    worker_repository = WorkerRepository(redis_client)
    session_repository = SessionRepository(redis_client)
    service = WorkerService(worker_repository, session_repository)

    await service.register_worker()
    await service.start_heartbeat()

    app.state.worker_service = service

    yield

    logger.info("Shutting down worker service...")
    await service.stop_heartbeat()
    await close_redis()


app = FastAPI(title=f"worker-{settings.worker_id}", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    try:
        redis_ok = await ping_redis()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc

    return {
        "worker_id": settings.worker_id,
        "status": "ok",
        "redis": redis_ok,
    }


@app.post("/internal/v1/media/bind/{session_id}")
async def bind_media_session(session_id: str) -> dict:
    service: WorkerService = app.state.worker_service
    try:
        return await service.bind_media_session(session_id)
    except MediaSessionAccessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/internal/v1/media/ingest/{session_id}")
async def ingest_media(session_id: str, request: Request) -> dict:
    service: WorkerService = app.state.worker_service
    payload = await request.body()
    try:
        return await service.ingest_media(session_id, payload)
    except MediaSessionAccessError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
