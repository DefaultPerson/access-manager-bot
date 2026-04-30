import asyncio
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.logger import get_logger
from bot.core.redis_client import redis_manager
from bot.models import PolicyChannel

logger = get_logger(__name__)


class MembershipService:
    """Service for evaluating join requests and checking compliance with shared snapshots (FR-012a)."""

    def __init__(self, session: AsyncSession, bot: Bot):
        """Initialize membership service.

        Args:
            session: Database session
            bot: Telegram bot instance
        """
        self.session = session
        self.bot = bot

    async def check_compliance(
        self, policy_id: UUID, user_id: int
    ) -> tuple[bool, list[dict]]:
        """Check if user meets all requirements with shared membership caching.

        Args:
            policy_id: Policy UUID
            user_id: Telegram user ID

        Returns:
            Tuple of (is_compliant, missing_channels)
        """
        # Get all channels for policy (all channels are now required)
        result = await self.session.execute(
            select(PolicyChannel).where(
                PolicyChannel.policy_id == policy_id,
            )
        )
        required_channels = result.scalars().all()

        missing = []
        for channel in required_channels:
            # Check membership with shared snapshot cache (FR-012a)
            is_member = await self._check_membership_cached(
                channel.telegram_chat_id, user_id
            )
            if not is_member:
                missing.append(
                    {
                        "channel_id": channel.telegram_chat_id,
                        "display_name": channel.display_name,
                        "id": str(channel.id),
                    }
                )

        is_compliant = len(missing) == 0
        return is_compliant, missing

    async def _check_membership_cached(self, chat_id: int, user_id: int) -> bool:
        """Check membership with Redis caching to avoid redundant API calls (FR-012a).

        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID

        Returns:
            True if user is member, False otherwise
        """
        cache_key = f"membership:{chat_id}:{user_id}"

        # Try cache first
        try:
            cached = await redis_manager.redis.get(cache_key)
            if cached is not None:
                return cached == "1"
        except Exception as e:
            logger.warning("membership_cache_get_failed", error=str(e))

        # Fallback to live API call
        is_member = await self.check_membership_live(chat_id, user_id)

        # Cache result for 5 minutes
        try:
            await redis_manager.redis.setex(cache_key, 300, "1" if is_member else "0")
        except Exception as e:
            logger.warning("membership_cache_set_failed", error=str(e))

        return is_member

    async def check_membership_live(self, chat_id: int, user_id: int) -> bool:
        """Check membership via Telegram API.

        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID

        Returns:
            True if user is member, False otherwise
        """
        try:
            member = await self.bot.get_chat_member(chat_id, user_id)
            return member.status in ("member", "administrator", "creator")
        except TelegramBadRequest:
            return False
        except Exception as e:
            logger.error(
                "membership_check_failed",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return False

    async def approve_with_retry(
        self, chat_id: int, user_id: int, max_attempts: int = 3
    ) -> tuple[bool, dict | None]:
        """Approve join request with exponential backoff retry.

        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID
            max_attempts: Maximum retry attempts

        Returns:
            Tuple of (success, error_details)
        """
        for attempt in range(max_attempts):
            try:
                await self.bot.approve_chat_join_request(chat_id, user_id)
                logger.info(
                    "join_request_approved",
                    chat_id=chat_id,
                    user_id=user_id,
                    attempt=attempt + 1,
                )
                return True, None

            except TelegramRetryAfter as e:
                wait_time = e.retry_after
                logger.warning(
                    "telegram_rate_limit",
                    chat_id=chat_id,
                    user_id=user_id,
                    wait_seconds=wait_time,
                    attempt=attempt + 1,
                )
                if attempt < max_attempts - 1:
                    await asyncio.sleep(wait_time)
                else:
                    return False, {
                        "error": "rate_limit",
                        "retry_after": wait_time,
                        "attempts": max_attempts,
                    }

            except TelegramBadRequest as e:
                logger.error(
                    "approve_request_failed",
                    chat_id=chat_id,
                    user_id=user_id,
                    error=str(e),
                    attempt=attempt + 1,
                )
                return False, {
                    "error": "bad_request",
                    "message": str(e),
                    "attempts": attempt + 1,
                }

            except Exception as e:
                logger.error(
                    "approve_request_unexpected_error",
                    chat_id=chat_id,
                    user_id=user_id,
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt < max_attempts - 1:
                    await asyncio.sleep(2**attempt)  # Exponential backoff: 1s, 2s, 4s
                else:
                    return False, {
                        "error": "unexpected",
                        "message": str(e),
                        "attempts": max_attempts,
                    }

        return False, {"error": "max_retries_exceeded", "attempts": max_attempts}

    async def get_missing_channels(self, policy_id: UUID, user_id: int) -> list[dict]:
        """Get list of missing required channels for user.

        Args:
            policy_id: Policy UUID
            user_id: Telegram user ID

        Returns:
            List of missing channel dicts
        """
        _, missing = await self.check_compliance(policy_id, user_id)
        return missing

    async def invalidate_membership_cache(self, chat_id: int, user_id: int) -> None:
        """Invalidate cached membership for user in channel.

        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID
        """
        cache_key = f"membership:{chat_id}:{user_id}"
        try:
            await redis_manager.redis.delete(cache_key)
            logger.debug(
                "membership_cache_invalidated", chat_id=chat_id, user_id=user_id
            )
        except Exception as e:
            logger.warning("membership_cache_invalidate_failed", error=str(e))

    async def load_missing_channel_objects(
        self, missing_channels: list[dict]
    ) -> list[PolicyChannel]:
        """Load PolicyChannel objects from missing channel dicts.

        Args:
            missing_channels: List of dicts with 'id' keys from check_compliance

        Returns:
            List of PolicyChannel objects
        """
        missing_channel_ids = [UUID(ch["id"]) for ch in missing_channels]
        result = await self.session.execute(
            select(PolicyChannel).where(PolicyChannel.id.in_(missing_channel_ids))
        )
        return list(result.scalars().all())

    async def notify_existing_users_about_new_channel(
        self, policy_id: UUID, new_channel: PolicyChannel, i18n, grace_period_minutes: int
    ) -> tuple[int, int]:
        """Notify existing users with ACTIVE grants about new required channel.

        Args:
            policy_id: Policy UUID
            new_channel: Newly added PolicyChannel
            i18n: I18n instance for translations
            grace_period_minutes: Grace period duration in minutes

        Returns:
            Tuple of (affected_users_count, notified_users_count)
        """
        from datetime import datetime, timedelta, timezone

        from sqlalchemy.orm import selectinload

        from bot.models import AccessPolicy, EventType, GrantStatus, MembershipGrant
        from bot.services.audit_service import AuditService

        # Get policy
        result = await self.session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()
        if not policy:
            return 0, 0

        # Find all users with ACTIVE grants for this policy
        result = await self.session.execute(
            select(MembershipGrant)
            .options(selectinload(MembershipGrant.missing_channels))
            .where(
                MembershipGrant.policy_id == policy_id,
                MembershipGrant.status == GrantStatus.ACTIVE,
            )
            .with_for_update()
        )
        grants = result.scalars().all()

        if not grants:
            return 0, 0

        audit_service = AuditService(self.session, self.bot)
        affected_count = 0
        notified_count = 0
        grace_minutes = grace_period_minutes

        for grant in grants:
            user_id = grant.user_id

            # Check if user is subscribed to new channel
            is_member = await self._check_membership_cached(
                new_channel.telegram_chat_id, user_id
            )

            if not is_member:
                # User not subscribed - move to GRACE
                grant.status = GrantStatus.GRACE
                grant.missing_channels = [new_channel]
                grant.grace_expires_at = datetime.now(timezone.utc) + timedelta(
                    minutes=grace_period_minutes
                )
                grant.last_checked_at = datetime.now(timezone.utc)

                await audit_service.log_event(
                    EventType.GRACE_STARTED,
                    policy_id=policy_id,
                    user_id=user_id,
                    details={
                        "reason": "new_channel_added",
                        "channel_id": str(new_channel.id),
                        "channel_name": new_channel.display_name,
                    },
                )

                affected_count += 1

                # Send notification
                try:
                    text = i18n.gettext("new-channel-added-notification").format(
                        policy_name=policy.title,
                        channel_name=new_channel.display_name,
                        grace_minutes=grace_minutes,
                    )

                    from bot.keyboards.inline.channels import confirm_keyboard

                    keyboard = confirm_keyboard(i18n, str(policy_id))

                    await self.bot.send_message(user_id, text, reply_markup=keyboard)
                    notified_count += 1
                except Exception as e:
                    logger.warning(
                        "new_channel_notification_failed",
                        user_id=user_id,
                        policy_id=str(policy_id),
                        error=str(e),
                    )

        await self.session.flush()
        return affected_count, notified_count
