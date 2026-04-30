from uuid import UUID

from bot.core.logger import get_logger
from bot.core.redis_client import redis_manager

logger = get_logger(__name__)


class CacheService:
    """Service for Redis-based caching and locking operations."""

    async def lock_eval(self, policy_id: UUID, user_id: int, timeout: int = 10) -> bool:
        """Acquire distributed lock for user-policy evaluation.

        Args:
            policy_id: Policy UUID
            user_id: Telegram user ID
            timeout: Lock timeout in seconds

        Returns:
            True if lock acquired, False otherwise
        """
        lock_key = f"eval_lock:{policy_id}:{user_id}"
        try:
            lock = redis_manager.redis.lock(lock_key, timeout=timeout)
            acquired = await lock.acquire(blocking=False)
            if acquired:
                logger.debug(
                    "eval_lock_acquired", policy_id=str(policy_id), user_id=user_id
                )
            else:
                logger.warning(
                    "eval_lock_failed", policy_id=str(policy_id), user_id=user_id
                )
            return acquired
        except Exception as e:
            logger.error(
                "lock_acquire_error",
                policy_id=str(policy_id),
                user_id=user_id,
                error=str(e),
            )
            return False

    async def unlock_eval(self, policy_id: UUID, user_id: int) -> None:
        """Release evaluation lock.

        Args:
            policy_id: Policy UUID
            user_id: Telegram user ID
        """
        lock_key = f"eval_lock:{policy_id}:{user_id}"
        try:
            await redis_manager.redis.delete(lock_key)
            logger.debug(
                "eval_lock_released", policy_id=str(policy_id), user_id=user_id
            )
        except Exception as e:
            logger.warning(
                "lock_release_error",
                policy_id=str(policy_id),
                user_id=user_id,
                error=str(e),
            )

    async def get_membership_cache(self, channel_id: int, user_id: int) -> bool | None:
        """Get cached membership status.

        Args:
            channel_id: Telegram chat ID
            user_id: Telegram user ID

        Returns:
            True/False if cached, None if not in cache
        """
        cache_key = f"membership:{channel_id}:{user_id}"
        try:
            cached = await redis_manager.redis.get(cache_key)
            if cached is None:
                return None
            return cached == "1"
        except Exception as e:
            logger.warning(
                "membership_cache_get_failed",
                channel_id=channel_id,
                user_id=user_id,
                error=str(e),
            )
            return None

    async def set_membership_cache(
        self, channel_id: int, user_id: int, is_member: bool, ttl: int = 300
    ) -> None:
        """Cache membership status.

        Args:
            channel_id: Telegram chat ID
            user_id: Telegram user ID
            is_member: Membership status
            ttl: Time to live in seconds
        """
        cache_key = f"membership:{channel_id}:{user_id}"
        try:
            await redis_manager.redis.setex(cache_key, ttl, "1" if is_member else "0")
            logger.debug(
                "membership_cached",
                channel_id=channel_id,
                user_id=user_id,
                is_member=is_member,
            )
        except Exception as e:
            logger.warning(
                "membership_cache_set_failed",
                channel_id=channel_id,
                user_id=user_id,
                error=str(e),
            )

    async def set_daily_cursor(self, policy_id: UUID, user_id: int) -> None:
        """Store cursor for daily safety scan.

        Args:
            policy_id: Policy UUID
            user_id: Last processed user ID
        """
        cursor_key = f"daily_audit:{policy_id}"
        try:
            await redis_manager.redis.set(cursor_key, str(user_id))
            logger.debug("daily_cursor_set", policy_id=str(policy_id), user_id=user_id)
        except Exception as e:
            logger.warning(
                "daily_cursor_set_failed", policy_id=str(policy_id), error=str(e)
            )

    async def get_daily_cursor(self, policy_id: UUID) -> int | None:
        """Get cursor for daily safety scan.

        Args:
            policy_id: Policy UUID

        Returns:
            Last processed user ID or None
        """
        cursor_key = f"daily_audit:{policy_id}"
        try:
            cursor = await redis_manager.redis.get(cursor_key)
            return int(cursor) if cursor else None
        except Exception as e:
            logger.warning(
                "daily_cursor_get_failed", policy_id=str(policy_id), error=str(e)
            )
            return None

    async def get_rate_limit(self, key: str) -> int:
        """Get current rate limit counter.

        Args:
            key: Rate limit key (e.g., 'approve', 'dm')

        Returns:
            Current count
        """
        rl_key = f"rl:{key}"
        try:
            count = await redis_manager.redis.get(rl_key)
            return int(count) if count else 0
        except Exception as e:
            logger.warning("rate_limit_get_failed", key=key, error=str(e))
            return 0

    async def increment_rate_limit(self, key: str, ttl: int = 60) -> int:
        """Increment rate limit counter.

        Args:
            key: Rate limit key
            ttl: Time to live in seconds

        Returns:
            New count
        """
        rl_key = f"rl:{key}"
        try:
            count = await redis_manager.redis.incr(rl_key)
            if count == 1:
                await redis_manager.redis.expire(rl_key, ttl)
            logger.debug("rate_limit_incremented", key=key, count=count)
            return count
        except Exception as e:
            logger.error("rate_limit_increment_failed", key=key, error=str(e))
            return 0
