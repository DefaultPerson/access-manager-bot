from typing import Any, Awaitable, Callable, Dict, MutableMapping

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, TelegramObject, User
from cachetools import TTLCache


class CallbackThrottlingMiddleware(BaseMiddleware):

    def __init__(self, ttl: float = 0.5) -> None:
        self.cache: MutableMapping[int, None] = TTLCache(maxsize=10_000, ttl=ttl)
        self.ttl = ttl

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        user: User | None = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        throttling_key = get_flag(data, "throttling_key")
        if throttling_key == "broadcast":
            return await handler(event, data)

        if user.id in self.cache:
            await event.answer("⚠️ Stop spamming!", show_alert=True)
            return None

        self.cache[user.id] = None

        return await handler(event, data)
