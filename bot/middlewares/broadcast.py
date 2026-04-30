from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Chat, TelegramObject, User
from aiogram.utils.i18n.core import I18n
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from bot.core.db import db_manager
from bot.keyboards.inline.newsletter import InlineKeyboard
from bot.manager import ANManager
from bot.models import UserProfile


class AiogramNewsletterMiddleware(BaseMiddleware):
    """Build ANManager per private-chat update and inject as `an_manager`."""

    def __init__(self, apscheduler: AsyncIOScheduler) -> None:
        self.apscheduler = apscheduler

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat: Chat = data.get("event_chat")

        if chat and chat.type == "private":
            user: User = data.get("event_from_user")
            i18n: I18n = data.get("i18n")

            if not i18n:
                from bot.core.i18n import i18n as default_i18n

                i18n = default_i18n

            async with db_manager.session() as session:
                result = await session.execute(
                    select(UserProfile).where(UserProfile.user_id == user.id)
                )
                profile = result.scalar_one_or_none()
                language_code = (
                    profile.preferred_language
                    if profile and profile.preferred_language
                    else "en"
                )

            inline_keyboard = InlineKeyboard(i18n, language_code)

            data["an_manager"] = ANManager(
                apscheduler=self.apscheduler,
                i18n=i18n,
                inline_keyboard=inline_keyboard,
                data=data,
            )

        return await handler(event, data)
