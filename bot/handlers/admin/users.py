"""Admin handlers for user management."""

from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n.core import I18n
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.filters.admin import IsAdmin
from bot.keyboards.inline.channels import users_pagination_keyboard
from bot.models import AccessPolicy, GrantStatus, MembershipGrant, PolicyChannel, UserProfile
from bot.services.membership_service import MembershipService

logger = get_logger(__name__)

router = Router()

USERS_PER_PAGE = 20


@router.message(Command("admin_users"), IsAdmin())
async def admin_users_command(message: Message, i18n: I18n) -> None:
    """Handle /admin_users command to display user list with pagination.

    Args:
        message: Incoming message
        i18n: I18n instance
    """
    user = message.from_user
    if not user:
        return

    await show_users_page(message, i18n, page=1)


@router.callback_query(F.data.startswith("users_page:"), IsAdmin())
async def users_pagination_callback(callback: CallbackQuery, i18n: I18n) -> None:
    """Handle pagination callbacks for user list.

    Args:
        callback: Callback query with users_page:{number} data
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

    await show_users_page(callback.message, i18n, page=page, edit=True)
    await callback.answer()


async def show_users_page(
    message: Message, i18n: I18n, page: int = 1, edit: bool = False
) -> None:
    """Show users list page.

    Args:
        message: Message to send/edit
        i18n: I18n instance
        page: Page number
        edit: Whether to edit existing message
    """
    async with db_manager.session() as session:
        # Get total count
        result = await session.execute(select(func.count(UserProfile.user_id)))
        total_users = result.scalar_one()

        if total_users == 0:
            text = i18n.gettext("admin-users-no-users")
            if edit:
                await message.edit_text(text)
            else:
                await message.answer(text)
            return

        # Calculate pagination
        total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
        offset = (page - 1) * USERS_PER_PAGE

        # Get page data
        result = await session.execute(
            select(UserProfile)
            .order_by(UserProfile.created_at.desc())
            .offset(offset)
            .limit(USERS_PER_PAGE)
        )
        users = result.scalars().all()

        # Build message text
        title = i18n.gettext("admin-users-title")
        page_info = i18n.gettext("admin-users-page-info").format(
            page=page, total_pages=total_pages, total=total_users
        )

        user_lines = []
        for idx, user_profile in enumerate(users, start=offset + 1):
            username = f"@{user_profile.username}" if user_profile.username else "—"
            full_name = user_profile.full_name or "—"
            user_lines.append(f"{idx}. ID: {user_profile.user_id} | {username} | {full_name}")

        text = f"{title}\n{page_info}\n\n" + "\n".join(user_lines)

        # Build keyboard
        keyboard = users_pagination_keyboard(i18n, page=page, total_pages=total_pages)

        if edit:
            await message.edit_text(text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)

    logger.info("admin_users_page_shown", page=page, total_users=total_users)


@router.message(Command("admin_user_sync"), IsAdmin())
async def admin_user_sync_command(message: Message, bot: Bot, i18n: I18n) -> None:
    """Handle /admin_user_sync command to actualize user membership.

    Args:
        message: Incoming message with format: /admin_user_sync <user_id>
        bot: Bot instance
        i18n: I18n instance
    """
    user = message.from_user
    if not user or not message.text:
        return

    # Parse user_id from command
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(i18n.gettext("admin-user-sync-usage"))
        return

    try:
        target_user_id = int(parts[1])
    except ValueError:
        await message.answer(i18n.gettext("admin-user-sync-invalid-id"))
        return

    async with db_manager.session() as session:
        # Verify user exists
        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == target_user_id)
        )
        user_profile = result.scalar_one_or_none()

        if not user_profile:
            await message.answer(i18n.gettext("admin-user-sync-user-not-found"))
            return

        # Send progress message
        progress_text = i18n.gettext("admin-user-sync-progress").format(
            user_id=target_user_id
        )
        progress_msg = await message.answer(progress_text)

        membership_service = MembershipService(session, bot)

        # Collect all unique chat_ids
        policy_channels_result = await session.execute(select(PolicyChannel))
        policy_channels = policy_channels_result.scalars().all()

        policies_result = await session.execute(select(AccessPolicy))
        policies = policies_result.scalars().all()

        chat_ids = set()
        for pc in policy_channels:
            chat_ids.add(pc.telegram_chat_id)
        for policy in policies:
            chat_ids.add(policy.protected_chat_id)

        # Check membership for each chat and populate cache
        checked = 0
        errors = 0
        for chat_id in chat_ids:
            try:
                # Invalidate cache first
                await membership_service.invalidate_membership_cache(
                    chat_id, target_user_id
                )
                # Fetch fresh data via API (this also populates cache)
                await membership_service.check_membership_live(chat_id, target_user_id)
                checked += 1
            except Exception as e:
                logger.warning(
                    "admin_user_sync_check_failed",
                    chat_id=chat_id,
                    user_id=target_user_id,
                    error=str(e),
                )
                errors += 1

        # Update grants for each policy
        updated_grants = 0
        for policy in policies:
            # Check compliance using fresh cache
            is_compliant, missing_channels = await membership_service.check_compliance(
                policy.id, target_user_id
            )

            # Load or create grant
            result = await session.execute(
                select(MembershipGrant)
                .options(selectinload(MembershipGrant.missing_channels))
                .where(
                    MembershipGrant.policy_id == policy.id,
                    MembershipGrant.user_id == target_user_id,
                )
            )
            grant = result.scalar_one_or_none()

            if is_compliant:
                # User is compliant
                if grant:
                    grant.status = GrantStatus.ACTIVE
                    grant.missing_channels = []
                    grant.grace_expires_at = None
                    grant.last_checked_at = datetime.now(timezone.utc)
                else:
                    # Create new ACTIVE grant
                    grant = MembershipGrant(
                        policy_id=policy.id,
                        user_id=target_user_id,
                        status=GrantStatus.ACTIVE,
                    )
                    session.add(grant)
                updated_grants += 1
            else:
                # User is not compliant
                missing_channel_objs = await membership_service.load_missing_channel_objects(
                    missing_channels
                )

                if grant:
                    # Don't override GRACE/REVOKED status, only update if ACTIVE or NEEDS_REVIEW
                    if grant.status in [GrantStatus.ACTIVE, GrantStatus.NEEDS_REVIEW]:
                        grant.status = GrantStatus.NEEDS_REVIEW
                        grant.missing_channels = list(missing_channel_objs)
                        grant.last_checked_at = datetime.now(timezone.utc)
                        # Keep grace_expires_at if exists
                        updated_grants += 1
                else:
                    # Create new NEEDS_REVIEW grant
                    grant = MembershipGrant(
                        policy_id=policy.id,
                        user_id=target_user_id,
                        status=GrantStatus.NEEDS_REVIEW,
                    )
                    grant.missing_channels = list(missing_channel_objs)
                    session.add(grant)
                    updated_grants += 1

        await session.commit()

        # Send completion message
        complete_text = i18n.gettext("admin-user-sync-complete").format(
            checked=checked, errors=errors, updated=updated_grants
        )
        await progress_msg.edit_text(complete_text)

    logger.info(
        "admin_user_sync_completed",
        admin_id=user.id,
        target_user_id=target_user_id,
        checked=checked,
        errors=errors,
        updated=updated_grants,
    )
