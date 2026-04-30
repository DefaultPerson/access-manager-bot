from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config.settings import settings
from bot.core.logger import get_logger
from bot.models import UserProfile

logger = get_logger(__name__)


class UserService:
    """Service for managing user profiles."""

    def __init__(self, session: AsyncSession):
        """Initialize user service.

        Args:
            session: Database session
        """
        self.session = session

    async def upsert_profile(
        self, user_id: int, username: str | None = None, full_name: str | None = None
    ) -> UserProfile:
        """Create or update user profile.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            full_name: User's full name

        Returns:
            UserProfile instance
        """
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if profile:
            profile.username = username
            profile.full_name = full_name
            profile.last_seen_at = datetime.now(timezone.utc)
            await self.session.flush()
        else:
            profile = UserProfile(
                user_id=user_id,
                username=username,
                full_name=full_name,
            )
            self.session.add(profile)
            await self.session.flush()
            logger.info("user_profile_created", user_id=user_id, username=username)

        return profile

    async def set_language(self, user_id: int, language_code: str) -> UserProfile:
        """Set user's preferred language.

        Args:
            user_id: Telegram user ID
            language_code: Language code (ru, en, ua)

        Returns:
            Updated UserProfile instance

        Raises:
            ValueError: If user not found
        """
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            raise ValueError(f"User {user_id} not found")

        profile.preferred_language = language_code
        await self.session.flush()

        logger.info("user_language_set", user_id=user_id, language=language_code)
        return profile

    async def get_profile(self, user_id: int) -> UserProfile | None:
        """Get user profile by ID.

        Args:
            user_id: Telegram user ID

        Returns:
            UserProfile instance or None
        """
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin.

        Args:
            user_id: Telegram user ID

        Returns:
            True if user in ADMIN_IDS
        """
        return user_id in settings.admin_ids_list
