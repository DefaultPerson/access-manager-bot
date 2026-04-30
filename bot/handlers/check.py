import asyncio
from datetime import datetime, timezone
from typing import Tuple
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from aiogram.utils.i18n.core import I18n
from sqlalchemy import select
from sqlalchemy.engine.result import Result
from sqlalchemy.orm import selectinload

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.keyboards.inline.channels import ok_dismiss_keyboard
from bot.models import (
    AccessPolicy,
    EventType,
    GrantStatus,
    MembershipGrant,
    PolicyChannel,
)
from bot.services.audit_service import AuditService
from bot.services.cache_service import CacheService
from bot.services.membership_service import MembershipService

logger = get_logger(__name__)

router = Router()


async def delete_message_after_delay(
    bot: Bot, chat_id: int, message_id: int, delay: int
) -> None:
    """Delete message after specified delay.

    Args:
        bot: Bot instance
        chat_id: Chat ID
        message_id: Message ID to delete
        delay: Delay in seconds
    """
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
        logger.debug("message_deleted", chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug("message_delete_failed", error=str(e))


@router.callback_query(F.data.startswith("check:"))
async def check_callback(callback: CallbackQuery, bot: Bot, i18n: I18n) -> None:
    """Handle compliance check callback.

    Args:
        callback: Callback query with check:{policy_id} data
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
        # Acquire lock
        cache_service = CacheService()
        if not await cache_service.lock_eval(policy_id, user.id):
            await callback.answer("Check already in progress")
            return

        try:
            # Get policy with channels
            result = await session.execute(
                select(AccessPolicy)
                .options(selectinload(AccessPolicy.channels))
                .where(AccessPolicy.id == policy_id)
            )
            policy = result.scalar_one_or_none()

            if not policy:
                await callback.answer("Policy not found")
                return

            membership_service = MembershipService(session, bot)

            # Invalidate cache for ALL channels in this policy before compliance check
            # This ensures we check actual membership status, not stale cache
            for channel in policy.channels:
                await membership_service.invalidate_membership_cache(
                    channel.telegram_chat_id, user.id
                )

            # Check compliance with fresh cache
            is_compliant, missing_channels = await membership_service.check_compliance(
                policy_id, user.id
            )

            audit_service = AuditService(session, bot)

            if is_compliant:
                # User is compliant - approve or update grant
                result = await session.execute(
                    select(MembershipGrant)
                    .options(selectinload(MembershipGrant.missing_channels))
                    .where(
                        MembershipGrant.policy_id == policy_id,
                        MembershipGrant.user_id == user.id,
                    )
                )
                grant = result.scalar_one_or_none()

                if grant:
                    # Update existing grant
                    grant.status = GrantStatus.ACTIVE
                    grant.missing_channels = []
                    grant.grace_expires_at = None
                    grant.last_checked_at = datetime.now(timezone.utc)
                else:
                    # Create new grant
                    grant = MembershipGrant(
                        policy_id=policy_id,
                        user_id=user.id,
                        status=GrantStatus.ACTIVE,
                    )
                    session.add(grant)

                # Log approval
                await audit_service.log_event(
                    EventType.JOIN_APPROVED,
                    policy_id=policy_id,
                    user_id=user.id,
                    details={},
                )

                # Try to approve pending join request if exists
                join_request_approved = False
                try:
                    await bot.approve_chat_join_request(
                        policy.protected_chat_id, user.id
                    )
                    join_request_approved = True
                    logger.info(
                        "join_auto_approved",
                        user_id=user.id,
                        policy_id=str(policy_id),
                    )
                except TelegramBadRequest as e:
                    # No pending join request
                    logger.debug(
                        "no_pending_join_request", user_id=user.id, error=str(e)
                    )
                except Exception as e:
                    logger.warning(
                        "join_auto_approve_failed", user_id=user.id, error=str(e)
                    )

                # Prepare response message based on join request status
                if join_request_approved:
                    text = i18n.gettext("join-approved-plain").format(
                        channel_name=policy.title
                    )
                    keyboard = ok_dismiss_keyboard(i18n)
                    await bot.send_message(user.id, text, reply_markup=keyboard)
                    await callback.answer()
                else:
                    # User is compliant but has no pending join request
                    text = i18n.gettext("compliant-send-request").format(
                        channel_name=policy.title,
                    )
                    await callback.answer(text, show_alert=True)

            else:
                # User is missing channels
                # Load PolicyChannel objects from missing channel IDs
                missing_channel_ids = [UUID(ch["id"]) for ch in missing_channels]
                result: Result[Tuple] = await session.execute(
                    select(PolicyChannel).where(
                        PolicyChannel.id.in_(missing_channel_ids)
                    )
                )
                missing_channel_objs = result.scalars().all()

                # Update or create grant as NEEDS_REVIEW
                result = await session.execute(
                    select(MembershipGrant)
                    .options(selectinload(MembershipGrant.missing_channels))
                    .where(
                        MembershipGrant.policy_id == policy_id,
                        MembershipGrant.user_id == user.id,
                    )
                )
                grant = result.scalar_one_or_none()

                if grant:
                    # Keep GRACE status if grace_expires_at is set (user in grace period)
                    # Otherwise use NEEDS_REVIEW (new user or user without grace period)
                    if grant.grace_expires_at is None:
                        grant.status = GrantStatus.NEEDS_REVIEW
                    # else: keep current status (likely GRACE)

                    grant.missing_channels = list(missing_channel_objs)
                    grant.last_checked_at = datetime.now(timezone.utc)
                else:
                    grant = MembershipGrant(
                        policy_id=policy_id,
                        user_id=user.id,
                        status=GrantStatus.NEEDS_REVIEW,
                    )
                    grant.missing_channels = list(missing_channel_objs)
                    session.add(grant)

                # Log missing channels
                await audit_service.log_event(
                    EventType.MISSING_CHANNELS_SENT,
                    policy_id=policy_id,
                    user_id=user.id,
                    details={"missing_channels_count": len(missing_channels)},
                )

                text = i18n.gettext("missing-channels-message-plain").format(
                    channel_name=policy.title
                )
                await callback.answer(text, show_alert=True)

        finally:
            # Release lock
            await cache_service.unlock_eval(policy_id, user.id)

    logger.info(
        "compliance_checked",
        user_id=user.id,
        policy_id=str(policy_id),
        compliant=is_compliant,
    )


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_callback(callback: CallbackQuery, bot: Bot, i18n: I18n) -> None:
    """Handle confirm callback during grace period.

    Args:
        callback: Callback query with confirm:{policy_id} data
        bot: Bot instance
        i18n: I18n instance
    """
    user = callback.from_user
    if not user or not callback.data or not callback.message:
        await callback.answer("Error")
        return

    # Extract policy_id
    try:
        policy_id_str = callback.data.split(":", 1)[1]
        policy_id = UUID(policy_id_str)
    except (ValueError, IndexError):
        await callback.answer("Invalid policy ID")
        return

    # Check if user is compliant to decide whether to delete message
    async with db_manager.session() as session:
        # Load policy with channels
        result = await session.execute(
            select(AccessPolicy)
            .options(selectinload(AccessPolicy.channels))
            .where(AccessPolicy.id == policy_id)
        )
        policy = result.scalar_one_or_none()

        if not policy:
            await callback.answer("Policy not found")
            return

        membership_service = MembershipService(session, bot)

        # Invalidate cache for ALL channels before compliance check
        for channel in policy.channels:
            await membership_service.invalidate_membership_cache(
                channel.telegram_chat_id, user.id
            )

        is_compliant, _ = await membership_service.check_compliance(policy_id, user.id)

    # Re-run compliance check
    await check_callback(callback, bot, i18n)

    # If compliant, schedule message deletion after 5 seconds
    if is_compliant and callback.message:
        asyncio.create_task(
            delete_message_after_delay(
                bot, callback.message.chat.id, callback.message.message_id, 5
            )
        )


@router.callback_query(F.data.startswith("dismiss:"))
async def dismiss_callback(callback: CallbackQuery, bot: Bot) -> None:
    """Handle dismiss button callback - delete the message.

    Args:
        callback: Callback query with dismiss:ok data
        bot: Bot instance
    """
    if not callback.message:
        await callback.answer()
        return

    try:
        await bot.delete_message(callback.message.chat.id, callback.message.message_id)
        logger.debug(
            "message_dismissed",
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
    except Exception as e:
        logger.warning("message_dismiss_failed", error=str(e))

    await callback.answer()
