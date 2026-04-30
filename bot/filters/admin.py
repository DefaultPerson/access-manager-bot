from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from bot.config.settings import settings


class IsAdmin(Filter):
    async def __call__(self, obj: Message | CallbackQuery) -> bool:
        user = obj.from_user
        if not user:
            return False
        return user.id in settings.admin_ids_list
