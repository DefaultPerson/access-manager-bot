from typing import Any

from aiogram.types import TelegramObject, User
from aiogram.utils.i18n.middleware import I18nMiddleware
from sqlalchemy import select

from bot.config.settings import settings
from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.models import UserProfile

logger = get_logger(__name__)


class UserLocaleMiddleware(I18nMiddleware):
    async def get_locale(self, event: TelegramObject, data: dict[str, Any]) -> str:
        user: User | None = data.get("event_from_user")
        if not user:
            user = getattr(event, "from_user", None)

        if not user:
            return settings.DEFAULT_LANG

        try:
            async with db_manager.session() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.user_id == user.id)
                )
                profile = result.scalar_one_or_none()

                if profile and profile.preferred_language:
                    return profile.preferred_language

        except Exception as e:
            logger.error("locale_retrieval_error", user_id=user.id, error=str(e))

        return settings.DEFAULT_LANG
