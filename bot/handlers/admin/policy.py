from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n.core import I18n
from sqlalchemy import select

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.filters.admin import IsAdmin
from bot.jobs.compliance_scan import daily_compliance_scan
from bot.keyboards.inline.admin import policy_management_keyboard
from bot.models import AccessPolicy, PolicyChannel
from bot.services.policy_service import PolicyService

logger = get_logger(__name__)

router = Router()

# Apply admin filter to all handlers in this router
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class PolicyCreationStates(StatesGroup):
    """States for policy creation flow."""

    waiting_for_chat_id = State()
    waiting_for_channel_link = State()


class ChannelAddStates(StatesGroup):
    """States for adding channels to policies."""

    waiting_for_policy_id = State()
    waiting_for_chat_id = State()
    waiting_for_channel_link = State()


class PolicyEditStates(StatesGroup):
    """States for editing policy properties."""

    waiting_for_new_link = State()


@router.message(Command("admin_policies"))
async def admin_policies_list(
    message: Message, bot: Bot, state: FSMContext, i18n: I18n
) -> None:
    """List all policies (admin only).

    Args:
        message: Incoming message
        bot: Bot instance
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        return

    # Clear any active FSM state
    await state.clear()

    async with db_manager.session() as session:
        result = await session.execute(
            select(AccessPolicy).order_by(AccessPolicy.created_at.desc()).limit(10)
        )
        policies = result.scalars().all()

        if not policies:
            await message.answer(i18n.gettext("admin-policies-not-found"))
            return

        text = i18n.gettext("admin-policies-title")
        for policy in policies:
            status = "✅" if policy.is_active else "❌"
            text += f"{status} <code>{policy.id}</code>\n"
            text += f"   <b>{policy.title}</b>\n"
            text += f"   {i18n.gettext('admin-label-chat-id')}: <code>{policy.protected_chat_id}</code>\n\n"

        await message.answer(text, parse_mode="HTML")

    logger.info("admin_policies_listed", admin_id=user.id, count=len(policies))


@router.message(Command("admin_policy_view"))
async def admin_policy_view_command(
    message: Message, state: FSMContext, i18n: I18n
) -> None:
    """View policy details and management menu (admin only).

    Usage: /admin_policy_view <policy_id>

    Args:
        message: Incoming message
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        return

    # Clear any active FSM state
    await state.clear()

    if not message.text:
        await message.answer(i18n.gettext("admin-usage-policy-view"))
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(i18n.gettext("admin-usage-policy-view"))
        return

    try:
        policy_id = UUID(parts[1].strip())
    except ValueError:
        await message.answer(i18n.gettext("admin-invalid-uuid"))
        return

    async with db_manager.session() as session:
        result = await session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            await message.answer(i18n.gettext("admin-policy-not-found"))
            return

        status = (
            i18n.gettext("admin-status-active")
            if policy.is_active
            else i18n.gettext("admin-status-inactive")
        )
        text = i18n.gettext("admin-policy-details").format(
            title=policy.title,
            id=policy.id,
            status=status,
            chat_id=policy.protected_chat_id,
        )

        await message.answer(
            text,
            reply_markup=policy_management_keyboard(
                i18n, str(policy.id), policy.is_active
            ),
            parse_mode="HTML",
        )

    logger.info(
        "admin_policy_viewed_command", admin_id=user.id, policy_id=str(policy_id)
    )


@router.message(Command("admin_policy_create"))
async def admin_policy_create_start(
    message: Message, state: FSMContext, i18n: I18n
) -> None:
    """Start policy creation flow (admin only).

    Args:
        message: Incoming message
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        return

    await state.set_state(PolicyCreationStates.waiting_for_chat_id)
    await message.answer(i18n.gettext("admin-enter-chat-id"))


@router.message(PolicyCreationStates.waiting_for_chat_id)
async def admin_policy_create_chat_id(
    message: Message, state: FSMContext, i18n: I18n
) -> None:
    """Process chat ID input for policy creation.

    Args:
        message: Message with chat ID
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        await state.clear()
        return

    if not message.text:
        await message.answer(i18n.gettext("admin-invalid-input"))
        return

    from bot.utils.validators import validate_channel_id

    input_text = message.text.strip()

    try:
        chat_id = int(input_text)
    except ValueError:
        await message.answer(i18n.gettext("admin-chat-id-numeric"))
        return

    # Validate channel ID format
    is_valid, error = validate_channel_id(chat_id)
    if not is_valid:
        await message.answer(i18n.gettext("admin-error").format(error=error))
        return

    await state.update_data(chat_id=chat_id)
    await state.set_state(PolicyCreationStates.waiting_for_channel_link)
    await message.answer(i18n.gettext("admin-enter-channel-link"))


