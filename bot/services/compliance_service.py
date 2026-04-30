"""Compliance enforcement service for grace periods and revocations."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.config.settings import settings
from bot.core.logger import get_logger
from bot.models import GrantStatus, MembershipGrant, PolicyChannel

logger = get_logger(__name__)


class ComplianceService:
    """Service for managing compliance grace periods and revocations."""

    def __init__(self, session: AsyncSession, bot: Bot):
        """Initialize compliance service.

        Args:
            session: Database session
            bot: Telegram bot instance
        """
        self.session = session
        self.bot = bot

    async def start_grace_period(
        self, grant_id: UUID, missing_channels: list[dict]
    ) -> MembershipGrant:
        """Start grace period for non-compliant user.

        Args:
            grant_id: MembershipGrant UUID
            missing_channels: List of missing channel dicts with 'id' (channel UUID)

        Returns:
            Updated MembershipGrant
        """
        result = await self.session.execute(
            select(MembershipGrant)
            .options(selectinload(MembershipGrant.missing_channels))
            .where(MembershipGrant.id == grant_id)
        )
        grant = result.scalar_one()

        grace_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.GRACE_PERIOD_MINUTES
        )

        grant.status = GrantStatus.GRACE
        grant.grace_expires_at = grace_expires_at
        grant.last_checked_at = datetime.now(timezone.utc)

        # Load PolicyChannel objects and assign to relationship
        channel_ids = [UUID(ch["id"]) for ch in missing_channels if "id" in ch]
        if channel_ids:
            result = await self.session.execute(
                select(PolicyChannel).where(PolicyChannel.id.in_(channel_ids))
            )
            channels = result.scalars().all()
            grant.missing_channels = channels

        await self.session.flush()

        logger.info(
            "grace_period_started",
            grant_id=str(grant_id),
            user_id=grant.user_id,
            expires_at=grace_expires_at.isoformat(),
            missing_count=len(missing_channels),
        )
        return grant

    async def revoke_expired_grants(self) -> list[MembershipGrant]:
        """Find and revoke all expired grace periods.

        Returns:
            List of revoked grants
        """
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(MembershipGrant)
            .options(selectinload(MembershipGrant.policy))
            .where(
                MembershipGrant.status == GrantStatus.GRACE,
                MembershipGrant.grace_expires_at <= now,
            )
        )
        expired_grants = result.scalars().all()

        revoked = []
        for grant in expired_grants:
            try:
                await self.remove_and_unban(
                    grant.policy.protected_chat_id, grant.user_id
                )
                grant.status = GrantStatus.REVOKED
                grant.last_checked_at = now
                revoked.append(grant)
                logger.info(
                    "grace_expired_revoked",
                    grant_id=str(grant.id),
                    user_id=grant.user_id,
                )
            except Exception as e:
                logger.error(
                    "revoke_failed",
                    grant_id=str(grant.id),
                    user_id=grant.user_id,
                    error=str(e),
                )

        if revoked:
            await self.session.flush()

        return revoked

    async def remove_and_unban(self, chat_id: int, user_id: int) -> None:
        """Remove user from channel and immediately unban to clear Telegram's ban state.

        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID

        Raises:
            TelegramBadRequest: If removal or unban fails
        """
        try:
            # Ban (remove) user
            await self.bot.ban_chat_member(chat_id, user_id)
            logger.info("user_removed", chat_id=chat_id, user_id=user_id)

            # Immediately unban to clear Telegram's ban state
            await self.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            logger.info("user_unbanned", chat_id=chat_id, user_id=user_id)

        except TelegramBadRequest as e:
            logger.error(
                "remove_unban_failed", chat_id=chat_id, user_id=user_id, error=str(e)
            )
            raise
