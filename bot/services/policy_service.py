"""Service for managing access policies and channels."""

from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.logger import get_logger
from bot.models import AccessPolicy, PolicyChannel
from bot.utils.validators import validate_channel_id, validate_channel_link

logger = get_logger(__name__)


class PolicyService:
    """Service for managing access policies and channels."""

    def __init__(self, session: AsyncSession, bot: Bot):
        """Initialize policy service.

        Args:
            session: Database session
            bot: Telegram bot instance
        """
        self.session = session
        self.bot = bot

    async def create_policy(
        self,
        chat_id: int,
        admin_id: int,
        title: str | None = None,
        channel_link: str | None = None,
    ) -> AccessPolicy:
        """Create new access policy for a protected channel.

        Args:
            chat_id: Telegram chat ID of protected channel
            admin_id: Admin user ID creating the policy
            title: Optional custom title
            channel_link: Optional channel link (validated)

        Returns:
            Created AccessPolicy instance

        Raises:
            ValueError: If bot lacks admin rights, policy already exists, or validation fails
        """
        # Validate channel ID
        is_valid, error = validate_channel_id(chat_id)
        if not is_valid:
            raise ValueError(f"Invalid protected channel ID: {error}")

        # Validate channel link if provided
        if channel_link:
            is_valid, error = validate_channel_link(channel_link)
            if not is_valid:
                raise ValueError(f"Invalid protected channel link: {error}")

        # Verify bot has admin rights
        if not await self.verify_bot_admin_rights(chat_id):
            raise ValueError(f"Bot lacks admin rights in channel {chat_id}")

        # Check if policy already exists
        result = await self.session.execute(
            select(AccessPolicy).where(AccessPolicy.protected_chat_id == chat_id)
        )
        if result.scalar_one_or_none():
            raise ValueError(f"Policy already exists for chat {chat_id}")

        # Get channel title if not provided
        if not title:
            try:
                chat = await self.bot.get_chat(chat_id)
                title = chat.title or f"Chat {chat_id}"
            except Exception:
                title = f"Chat {chat_id}"

        policy = AccessPolicy(
            protected_chat_id=chat_id,
            protected_channel_link=channel_link,
            title=title,
            created_by_admin_id=admin_id,
        )
        self.session.add(policy)
        await self.session.flush()
        logger.info(
            "policy_created",
            policy_id=str(policy.id),
            chat_id=chat_id,
            admin_id=admin_id,
        )
        return policy

    async def add_channel(
        self,
        policy_id: UUID,
        chat_id: int,
        admin_id: int,
        display_name: str | None = None,
        channel_link: str | None = None,
    ) -> PolicyChannel:
        """Add required channel to policy.

        Args:
            policy_id: Policy UUID
            chat_id: Telegram chat ID
            admin_id: Admin user ID
            display_name: Optional custom display name
            channel_link: Optional channel link (validated)

        Returns:
            Created PolicyChannel instance

        Raises:
            ValueError: If bot lacks admin rights or validation fails
        """
        # Validate channel ID
        is_valid, error = validate_channel_id(chat_id)
        if not is_valid:
            raise ValueError(f"Invalid channel ID: {error}")

        # Validate channel link if provided
        if channel_link:
            is_valid, error = validate_channel_link(channel_link)
            if not is_valid:
                raise ValueError(f"Invalid channel link: {error}")

        # Verify bot has admin rights
        if not await self.verify_bot_admin_rights(chat_id):
            raise ValueError(f"Bot lacks admin rights in channel {chat_id}")

        # Get display name if not provided
        if not display_name:
            try:
                chat = await self.bot.get_chat(chat_id)
                display_name = chat.title or f"Chat {chat_id}"
            except Exception:
                display_name = f"Chat {chat_id}"

        # Get next position
        result = await self.session.execute(
            select(PolicyChannel)
            .where(PolicyChannel.policy_id == policy_id)
            .order_by(PolicyChannel.position.desc())
        )
        last_channel = result.first()
        position = (last_channel[0].position + 1) if last_channel else 0

        channel = PolicyChannel(
            policy_id=policy_id,
            telegram_chat_id=chat_id,
            channel_link=channel_link,
            display_name=display_name,
            position=position,
            added_by_admin_id=admin_id,
        )
        self.session.add(channel)
        await self.session.flush()

        logger.info(
            "channel_added",
            policy_id=str(policy_id),
            channel_id=str(channel.id),
        )
        return channel

    async def add_required_channel(
        self,
        policy_id: UUID,
        telegram_chat_id: int,
        display_name: str | None,
        admin_id: int,
        channel_link: str | None = None,
    ) -> PolicyChannel:
        """Add required channel to policy.

        Args:
            policy_id: Policy UUID
            telegram_chat_id: Telegram chat ID
            display_name: Optional custom display name
            admin_id: Admin user ID
            channel_link: Optional channel link (validated)

        Returns:
            Created PolicyChannel instance
        """
        return await self.add_channel(
            policy_id=policy_id,
            chat_id=telegram_chat_id,
            admin_id=admin_id,
            display_name=display_name,
            channel_link=channel_link,
        )

    async def reactivate_policy(self, policy_id: UUID, admin_id: int) -> AccessPolicy:
        """Reactivate a deactivated policy.

        Args:
            policy_id: Policy UUID
            admin_id: Admin user ID

        Returns:
            Reactivated AccessPolicy instance

        Raises:
            ValueError: If policy not found or already active
        """
        result = await self.session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            raise ValueError("Policy not found")

        if policy.is_active:
            raise ValueError("Policy is already active")

        # Verify bot still has admin rights
        if not await self.verify_bot_admin_rights(policy.protected_chat_id):
            raise ValueError(
                f"Bot lacks admin rights in channel {policy.protected_chat_id}"
            )

        policy.is_active = True
        await self.session.flush()

        logger.info("policy_reactivated", policy_id=str(policy_id), admin_id=admin_id)
        return policy

    async def remove_channel(
        self, channel_id: UUID, admin_id: int
    ) -> PolicyChannel:
        """Remove channel from policy (hard delete).

        Args:
            channel_id: PolicyChannel UUID
            admin_id: Admin user ID

        Returns:
            Deleted PolicyChannel instance

        Raises:
            ValueError: If channel not found
        """
        result = await self.session.execute(
            select(PolicyChannel).where(PolicyChannel.id == channel_id)
        )
        channel = result.scalar_one_or_none()

        if not channel:
            raise ValueError(f"Channel {channel_id} not found")

        # Store channel data before deletion
        policy_id = channel.policy_id
        display_name = channel.display_name
        channel_chat_id = channel.telegram_chat_id

        await self.session.delete(channel)
        await self.session.flush()

        logger.info(
            "channel_removed",
            channel_id=str(channel_id),
            policy_id=str(policy_id),
            admin_id=admin_id,
        )

        return channel

    async def list_policies(self, active_only: bool = True) -> list[AccessPolicy]:
        """List all policies.

        Args:
            active_only: Only return active policies

        Returns:
            List of AccessPolicy instances
        """
        query = select(AccessPolicy)
        if active_only:
            query = query.where(AccessPolicy.is_active == True)  # noqa: E712

        result = await self.session.execute(
            query.order_by(AccessPolicy.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_policy(self, policy_id: UUID) -> AccessPolicy | None:
        """Get policy by ID.

        Args:
            policy_id: Policy UUID

        Returns:
            AccessPolicy instance or None
        """
        result = await self.session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        return result.scalar_one_or_none()

    async def verify_bot_admin_rights(self, chat_id: int) -> bool:
        """Verify bot has admin rights in channel.

        Args:
            chat_id: Telegram chat ID

        Returns:
            True if bot is admin, False otherwise
        """
        try:
            bot_member = await self.bot.get_chat_member(chat_id, self.bot.id)
            return bot_member.status in ("administrator", "creator")
        except TelegramBadRequest as e:
            logger.warning("bot_admin_check_failed", chat_id=chat_id, error=str(e))
            return False