@router.message(PolicyCreationStates.waiting_for_channel_link)
async def admin_policy_create_channel_link(
    message: Message, state: FSMContext, bot: Bot, i18n: I18n
) -> None:
    """Process channel link input and create policy with auto-fetched title.

    Args:
        message: Message with channel link
        state: FSM context
        bot: Bot instance
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        await state.clear()
        return

    if not message.text:
        await message.answer(i18n.gettext("admin-invalid-input"))
        return

    from bot.utils.validators import validate_channel_link

    input_text = message.text.strip()

    # Validate channel link (now required)
    is_valid, error = validate_channel_link(input_text)
    if not is_valid:
        await message.answer(i18n.gettext("admin-error").format(error=error))
        return

    data = await state.get_data()
    chat_id = data["chat_id"]

    # Fetch channel title automatically using bot.get_chat()
    try:
        chat = await bot.get_chat(chat_id)
        title = chat.title if chat.title else f"Channel {chat_id}"
    except Exception as e:
        await message.answer(
            i18n.gettext("admin-error").format(error=f"Cannot fetch channel title: {str(e)}")
        )
        await state.clear()
        return

    # Create policy immediately
    async with db_manager.session() as session:
        policy_service = PolicyService(session, bot)

        try:
            policy = await policy_service.create_policy(
                chat_id=chat_id,
                admin_id=user.id,
                title=title,
                channel_link=input_text,
            )

            await message.answer(
                i18n.gettext("admin-policy-created-details").format(
                    id=policy.id,
                    title=policy.title,
                    chat_id=policy.protected_chat_id,
                ),
                reply_markup=policy_management_keyboard(
                    i18n, str(policy.id), policy.is_active
                ),
                parse_mode="HTML",
            )

            logger.info(
                "admin_policy_created", admin_id=user.id, policy_id=str(policy.id)
            )
        except Exception as e:
            await message.answer(i18n.gettext("admin-error").format(error=str(e)))
            logger.error("admin_policy_creation_failed", admin_id=user.id, error=str(e))

    await state.clear()


@router.message(Command("admin_policy_add_required"))
async def admin_add_required_start(
    message: Message, state: FSMContext, i18n: I18n
) -> None:
    """Start adding required channel flow (admin only).

    Args:
        message: Incoming message
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        return

    await state.set_state(ChannelAddStates.waiting_for_policy_id)
    await message.answer(i18n.gettext("admin-enter-policy-id"))


