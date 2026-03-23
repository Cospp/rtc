import logging
from typing import Optional

import redis.asyncio as redis
from redis.asyncio import Redis

from worker.app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[Redis] = None


async def init_redis() -> Redis:
    global _redis_client

    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
        )
        logger.info("Worker Redis client initialized.")

    return _redis_client


async def get_redis() -> Redis:
    if _redis_client is None:
        return await init_redis()
    return _redis_client


async def ping_redis() -> bool:
    client = await get_redis()
    return await client.ping()


async def close_redis() -> None:
    global _redis_client

    if _redis_client is not None:
        await _redis_client.aclose()
        logger.info("Worker Redis client closed.")
        _redis_client = None