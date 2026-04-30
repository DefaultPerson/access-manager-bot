import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config.settings import settings
from bot.core.logger import get_logger

logger = get_logger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Middleware to log all incoming messages and callbacks."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Log event and measure handler execution time.

        Args:
            handler: Next handler in chain
            event: Incoming event
            data: Context data

        Returns:
            Handler result
        """
        start_time = time.time()

        event_type = type(event).__name__
        user = None
        event_id = None
        event_data = {}

        if isinstance(event, Message):
            user = event.from_user
            event_id = event.message_id
            event_data = {
                "chat_id": event.chat.id,
                "text_length": len(event.text) if event.text else 0,
                "has_photo": event.photo is not None,
                "has_document": event.document is not None,
            }
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            event_id = event.id
            event_data = {
                "callback_data": event.data,
            }

        if user:
            logger.info(
                "event_received",
                event_type=event_type,
                event_id=event_id,
                user_id=user.id,
                username=user.username,
                **event_data,
            )

        try:
            result = await handler(event, data)

            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                "event_handled",
                event_type=event_type,
                event_id=event_id,
                user_id=user.id if user else None,
                duration_ms=round(duration_ms, 2),
            )
            if settings.LOG_LEVEL == "DEBUG":
                handler_obj = data.get("handler")
                cb = getattr(
                    handler_obj, "callback", None
                    ) or handler

                name = getattr(cb, "__qualname__", None) or getattr(
                    cb, "__name__", None
                )
                if name is None:
                    name = cb.__class__.__name__

                data["__handled_by__"] = name
                logger.info("handled_by=%s event=%s", name, type(event).__name__)

            if hasattr(event, "message"):
                msg: Message | None = event.message
                if msg and (msg.left_chat_member or msg.new_chat_members):
                    bot = data["bot"]
                    try:
                        await bot.delete_message(msg.chat.id, msg.message_id)
                    except TelegramBadRequest:
                        # Message already deleted, ignore
                        pass

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "event_error",
                event_type=event_type,
                event_id=event_id,
                user_id=user.id if user else None,
                duration_ms=round(duration_ms, 2),
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