@router.message(Command("admin_channel_remove"))
async def admin_channel_remove_command(
    message: Message, state: FSMContext, bot: Bot, i18n: I18n
) -> None:
    """Remove required channel from policy (admin only).

    Usage: /admin_channel_remove <channel_uuid>

    Args:
        message: Incoming message
        state: FSM context
        bot: Bot instance
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        return

    # Clear any active FSM state
    await state.clear()

    if not message.text:
        await message.answer(i18n.gettext("admin-usage-channel-remove"))
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(i18n.gettext("admin-usage-channel-remove"))
        return

    try:
        channel_id = UUID(parts[1].strip())
    except ValueError:
        await message.answer(i18n.gettext("admin-invalid-uuid"))
        return

    async with db_manager.session() as session:
        policy_service = PolicyService(session, bot)

        try:
            channel = await policy_service.remove_channel(
                channel_id=channel_id, admin_id=user.id
            )

            await message.answer(
                i18n.gettext("admin-channel-removed-details").format(
                    id=channel.id,
                    name=channel.display_name,
                    policy_id=channel.policy_id,
                ),
                parse_mode="HTML",
            )

            logger.info(
                "admin_channel_removed_command",
                admin_id=user.id,
                channel_id=str(channel_id),
            )
        except Exception as e:
            await message.answer(i18n.gettext("admin-error").format(error=str(e)))
            logger.error("admin_channel_removal_failed", admin_id=user.id, error=str(e))


@router.message(Command("admin_policy_reactivate"))
async def admin_policy_reactivate_command(
    message: Message, state: FSMContext, bot: Bot, i18n: I18n
) -> None:
    """Reactivate a deactivated policy (admin only).

    Usage: /admin_policy_reactivate <policy_id>

    Args:
        message: Incoming message
        state: FSM context
        bot: Bot instance
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        return

    # Clear any active FSM state
    await state.clear()

    if not message.text:
        await message.answer(i18n.gettext("admin-usage-reactivate"))
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(i18n.gettext("admin-usage-reactivate"))
        return

    try:
        policy_id = UUID(parts[1].strip())
    except ValueError:
        await message.answer(i18n.gettext("admin-invalid-uuid"))
        return

    async with db_manager.session() as session:
        policy_service = PolicyService(session, bot)

        try:
            policy = await policy_service.reactivate_policy(
                policy_id=policy_id, admin_id=user.id
            )

            await message.answer(
                i18n.gettext("admin-policy-reactivated-details").format(
                    id=policy.id,
                    title=policy.title,
                ),
                reply_markup=policy_management_keyboard(
                    i18n, str(policy.id), policy.is_active
                ),
                parse_mode="HTML",
            )

            logger.info(
                "admin_policy_reactivated_command",
                admin_id=user.id,
                policy_id=str(policy_id),
            )
        except Exception as e:
            await message.answer(i18n.gettext("admin-error").format(error=str(e)))
            logger.error(
                "admin_policy_reactivation_failed", admin_id=user.id, error=str(e)
            )


@router.message(ChannelAddStates.waiting_for_policy_id)
async def admin_add_channel_policy_id(
    message: Message, state: FSMContext, i18n: I18n
) -> None:
    """Process policy ID input for channel addition.

    Args:
        message: Message with policy ID
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        await state.clear()
        return

    if not message.text:
        await message.answer(i18n.gettext("admin-invalid-input"))
        return

    try:
        policy_id = UUID(message.text.strip())
    except ValueError:
        await message.answer(i18n.gettext("admin-invalid-uuid"))
        return

    await state.update_data(policy_id=str(policy_id))
    await state.set_state(ChannelAddStates.waiting_for_chat_id)
    await message.answer(i18n.gettext("admin-enter-channel-chat-id"))


@router.message(ChannelAddStates.waiting_for_chat_id)
async def admin_add_channel_chat_id(
    message: Message, state: FSMContext, i18n: I18n
) -> None:
    """Process chat ID input for channel addition.

    Args:
        message: Message with chat ID
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        await state.clear()
        return

    if not message.text:
        await message.answer(i18n.gettext("admin-invalid-input"))
        return

    from bot.utils.validators import validate_channel_id

    try:
        chat_id = int(message.text.strip())
    except ValueError:
        await message.answer(i18n.gettext("admin-chat-id-numeric"))
        return

    # Validate channel ID format
    is_valid, error = validate_channel_id(chat_id)
    if not is_valid:
        await message.answer(i18n.gettext("admin-error").format(error=error))
        return

    await state.update_data(chat_id=chat_id)
    await state.set_state(ChannelAddStates.waiting_for_channel_link)
    await message.answer(i18n.gettext("admin-enter-channel-link-add"))


