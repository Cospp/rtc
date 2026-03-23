import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from session_control.app.api.session_routes import router as session_router
from session_control.app.core.config import settings
from session_control.app.core.logging import setup_logging
from session_control.app.redis.redis_client import close_redis, init_redis, ping_redis

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting session-control service...")
    await init_redis()

    try:
        redis_ok = await ping_redis()
        logger.info("Redis ping successful: %s", redis_ok)
    except Exception as exc:
        logger.exception("Redis ping failed during startup.")
        raise RuntimeError("Redis unavailable during startup") from exc

    yield

    logger.info("Shutting down session-control service...")
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.include_router(session_router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    try:
        redis_ok = await ping_redis()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc

    return {
        "service": settings.app_name,
        "status": "ok",
        "redis": redis_ok,
    }


@app.get("/metrics", tags=["system"])
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)