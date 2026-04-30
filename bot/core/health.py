import asyncio
from typing import Any

from aiogram import Bot
from aiohttp import web

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.core.redis_client import redis_manager

logger = get_logger(__name__)


async def health_handler(request: web.Request) -> web.Response:
    """Handle /health/live requests."""
    bot: Bot = request.app["bot"]

    redis_ok, postgres_ok, telegram_ok = await asyncio.gather(
        redis_manager.health_check(),
        db_manager.health_check(),
        check_telegram_connection(bot),
        return_exceptions=True,
    )

    redis_ok = redis_ok if isinstance(redis_ok, bool) else False
    postgres_ok = postgres_ok if isinstance(postgres_ok, bool) else False
    telegram_ok = telegram_ok if isinstance(telegram_ok, bool) else False

    status = "ok" if all([redis_ok, postgres_ok, telegram_ok]) else "degraded"

    response_data: dict[str, Any] = {
        "status": status,
        "redis": redis_ok,
        "postgres": postgres_ok,
        "telegram": "connected" if telegram_ok else "disconnected",
    }

    status_code = 200 if status == "ok" else 503

    return web.json_response(response_data, status=status_code)


async def check_telegram_connection(bot: Bot) -> bool:
    """Check if bot can connect to Telegram API."""
    try:
        await bot.get_me()
        return True
    except Exception as e:
        logger.warning("telegram_health_check_failed", error=str(e))
        return False


async def create_health_app(bot: Bot) -> web.Application:
    """Create aiohttp app for health checks."""
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/health/live", health_handler)
    return app


async def start_health_server(
    bot: Bot, host: str = "0.0.0.0", port: int = 8080
) -> web.AppRunner:
    """Start health check HTTP server."""
    app = await create_health_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("health_server_started", host=host, port=port)
    return runner


async def stop_health_server(runner: web.AppRunner) -> None:
    """Stop health check HTTP server."""
    await runner.cleanup()
    logger.info("health_server_stopped")
