"""Module-level singleton for accessing Bot/BroadcastService from APScheduler jobs.

APScheduler with a persistent jobstore pickles job args. Bot and BroadcastService
contain unpicklable resources (aiohttp session, etc.), so we keep them as
in-memory singletons set during startup; scheduled jobs grab them from here
instead of receiving them as args.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram_broadcast import BroadcastService

_bot: "Bot | None" = None
_service: "BroadcastService | None" = None


def set_runtime(bot: "Bot", service: "BroadcastService") -> None:
    global _bot, _service
    _bot = bot
    _service = service


def get_bot() -> "Bot":
    if _bot is None:
        raise RuntimeError("Broadcast runtime not initialized — call set_runtime() at startup")
    return _bot


def get_service() -> "BroadcastService":
    if _service is None:
        raise RuntimeError("Broadcast runtime not initialized — call set_runtime() at startup")
    return _service
