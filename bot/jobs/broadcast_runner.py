"""Picklable broadcast runner used by APScheduler jobs and immediate sends.

Args (message_data: dict, admin_user_id: int) are picklable so this function can
be persisted in RedisJobStore. Bot and BroadcastService come from
bot.services.broadcast_runtime singleton.
"""

from __future__ import annotations

from aiogram.types import Message

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.models import EventType
from bot.services.audit_service import AuditService
from bot.services.broadcast_runtime import get_bot, get_service

logger = get_logger(__name__)


async def run_broadcast(message_data: dict, admin_user_id: int) -> None:
    """Send the broadcast message to all active subscribers and write audit log.

    Used both for immediate broadcasts (asyncio.create_task) and scheduled
    broadcasts (APScheduler).
    """
    bot = get_bot()
    service = get_service()

    async def sender(chat_id: int) -> None:
        msg = Message(**message_data).as_(bot)
        await msg.send_copy(chat_id=chat_id, reply_markup=msg.reply_markup)

    try:
        result = await service.broadcast_custom(sender=sender)
        logger.info(
            "broadcast_completed",
            admin_id=admin_user_id,
            total=result.total,
            successful=result.successful,
            failed=result.failed,
            blocked=len(result.blocked_users),
        )

        async with db_manager.session() as session:
            audit = AuditService(session, bot)
            await audit.log_event(
                event_type=EventType.BROADCAST_SENT,
                user_id=admin_user_id,
                details={
                    "total_users": result.total,
                    "successful": result.successful,
                    "unsuccessful": result.failed,
                    "blocked": len(result.blocked_users),
                },
            )
    except Exception as e:
        logger.error("broadcast_failed", admin_id=admin_user_id, error=str(e))
