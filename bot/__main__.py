import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram_broadcast import BroadcastService

from bot.config.settings import settings
from bot.core.db import db_manager
from bot.core.health import start_health_server, stop_health_server
from bot.core.i18n import i18n
from bot.core.logger import get_logger
from bot.core.menu import setup_bot_commands
from bot.core.redis_client import redis_manager
from bot.handlers import (
    channels,
    chat_member,
    check,
    join_request,
    language,
    menu,
    requirements,
    start,
)
from bot.handlers.admin import broadcast, policy, users
from bot.jobs.scheduler import setup_scheduler, start_scheduler, stop_scheduler
from bot.middlewares.broadcast import AiogramNewsletterMiddleware
from bot.middlewares.callback_throttling import CallbackThrottlingMiddleware
from bot.middlewares.i18n import UserLocaleMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.newsletter import AiogramNewsletterHandlers
from bot.services.broadcast_runtime import set_runtime
from bot.services.broadcast_storage import SQLAlchemyBroadcastStorage

logger = get_logger(__name__)


async def main() -> None:
    """Main bot entry point."""
    logger.info("bot_starting", version="1.0.0")

    # Initialize core services
    await db_manager.connect()
    await redis_manager.connect()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )

    storage = RedisStorage.from_url(settings.REDIS_DSN)
    dp = Dispatcher(storage=storage)

    scheduler = setup_scheduler()

    # Broadcast service (aiogram-broadcast) over UserProfile
    broadcast_storage = SQLAlchemyBroadcastStorage(db_manager)
    broadcast_service = BroadcastService(
        bot,
        broadcast_storage,
        rate_limit=settings.BROADCAST_RPS_DELAY,
        max_retries=settings.BROADCAST_MAX_RETRIES,
    )
    set_runtime(bot, broadcast_service)
    dp["broadcast_service"] = broadcast_service

    def attach_inner_to_all_observers(
        router, mw, *, exclude: set[str] | None = None
    ) -> None:
        exclude = exclude or set()
        for event_name, observer in router.observers.items():
            if event_name in exclude:
                continue
            observer.middleware(mw)

        for child in getattr(router, "sub_routers", []):
            attach_inner_to_all_observers(child, mw, exclude=exclude)

    if settings.LOG_LEVEL == "DEBUG":
        attach_inner_to_all_observers(dp, LoggingMiddleware())

    dp.update.middleware.register(LoggingMiddleware())
    dp.update.middleware.register(ThrottlingMiddleware(default_ttl=1.0))
    dp.update.middleware.register(CallbackThrottlingMiddleware(ttl=0.5))
    dp.update.middleware.register(UserLocaleMiddleware(i18n=i18n))

    dp.update.middleware.register(AiogramNewsletterMiddleware(scheduler))
    logger.info("newsletter_middleware_registered")

    dp.include_router(start.router)
    dp.include_router(language.router)
    dp.include_router(menu.router)
    dp.include_router(channels.router)
    dp.include_router(requirements.router)
    dp.include_router(check.router)
    dp.include_router(join_request.router)
    dp.include_router(chat_member.router)
    dp.include_router(policy.router)
    dp.include_router(broadcast.router)
    dp.include_router(users.router)

    AiogramNewsletterHandlers().register(dp)
    logger.info("newsletter_handlers_registered")

    await setup_bot_commands(bot)

    await start_scheduler(scheduler, bot)

    health_server = await start_health_server(
        bot, host="0.0.0.0", port=settings.HEALTH_PORT
    )

    logger.info("bot_started")

    try:
        # Explicitly include chat_member updates for membership tracking
        allowed_updates = list(dp.resolve_used_update_types())
        if "chat_member" not in allowed_updates:
            allowed_updates.append("chat_member")
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        logger.info("bot_stopping")
        await stop_scheduler(scheduler)
        await stop_health_server(health_server)
        await bot.session.close()
        await db_manager.disconnect()
        await redis_manager.disconnect()
        logger.info("bot_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("bot_interrupted")
