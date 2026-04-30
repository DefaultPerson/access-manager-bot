from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config.settings import settings
from bot.core.db import db_manager
from bot.core.i18n import i18n
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
from bot.services.membership_service import MembershipService

logger = get_logger(__name__)


async def grace_restoration_watcher(bot: Bot) -> None:
    """Periodically check GRACE grants for automatic restoration.

    This provides automatic restoration even when bot is not admin in required channels
    and cannot receive ChatMemberUpdated events. Acts as a backup mechanism to ensure
    users are restored to ACTIVE status when they rejoin required channels.

    Runs every 1-2 minutes to check all grants in GRACE status.

    Args:
        bot: Bot instance
    """
    logger.info("grace_restoration_watcher_started")

    restored_count = 0
    checked_count = 0
    errors_count = 0
    skipped_count = 0

    try:
        async with db_manager.session() as session:
            now = datetime.now(timezone.utc)

            # Get all grants in GRACE status (not yet expired)
            # Skip grants with NULL grace_expires_at (preventive cascade, not yet expired)
            result = await session.execute(
                select(MembershipGrant)
                .options(
                    selectinload(MembershipGrant.policy).selectinload(
                        AccessPolicy.channels
                    ),
                    selectinload(MembershipGrant.missing_channels),
                    selectinload(MembershipGrant.user),
                )
                .where(
                    MembershipGrant.status == GrantStatus.GRACE,
                    MembershipGrant.grace_expires_at.is_not(None),
                    MembershipGrant.grace_expires_at > now,  # Only non-expired
                )
                .order_by(MembershipGrant.grace_expires_at)
            )
            grace_grants = result.scalars().all()

            if not grace_grants:
                logger.info("grace_restoration_watcher_completed_no_grants")
                return

            membership_service = MembershipService(session, bot)
            audit_service = AuditService(session, bot)

            for grant in grace_grants:
                try:
                    checked_count += 1
                    policy = grant.policy
                    user_id = grant.user_id

                    # Check if this grant depends on another GRACE grant (preventive cascade)
                    # Skip restoration if source policy is still in GRACE
                    should_skip = False
                    for missing_channel in grant.missing_channels:
                        # Find policy protecting this missing channel
                        result_protecting = await session.execute(
                            select(AccessPolicy).where(
                                AccessPolicy.protected_chat_id == missing_channel.telegram_chat_id
                            )
                        )
                        protecting_policy = result_protecting.scalar_one_or_none()

                        if protecting_policy:
                            # Check if user has GRACE grant for that policy
                            result_source_grace = await session.execute(
                                select(MembershipGrant).where(
                                    MembershipGrant.policy_id == protecting_policy.id,
                                    MembershipGrant.user_id == user_id,
                                    MembershipGrant.status == GrantStatus.GRACE,
                                )
                            )
                            source_grace_grant = result_source_grace.scalar_one_or_none()

                            if source_grace_grant:
                                # This grant depends on another GRACE grant
                                # Don't restore yet - cascade restoration will handle it
                                should_skip = True
                                logger.debug(
                                    "grace_restoration_skipped_cascade_dependency",
                                    grant_id=str(grant.id),
                                    user_id=user_id,
                                    dependent_policy=policy.title,
                                    source_policy=protecting_policy.title,
                                )
                                break

                    if should_skip:
                        skipped_count += 1
                        continue

                    # Invalidate cache for ALL channels in this policy
                    for channel in policy.channels:
                        await membership_service.invalidate_membership_cache(
                            channel.telegram_chat_id, user_id
                        )

                    # Check compliance
                    is_compliant, _ = await membership_service.check_compliance(
                        policy.id, user_id
                    )

                    if is_compliant:
                        # Restore to ACTIVE
                        grant.status = GrantStatus.ACTIVE
                        grant.missing_channels = []
                        grant.grace_expires_at = None
                        grant.last_checked_at = datetime.now(timezone.utc)

                        await audit_service.log_event(
                            EventType.GRACE_RESOLVED,
                            policy_id=policy.id,
                            user_id=user_id,
                            details={
                                "trigger": "grace_restoration_watcher",
                            },
                        )

                        # Send restoration notification
                        locale = (
                            grant.user.preferred_language
                            if grant.user and grant.user.preferred_language
                            else settings.DEFAULT_LANG
                        )

                        text = i18n.gettext(
                            "compliance-restored", locale=locale
                        ).format(channel_name=policy.title)

                        keyboard = ok_dismiss_keyboard(i18n)

                        try:
                            await bot.send_message(user_id, text, reply_markup=keyboard)
                            logger.info(
                                "grace_auto_restored",
                                user_id=user_id,
                                policy_id=str(policy.id),
                            )
                        except Exception as send_error:
                            logger.warning(
                                "grace_auto_restore_notification_failed",
                                user_id=user_id,
                                policy_id=str(policy.id),
                                error=str(send_error),
                            )

                        restored_count += 1

                        # Cascade restoration: if restored channel is required in OTHER policies,
                        # check and restore those grants too
                        result = await session.execute(
                            select(PolicyChannel).where(
                                PolicyChannel.telegram_chat_id
                                == policy.protected_chat_id
                            )
                        )
                        cascade_policy_channels = result.scalars().all()

                        if cascade_policy_channels:
                            cascade_policy_ids = [
                                pc.policy_id for pc in cascade_policy_channels
                            ]

                            # Find user's grants for these policies (GRACE or NEEDS_REVIEW)
                            result = await session.execute(
                                select(MembershipGrant)
                                .options(
                                    selectinload(MembershipGrant.policy).selectinload(
                                        AccessPolicy.channels
                                    ),
                                    selectinload(MembershipGrant.user),
                                )
                                .where(
                                    MembershipGrant.user_id == user_id,
                                    MembershipGrant.policy_id.in_(cascade_policy_ids),
                                    MembershipGrant.status.in_(
                                        [GrantStatus.GRACE, GrantStatus.NEEDS_REVIEW]
                                    ),
                                )
                            )
                            cascade_grants = result.scalars().all()

                            for cascade_grant in cascade_grants:
                                # Invalidate cache for all channels in cascade policy
                                for channel in cascade_grant.policy.channels:
                                    await membership_service.invalidate_membership_cache(
                                        channel.telegram_chat_id, user_id
                                    )

                                # Check compliance
                                cascade_is_compliant, _ = (
                                    await membership_service.check_compliance(
                                        cascade_grant.policy_id, user_id
                                    )
                                )

                                if cascade_is_compliant:
                                    # Restore to ACTIVE
                                    old_cascade_status = cascade_grant.status
                                    cascade_grant.status = GrantStatus.ACTIVE
                                    cascade_grant.missing_channels = []
                                    cascade_grant.grace_expires_at = None
                                    cascade_grant.last_checked_at = datetime.now(
                                        timezone.utc
                                    )

                                    await audit_service.log_event(
                                        EventType.GRACE_RESOLVED,
                                        policy_id=cascade_grant.policy_id,
                                        user_id=user_id,
                                        details={
                                            "previous_status": (
                                                old_cascade_status.value
                                                if hasattr(old_cascade_status, "value")
                                                else old_cascade_status
                                            ),
                                            "trigger": "cascade_restoration_watcher",
                                            "source_policy": str(policy.id),
                                        },
                                    )

                                    # Send restoration notification
                                    cascade_locale = (
                                        cascade_grant.user.preferred_language
                                        if cascade_grant.user
                                        and cascade_grant.user.preferred_language
                                        else settings.DEFAULT_LANG
                                    )

                                    cascade_text = i18n.gettext(
                                        "compliance-restored", locale=cascade_locale
                                    ).format(channel_name=cascade_grant.policy.title)

                                    cascade_keyboard = ok_dismiss_keyboard(i18n)

                                    try:
                                        await bot.send_message(
                                            user_id,
                                            cascade_text,
                                            reply_markup=cascade_keyboard,
                                        )
                                    except Exception as cascade_send_error:
                                        logger.warning(
                                            "cascade_restoration_watcher_notification_failed",
                                            user_id=user_id,
                                            policy_id=str(cascade_grant.policy_id),
                                            error=str(cascade_send_error),
                                        )

                                    logger.info(
                                        "cascade_restoration_watcher_completed",
                                        user_id=user_id,
                                        policy_id=str(cascade_grant.policy_id),
                                        source_policy=str(policy.id),
                                    )

                except Exception as e:
                    errors_count += 1
                    logger.exception(
                        "grace_restoration_processing_error",
                        grant_id=str(grant.id),
                        user_id=grant.user_id,
                        policy_id=str(grant.policy_id),
                        error=str(e),
                    )

            # Commit all changes
            await session.commit()

    except Exception as e:
        logger.error("grace_restoration_watcher_failed", error=str(e))

    logger.info(
        "grace_restoration_watcher_completed",
        checked=checked_count,
        restored=restored_count,
        errors=errors_count,
        skipped=skipped_count,
    )
