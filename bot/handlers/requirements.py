from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.i18n.core import I18n
from sqlalchemy import select

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.keyboards.inline.channels import channel_list_keyboard
from bot.models import AccessPolicy, PolicyChannel

logger = get_logger(__name__)

router = Router()


@router.callback_query(F.data.startswith("reqs:"))
async def requirements_callback(callback: CallbackQuery, bot: Bot, i18n: I18n) -> None:
    """Handle requirements display callback for a policy.

    Args:
        callback: Callback query with reqs:{policy_id} data
        bot: Bot instance
        i18n: I18n instance
    """
    user = callback.from_user
    if not user or not callback.data or not callback.message:
        await callback.answer("Error")
        return

    # Extract policy_id from callback data
    try:
        policy_id_str = callback.data.split(":", 1)[1]
        policy_id = UUID(policy_id_str)
    except (ValueError, IndexError):
        await callback.answer("Invalid policy ID")
        return

    async with db_manager.session() as session:
        # Get policy
        result = await session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            await callback.answer("Policy not found")
            return

        # Get required channels for this policy
        result = await session.execute(
            select(PolicyChannel)
            .where(PolicyChannel.policy_id == policy_id)
            .order_by(PolicyChannel.position)
        )
        required_channels = result.scalars().all()

        if not required_channels:
            await callback.answer("No requirements")
            return

        # Build requirements text
        text = i18n.gettext("channels-title") + "\n\n"
        text += i18n.gettext("channels-instructions") + "\n\n"
        text += (
            i18n.gettext("channels-to-access").format(channel_name=policy.title)
            + "\n\n"
        )
        text += i18n.gettext("channels-required") + "\n\n"

        for idx, channel in enumerate(required_channels, 1):
            # Use channel_link if available, otherwise fallback to chat_id link
            if channel.channel_link:
                invite_link = channel.channel_link
            else:
                invite_link = f"https://t.me/c/{abs(channel.telegram_chat_id)}"
            text += f'{idx}. <a href="{invite_link}">{channel.display_name}</a>\n'

        # Get all active policies to rebuild channels menu keyboard
        result = await session.execute(
            select(AccessPolicy)
            .where(AccessPolicy.is_active == True)  # noqa: E712
            .order_by(AccessPolicy.created_at.desc())
        )
        policies = result.scalars().all()

        # Prepare channels data for keyboard
        channels_data = []
        for p in policies:
            if p.protected_channel_link:
                invite_link = p.protected_channel_link
            else:
                invite_link = f"https://t.me/c/{abs(p.protected_chat_id)}"

            channels_data.append(
                {
                    "policy_id": str(p.id),
                    "display_name": p.title,
                    "invite_link": invite_link,
                }
            )

        # Calculate pagination for first page
        CHANNELS_PER_PAGE = 10
        total_channels = len(channels_data)
        total_pages = (total_channels + CHANNELS_PER_PAGE - 1) // CHANNELS_PER_PAGE
        page_channels = channels_data[:CHANNELS_PER_PAGE]

        # Build keyboard
        keyboard = channel_list_keyboard(
            i18n,
            channels=page_channels,
            page=1,
            total_pages=total_pages,
        )

        # Edit message with requirements text and channels menu keyboard
        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
        except Exception:
            # If edit fails (message too old), just answer callback
            await callback.answer(i18n.gettext("channels-required"))

    await callback.answer()
    logger.info(
        "requirements_shown",
        user_id=user.id,
        policy_id=str(policy_id),
        required_count=len(required_channels),
    )
