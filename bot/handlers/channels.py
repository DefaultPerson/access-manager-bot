"""Channels list handler with pagination."""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n.core import I18n
from sqlalchemy import select

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.keyboards.inline.channels import channel_list_keyboard
from bot.models import AccessPolicy

logger = get_logger(__name__)

router = Router()

CHANNELS_PER_PAGE = 10


@router.message(Command("channels"))
async def channels_command(
    message: Message, bot: Bot, state: FSMContext, i18n: I18n
) -> None:
    """Handle /channels command to display available channels.

    Args:
        message: Incoming message
        bot: Bot instance
        state: FSM context
        i18n: I18n instance
    """
    user = message.from_user
    if not user:
        return

    # Clear any active FSM state
    await state.clear()

    await show_channels_page(message, i18n, page=1)


@router.callback_query(F.data == "menu:channels")
async def menu_channels_callback(callback: CallbackQuery, i18n: I18n) -> None:
    """Handle menu channels button callback.

    Args:
        callback: Callback query
        i18n: I18n instance
    """
    if not callback.message:
        await callback.answer("Error")
        return

    await show_channels_page(callback.message, i18n, page=1, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("page:"))
async def channels_pagination(callback: CallbackQuery, bot: Bot, i18n: I18n) -> None:
    """Handle pagination callbacks for channel list.

    Args:
        callback: Callback query with page:{number} data
        bot: Bot instance
        i18n: I18n instance
    """
    if not callback.data or not callback.message:
        await callback.answer("Error")
        return

    page_data = callback.data.split(":", 1)[1]

    if page_data == "current":
        await callback.answer()
        return

    try:
        page = int(page_data)
    except ValueError:
        await callback.answer("Invalid page")
        return

    await show_channels_page(callback.message, i18n, page=page, edit=True)
    await callback.answer()


async def show_channels_page(
    message: Message, i18n: I18n, page: int = 1, edit: bool = False
) -> None:
    """Show channels list page.

    Args:
        message: Message to send/edit
        i18n: I18n instance
        page: Page number
        edit: Whether to edit existing message
    """
    async with db_manager.session() as session:
        # Get all active policies with their protected channels
        result = await session.execute(
            select(AccessPolicy)
            .where(AccessPolicy.is_active == True)  # noqa: E712
            .order_by(AccessPolicy.created_at.desc())
        )
        policies = result.scalars().all()

        if not policies:
            text = i18n.gettext("admin-no-policies")
            if edit:
                await message.edit_text(text)
            else:
                await message.answer(text)
            return

        # Prepare channel data from policies
        channels_data = []
        for policy in policies:
            # Use policy protected_channel_link if available, otherwise fallback to chat_id link
            if policy.protected_channel_link:
                invite_link = policy.protected_channel_link
            else:
                invite_link = f"https://t.me/c/{abs(policy.protected_chat_id)}"

            channels_data.append(
                {
                    "policy_id": str(policy.id),
                    "display_name": policy.title,
                    "invite_link": invite_link,
                }
            )

        # Calculate pagination
        total_channels = len(channels_data)
        total_pages = (total_channels + CHANNELS_PER_PAGE - 1) // CHANNELS_PER_PAGE
        start_idx = (page - 1) * CHANNELS_PER_PAGE
        end_idx = start_idx + CHANNELS_PER_PAGE
        page_channels = channels_data[start_idx:end_idx]

        # Build message
        text = (
            i18n.gettext("channels-title")
            + "\n\n"
            + i18n.gettext("channels-instructions")
        )

        keyboard = channel_list_keyboard(
            i18n,
            channels=page_channels,
            page=page,
            total_pages=total_pages,
        )

        if edit:
            await message.edit_text(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)

    logger.info("channels_page_shown", page=page, total_channels=total_channels)
