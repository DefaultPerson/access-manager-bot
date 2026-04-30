from typing import AsyncIterator

import redis.asyncio as aioredis
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from bot.config.settings import settings
from bot.core.logger import get_logger

logger = get_logger(__name__)


class RedisManager:
    """Manages Redis connections and health checks."""

    def __init__(self) -> None:
        """Initialize Redis manager."""
        self._redis: Redis | None = None
        self._storage: RedisStorage | None = None

    async def connect(self) -> None:
        """Establish Redis connection."""
        try:
            self._redis = await aioredis.from_url(
                settings.REDIS_DSN,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
            )
            await self._redis.ping()
            logger.info("redis_connected", dsn=settings.REDIS_DSN.split("@")[-1])

            self._storage = RedisStorage.from_url(settings.REDIS_DSN)

        except RedisConnectionError as e:
            logger.error("redis_connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()
            logger.info("redis_disconnected")

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            if self._redis:
                await self._redis.ping()
                return True
            return False
        except RedisConnectionError:
            return False

    @property
    def redis(self) -> Redis:
        """Get Redis client instance."""
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._redis

    @property
    def storage(self) -> RedisStorage:
        """Get FSM storage for aiogram."""
        if not self._storage:
            raise RuntimeError("Redis storage not initialized. Call connect() first.")
        return self._storage

    async def lock(self, key: str, timeout: int = 10) -> AsyncIterator[bool]:
        """Acquire distributed lock."""
        lock = self.redis.lock(f"lock:{key}", timeout=timeout)
        try:
            acquired = await lock.acquire(blocking=True, blocking_timeout=timeout)
            yield acquired
        finally:
            if acquired:
                await lock.release()


redis_manager = RedisManager()