@router.message(ChannelAddStates.waiting_for_channel_link)
async def admin_add_channel_link(
    message: Message, state: FSMContext, bot: Bot, i18n: I18n
) -> None:
    """Process channel link input and add channel with auto-fetched display name.

    Args:
        message: Message with channel link
        state: FSM context
        bot: Bot instance
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        await state.clear()
        return

    if not message.text:
        await message.answer(i18n.gettext("admin-invalid-input"))
        return

    from bot.utils.validators import validate_channel_link

    input_text = message.text.strip()

    # Validate channel link (now required)
    is_valid, error = validate_channel_link(input_text)
    if not is_valid:
        await message.answer(i18n.gettext("admin-error").format(error=error))
        return

    data = await state.get_data()
    policy_id = UUID(data["policy_id"])
    chat_id = data["chat_id"]

    # Fetch channel display name automatically using bot.get_chat()
    try:
        chat = await bot.get_chat(chat_id)
        display_name = chat.title if chat.title else f"Channel {chat_id}"
    except Exception as e:
        await message.answer(
            i18n.gettext("admin-error").format(error=f"Cannot fetch channel name: {str(e)}")
        )
        await state.clear()
        return

    # Add channel immediately
    async with db_manager.session() as session:
        policy_service = PolicyService(session, bot)

        try:
            new_channel = await policy_service.add_channel(
                policy_id=policy_id,
                chat_id=chat_id,
                admin_id=user.id,
                display_name=display_name,
                channel_link=input_text,
            )

            # Notify existing users with ACTIVE grants about new channel
            from bot.config.settings import settings
            from bot.services.membership_service import MembershipService

            membership_service = MembershipService(session, bot)
            affected, notified = await membership_service.notify_existing_users_about_new_channel(
                policy_id, new_channel, i18n, settings.GRACE_PERIOD_MINUTES
            )

            await session.commit()

            success_msg = i18n.gettext("admin-channel-added").format(
                policy_id=str(policy_id),
                channel_name=display_name,
                kind=i18n.gettext("admin-kind-required"),
            )
            if affected > 0:
                success_msg += i18n.gettext("admin-users-notified-suffix").format(
                    notified=notified, affected=affected
                )

            await message.answer(success_msg, parse_mode="HTML")

            logger.info(
                "admin_channel_added",
                admin_id=user.id,
                policy_id=str(policy_id),
                chat_id=chat_id,
                affected_users=affected,
                notified_users=notified,
            )
        except Exception as e:
            await message.answer(i18n.gettext("admin-error").format(error=str(e)))
            logger.error(
                "admin_channel_addition_failed", admin_id=user.id, error=str(e)
            )

    await state.clear()


@router.callback_query(F.data.startswith("admin:deactivate:"))
async def admin_deactivate_policy(
    callback: CallbackQuery, bot: Bot, i18n: I18n
) -> None:
    """Handle policy deactivation callback.

    Args:
        callback: Callback query
        bot: Bot instance
        i18n: I18n instance for translations
    """
    user = callback.from_user
    if not user:
        return

    if not callback.data:
        await callback.answer(i18n.gettext("admin-callback-error"))
        return

    policy_id_str = callback.data.split(":", 2)[2]
    try:
        policy_id = UUID(policy_id_str)
    except ValueError:
        await callback.answer(i18n.gettext("admin-invalid-policy-id"))
        return

    async with db_manager.session() as session:
        result = await session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            await callback.answer(i18n.gettext("admin-policy-not-found"))
            return

        policy.is_active = False

        await callback.message.edit_text(
            i18n.gettext("admin-policy-deactivated").format(title=policy.title),
            parse_mode="HTML",
        )

    await callback.answer()
    logger.info("admin_policy_deactivated", admin_id=user.id, policy_id=str(policy_id))


@router.callback_query(F.data.startswith("admin:policy:"))
async def admin_policy_view(callback: CallbackQuery, i18n: I18n) -> None:
    """Handle policy view/edit callback.

    Args:
        callback: Callback query
        i18n: I18n instance for translations
    """
    user = callback.from_user
    if not user:
        return

    if not callback.data:
        await callback.answer(i18n.gettext("admin-callback-error"))
        return

    policy_id_str = callback.data.split(":", 2)[2]
    try:
        policy_id = UUID(policy_id_str)
    except ValueError:
        await callback.answer(i18n.gettext("admin-invalid-policy-id"))
        return

    async with db_manager.session() as session:
        result = await session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            await callback.answer(i18n.gettext("admin-policy-not-found"))
            return

        status = (
            i18n.gettext("admin-status-active")
            if policy.is_active
            else i18n.gettext("admin-status-inactive")
        )
        text = i18n.gettext("admin-policy-details").format(
            title=policy.title,
            id=str(policy.id),
            status=status,
            chat_id=policy.protected_chat_id,
        )

        await callback.message.edit_text(
            text,
            reply_markup=policy_management_keyboard(
                i18n, str(policy.id), policy.is_active
            ),
            parse_mode="HTML",
        )

    await callback.answer()
    logger.info("admin_policy_viewed", admin_id=user.id, policy_id=str(policy_id))


@router.callback_query(F.data.startswith("admin:add_required:"))
async def admin_add_required_callback(
    callback: CallbackQuery, state: FSMContext, i18n: I18n
) -> None:
    """Handle add required channel callback.

    Args:
        callback: Callback query
        state: FSM context
        i18n: I18n instance for translations
    """
    user = callback.from_user
    if not user:
        return

    if not callback.data:
        await callback.answer(i18n.gettext("admin-callback-error"))
        return

    policy_id_str = callback.data.split(":", 2)[2]
    try:
        policy_id = UUID(policy_id_str)
    except ValueError:
        await callback.answer(i18n.gettext("admin-invalid-policy-id"))
        return

    await state.update_data(policy_id=str(policy_id))
    await state.set_state(ChannelAddStates.waiting_for_chat_id)
    await callback.message.answer(i18n.gettext("admin-enter-channel-chat-id"))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:reactivate:"))
async def admin_reactivate_policy(
    callback: CallbackQuery, bot: Bot, i18n: I18n
) -> None:
    """Handle policy reactivation callback.

    Args:
        callback: Callback query
        bot: Bot instance
        i18n: I18n instance for translations
    """
    user = callback.from_user
    if not user:
        return

    if not callback.data:
        await callback.answer(i18n.gettext("admin-callback-error"))
        return

    policy_id_str = callback.data.split(":", 2)[2]
    try:
        policy_id = UUID(policy_id_str)
    except ValueError:
        await callback.answer(i18n.gettext("admin-invalid-policy-id"))
        return

    async with db_manager.session() as session:
        policy_service = PolicyService(session, bot)

        try:
            policy = await policy_service.reactivate_policy(
                policy_id=policy_id, admin_id=user.id
            )

            await callback.message.edit_text(
                i18n.gettext("admin-policy-reactivated").format(title=policy.title),
                reply_markup=policy_management_keyboard(
                    i18n, str(policy.id), policy.is_active
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            await callback.answer(
                i18n.gettext("admin-error").format(error=str(e)), show_alert=True
            )
            return

    await callback.answer()
    logger.info("admin_policy_reactivated", admin_id=user.id, policy_id=str(policy_id))


@router.callback_query(F.data.startswith("admin:edit_link:"))
async def admin_edit_link_callback(
    callback: CallbackQuery, state: FSMContext, i18n: I18n
) -> None:
    """Handle edit protected channel link callback.

    Args:
        callback: Callback query
        state: FSM context
        i18n: I18n instance for translations
    """
    user = callback.from_user
    if not user:
        return

    if not callback.data:
        await callback.answer(i18n.gettext("admin-callback-error"))
        return

    policy_id_str = callback.data.split(":", 2)[2]
    try:
        policy_id = UUID(policy_id_str)
    except ValueError:
        await callback.answer(i18n.gettext("admin-invalid-policy-id"))
        return

    async with db_manager.session() as session:
        result = await session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            await callback.answer(i18n.gettext("admin-policy-not-found"))
            return

        await state.update_data(policy_id=str(policy_id))
        await state.set_state(PolicyEditStates.waiting_for_new_link)
        await callback.message.answer(
            i18n.gettext("admin-enter-new-link").format(
                current_link=policy.protected_channel_link
            )
        )

    await callback.answer()
    logger.info("admin_edit_link_started", admin_id=user.id, policy_id=str(policy_id))


@router.message(PolicyEditStates.waiting_for_new_link)
async def admin_edit_link_process(
    message: Message, state: FSMContext, i18n: I18n
) -> None:
    """Process new protected channel link.

    Args:
        message: Message with new link
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        await state.clear()
        return

    if not message.text:
        await message.answer(i18n.gettext("admin-invalid-input"))
        return

    from bot.utils.validators import validate_channel_link

    new_link = message.text.strip()

    # Validate new link
    is_valid, error = validate_channel_link(new_link)
    if not is_valid:
        await message.answer(i18n.gettext("admin-error").format(error=error))
        return

    data = await state.get_data()
    policy_id = UUID(data["policy_id"])

    async with db_manager.session() as session:
        result = await session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            await message.answer(i18n.gettext("admin-policy-not-found"))
            await state.clear()
            return

        old_link = policy.protected_channel_link
        policy.protected_channel_link = new_link
        await session.commit()

        await message.answer(
            i18n.gettext("admin-channel-link-updated").format(
                old_link=old_link, new_link=new_link
            ),
            parse_mode="HTML",
        )

        logger.info(
            "admin_policy_link_updated", admin_id=user.id, policy_id=str(policy_id)
        )

    await state.clear()


