from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.i18n.core import I18n

from bot.core.logger import get_logger
from bot.filters.admin import IsAdmin
from bot.services.broadcast_runtime import get_service

logger = get_logger(__name__)

router = Router()

# Apply admin filter to all handlers in this router
router.message.filter(IsAdmin())


async def broadcast_return_callback(**_) -> None:
    """Callback after broadcast menu is closed — placeholder."""
    return


@router.message(Command("broadcast"))
async def broadcast_start(
    message: Message, state: FSMContext, i18n: I18n, an_manager=None
) -> None:
    """Open the broadcast menu (admin only).

    Subscriber list is read live by `BroadcastService` from the storage layer
    (`SQLAlchemyBroadcastStorage` over UserProfile), so we don't need to pass
    user ids explicitly. We only sanity-check that there is at least one active
    subscriber before opening the menu.
    """
    user = message.from_user
    if not user:
        return

    if not an_manager:
        await message.answer(i18n.gettext("broadcast-system-unavailable"))
        logger.error(
            "broadcast_an_manager_missing",
            user_id=user.id,
            message="ANManager not injected by middleware",
        )
        return

    total_active = await get_service().get_subscriber_count(only_active=True)
    if total_active == 0:
        await message.answer(i18n.gettext("broadcast-no-users"))
        return

    await state.clear()

    await an_manager.newsletter_menu(return_callback=broadcast_return_callback)

    logger.info(
        "broadcast_menu_opened",
        admin_id=user.id,
        total_active=total_active,
    )