@router.callback_query(F.data.startswith("admin:list_channels:"))
async def admin_list_channels(callback: CallbackQuery, i18n: I18n) -> None:
    """Handle list policy channels callback.

    Args:
        callback: Callback query
        i18n: I18n instance for translations
    """
    user = callback.from_user
    if not user:
        return

    if not callback.data:
        await callback.answer(i18n.gettext("admin-callback-error"))
        return

    policy_id_str = callback.data.split(":", 2)[2]
    try:
        policy_id = UUID(policy_id_str)
    except ValueError:
        await callback.answer(i18n.gettext("admin-invalid-policy-id"))
        return

    async with db_manager.session() as session:
        result = await session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            await callback.answer(i18n.gettext("admin-policy-not-found"))
            return

        # Get all channels for this policy
        result = await session.execute(
            select(PolicyChannel)
            .where(PolicyChannel.policy_id == policy_id)
            .order_by(PolicyChannel.position)
        )
        channels = result.scalars().all()

        if not channels:
            await callback.answer(i18n.gettext("admin-no-channels"), show_alert=True)
            return

        text = i18n.gettext("admin-channels-in-policy").format(title=policy.title)
        text += i18n.gettext("admin-required-channels")

        for ch in channels:
            link = (
                ch.channel_link
                if ch.channel_link
                else f"https://t.me/c/{abs(ch.telegram_chat_id)}"
            )
            text += f"• <a href='{link}'>{ch.display_name}</a> (<code>{ch.telegram_chat_id}</code>)\n"
            text += f"  {i18n.gettext('admin-remove-cmd')}: <code>/admin_channel_remove {ch.id}</code>\n"
        text += "\n"

        # Get policy to check is_active status
        result = await session.execute(
            select(AccessPolicy).where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one()

        await callback.message.edit_text(
            text,
            reply_markup=policy_management_keyboard(
                i18n, str(policy.id), policy.is_active
            ),
            parse_mode="HTML",
        )

    await callback.answer()
    logger.info(
        "admin_channels_listed",
        admin_id=user.id,
        policy_id=str(policy_id),
        count=len(channels),
    )


@router.callback_query(F.data == "admin:policy_list")
async def admin_policy_list_callback(callback: CallbackQuery, i18n: I18n) -> None:
    """Handle back to policy list callback.

    Args:
        callback: Callback query
        i18n: I18n instance for translations
    """
    user = callback.from_user
    if not user:
        return

    async with db_manager.session() as session:
        result = await session.execute(
            select(AccessPolicy).order_by(AccessPolicy.created_at.desc()).limit(10)
        )
        policies = result.scalars().all()

        if not policies:
            await callback.message.edit_text(i18n.gettext("admin-policies-not-found"))
            await callback.answer()
            return

        text = i18n.gettext("admin-policies-title")
        for policy in policies:
            status = "✅" if policy.is_active else "❌"
            text += f"{status} <code>{policy.id}</code>\n"
            text += f"   <b>{policy.title}</b>\n"
            text += f"   {i18n.gettext('admin-label-chat-id')}: <code>{policy.protected_chat_id}</code>\n\n"

        await callback.message.edit_text(text, parse_mode="HTML")

    await callback.answer()
    logger.info("admin_policies_listed_callback", admin_id=user.id)


@router.message(Command("admin_compliance_scan"))
async def admin_run_compliance_scan(
    message: Message, bot: Bot, state: FSMContext, i18n: I18n
) -> None:
    """Manually trigger daily compliance scan (admin only).

    Args:
        message: Incoming message
        bot: Bot instance
        state: FSM context
        i18n: I18n instance for translations
    """
    user = message.from_user
    if not user:
        return

    # Clear any active FSM state
    await state.clear()

    await message.answer(i18n.gettext("admin-compliance-scan-started"))

    try:
        await daily_compliance_scan(bot)
        await message.answer(i18n.gettext("admin-compliance-scan-completed"))
        logger.info("admin_manual_compliance_scan_triggered", admin_id=user.id)
    except Exception as e:
        await message.answer(
            i18n.gettext("admin-compliance-scan-failed").format(error=str(e))
        )
        logger.error(
            "admin_manual_compliance_scan_failed", admin_id=user.id, error=str(e)
        )
