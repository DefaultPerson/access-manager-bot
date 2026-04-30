from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config.settings import settings
from bot.core.db import db_manager
from bot.core.i18n import i18n
from bot.core.logger import get_logger
from bot.keyboards.inline.channels import (
    join_requirements_keyboard,
    ok_dismiss_keyboard,
)
from bot.models import (
    AccessPolicy,
    EventType,
    GrantStatus,
    MembershipGrant,
    PolicyChannel,
)
from bot.services.audit_service import AuditService
from bot.services.compliance_service import ComplianceService
from bot.services.membership_service import MembershipService

logger = get_logger(__name__)


async def grace_expiry_watcher(bot: Bot) -> None:
    """Watch for expired grace periods and revoke access.

    Runs every few minutes to check for grants with expired grace periods.
    Revokes access and removes users from protected channels.

    Args:
        bot: Bot instance
    """
    logger.info("grace_expiry_watcher_started")

    expired_count = 0
    errors_count = 0

    try:
        async with db_manager.session() as session:
            now = datetime.now(timezone.utc)

            # Get all grants in GRACE status with expired grace_expires_at
            # Skip grants with NULL grace_expires_at (preventive cascade, not yet expired)
            result = await session.execute(
                select(MembershipGrant)
                .options(
                    selectinload(MembershipGrant.policy),
                    selectinload(MembershipGrant.missing_channels),
                    selectinload(MembershipGrant.user),
                )
                .where(
                    MembershipGrant.status == GrantStatus.GRACE,
                    MembershipGrant.grace_expires_at.is_not(None),
                    MembershipGrant.grace_expires_at <= now,
                )
                .order_by(MembershipGrant.grace_expires_at)
            )
            expired_grants = result.scalars().all()

            compliance_service = ComplianceService(session, bot)
            audit_service = AuditService(session, bot)

            for grant in expired_grants:
                try:
                    policy = grant.policy

                    # Revoke access
                    grant.status = GrantStatus.REVOKED
                    grant.grace_expires_at = None

                    # Remove user from protected channel
                    await compliance_service.remove_and_unban(
                        chat_id=policy.protected_chat_id,
                        user_id=grant.user_id,
                    )

                    # Log revocation BEFORE cascade (in case cascade fails)
                    await audit_service.log_event(
                        EventType.USER_REVOKED,
                        policy_id=policy.id,
                        user_id=grant.user_id,
                        details={"reason": "grace_expired"},
                    )

                    # Get user's preferred language or use default
                    locale = (
                        grant.user.preferred_language
                        if grant.user and grant.user.preferred_language
                        else settings.DEFAULT_LANG
                    )

                    # Notify user about revocation BEFORE cascade (in case cascade fails)
                    # Use explicit query instead of grant.missing_channels to avoid lazy load
                    policy_channels = []
                    channels_list = ""

                    try:
                        # Explicitly load all required channels for this policy
                        result = await session.execute(
                            select(PolicyChannel).where(
                                PolicyChannel.policy_id == policy.id
                            )
                        )
                        policy_channels = result.scalars().all()
                        if policy_channels:
                            channels_list = "\n".join(
                                [
                                    f"• <a href='{ch.channel_link}'>{ch.display_name or str(ch.telegram_chat_id)}</a>"
                                    for ch in policy_channels
                                ]
                            )
                    except Exception as load_error:
                        logger.warning(
                            "failed_to_load_policy_channels",
                            policy_id=str(policy.id),
                            error=str(load_error),
                        )
                        channels_list = i18n.gettext(
                            "grace-fallback-missing-channels", locale=locale
                        )

                    text = i18n.gettext(
                        "revoked-message",
                        locale=locale,
                    ).format(
                        channel_name=policy.title,
                        missing_channels=(
                            channels_list
                            if channels_list
                            else i18n.gettext(
                                "grace-fallback-missing-channels", locale=locale
                            )
                        ),
                    )

                    logger.info(
                        "sending_revocation_notification",
                        user_id=grant.user_id,
                        policy_id=str(policy.id),
                        channels_count=len(policy_channels),
                    )

                    try:
                        keyboard = ok_dismiss_keyboard(i18n)
                        await bot.send_message(grant.user_id, text, reply_markup=keyboard)
                        logger.info(
                            "revocation_notification_sent",
                            user_id=grant.user_id,
                            policy_id=str(policy.id),
                        )
                    except Exception as send_error:
                        logger.warning(
                            "revocation_notification_failed",
                            user_id=grant.user_id,
                            policy_id=str(policy.id),
                            error=str(send_error),
                        )

                    logger.info(
                        "grace_expired_revoked",
                        policy_id=str(policy.id),
                        user_id=grant.user_id,
                    )

                    # Cascade check: if kicked channel is required in OTHER policies,
                    # transition those grants to GRACE (don't rely on events due to race condition)
                    result = await session.execute(
                        select(PolicyChannel).where(
                            PolicyChannel.telegram_chat_id == policy.protected_chat_id
                        )
                    )
                    affected_policy_channels = result.scalars().all()

                    if affected_policy_channels:
                        affected_policy_ids = [
                            pc.policy_id for pc in affected_policy_channels
                        ]

                        # Find grants for this user in affected policies (all statuses except REVOKED)
                        result = await session.execute(
                            select(MembershipGrant)
                            .options(
                                selectinload(MembershipGrant.policy).selectinload(
                                    AccessPolicy.channels
                                ),
                                selectinload(MembershipGrant.user),
                                selectinload(MembershipGrant.missing_channels),
                            )
                            .where(
                                MembershipGrant.user_id == grant.user_id,
                                MembershipGrant.policy_id.in_(affected_policy_ids),
                                MembershipGrant.status.in_(
                                    [
                                        GrantStatus.ACTIVE,
                                        GrantStatus.GRACE,
                                        GrantStatus.NEEDS_REVIEW,
                                    ]
                                ),
                            )
                        )
                        cascade_grants = result.scalars().all()

                        # Create membership service once for all cascade grants
                        membership_service_cascade = MembershipService(session, bot)

                        for cascade_grant in cascade_grants:
                            # Skip the current grant (already being revoked)
                            if cascade_grant.id == grant.id:
                                continue

                            # Invalidate cache for all channels in this policy
                            for channel in cascade_grant.policy.channels:
                                await membership_service_cascade.invalidate_membership_cache(
                                    channel.telegram_chat_id, grant.user_id
                                )

                            # Check compliance
                            is_compliant, missing_channels = (
                                await membership_service_cascade.check_compliance(
                                    cascade_grant.policy_id, grant.user_id
                                )
                            )

                            if not is_compliant:
                                old_cascade_status = cascade_grant.status

                                # Load missing channel objects
                                missing_channel_objs = await membership_service_cascade.load_missing_channel_objects(
                                    missing_channels
                                )

                                # Update missing channels for all statuses
                                cascade_grant.missing_channels = list(
                                    missing_channel_objs
                                )
                                cascade_grant.last_checked_at = datetime.now(
                                    timezone.utc
                                )

                                if old_cascade_status == GrantStatus.ACTIVE:
                                    # ACTIVE → GRACE (start grace period)
                                    cascade_grant.status = GrantStatus.GRACE
                                    cascade_grant.grace_expires_at = datetime.now(
                                        timezone.utc
                                    ) + timedelta(minutes=settings.GRACE_PERIOD_MINUTES)

                                    await audit_service.log_event(
                                        EventType.GRACE_STARTED,
                                        policy_id=cascade_grant.policy_id,
                                        user_id=grant.user_id,
                                        details={
                                            "missing_channels_count": len(
                                                missing_channels
                                            ),
                                            "trigger": "cascade_from_kick",
                                            "source_policy": str(policy.id),
                                        },
                                    )

                                    # Send grace notification
                                    cascade_policy = cascade_grant.policy
                                    grace_minutes = settings.GRACE_PERIOD_MINUTES

                                    # Get user's preferred language
                                    cascade_locale = (
                                        cascade_grant.user.preferred_language
                                        if cascade_grant.user
                                        and cascade_grant.user.preferred_language
                                        else settings.DEFAULT_LANG
                                    )

                                    grace_text = i18n.gettext(
                                        "grace-message",
                                        locale=cascade_locale,
                                    ).format(
                                        channel_name=cascade_policy.title,
                                        grace_minutes=grace_minutes,
                                    )

                                    keyboard = join_requirements_keyboard(
                                        i18n,
                                        list(missing_channel_objs),
                                        str(cascade_grant.policy_id),
                                        locale=cascade_locale
                                    )

                                    try:
                                        await bot.send_message(
                                            grant.user_id, grace_text, reply_markup=keyboard
                                        )
                                    except Exception as send_error:
                                        logger.warning(
                                            "cascade_grace_notification_failed",
                                            user_id=grant.user_id,
                                            policy_id=str(cascade_grant.policy_id),
                                            error=str(send_error),
                                        )

                                    logger.info(
                                        "cascade_grace_started",
                                        user_id=grant.user_id,
                                        policy_id=str(cascade_grant.policy_id),
                                        source_policy=str(policy.id),
                                        missing_count=len(missing_channels),
                                    )

                                elif old_cascade_status == GrantStatus.GRACE:
                                    # Already in GRACE - update missing_channels
                                    # If grace_expires_at is NULL (preventive cascade), set it now
                                    # Otherwise keep existing grace_expires_at and send notification

                                    # Send cascade notification
                                    cascade_policy = cascade_grant.policy

                                    # Calculate remaining grace time
                                    if cascade_grant.grace_expires_at:
                                        remaining = (
                                            cascade_grant.grace_expires_at
                                            - datetime.now(timezone.utc)
                                        )
                                        grace_minutes = max(
                                            1, int(remaining.total_seconds() // 60)
                                        )
                                    else:
                                        # Preventive cascade - set grace_expires_at now
                                        cascade_grant.grace_expires_at = datetime.now(
                                            timezone.utc
                                        ) + timedelta(minutes=settings.GRACE_PERIOD_MINUTES)
                                        grace_minutes = settings.GRACE_PERIOD_MINUTES

                                        await audit_service.log_event(
                                            EventType.GRACE_STARTED,
                                            policy_id=cascade_grant.policy_id,
                                            user_id=grant.user_id,
                                            details={
                                                "missing_channels_count": len(missing_channels),
                                                "trigger": "cascade_from_kick_preventive",
                                                "source_policy": str(policy.id),
                                            },
                                        )

                                    # Get user's preferred language
                                    cascade_locale = (
                                        cascade_grant.user.preferred_language
                                        if cascade_grant.user
                                        and cascade_grant.user.preferred_language
                                        else settings.DEFAULT_LANG
                                    )

                                    grace_text = i18n.gettext(
                                        "grace-message",
                                        locale=cascade_locale,
                                    ).format(
                                        channel_name=cascade_policy.title,
                                        grace_minutes=grace_minutes,
                                    )

                                    keyboard = join_requirements_keyboard(
                                        i18n,
                                        list(missing_channel_objs),
                                        str(cascade_grant.policy_id),
                                        locale=cascade_locale
                                    )

                                    try:
                                        await bot.send_message(
                                            grant.user_id,
                                            grace_text,
                                            reply_markup=keyboard,
                                        )
                                    except Exception as send_error:
                                        logger.warning(
                                            "cascade_grace_notification_failed",
                                            user_id=grant.user_id,
                                            policy_id=str(cascade_grant.policy_id),
                                            error=str(send_error),
                                        )

                                    logger.info(
                                        "cascade_grace_updated",
                                        user_id=grant.user_id,
                                        policy_id=str(cascade_grant.policy_id),
                                        source_policy=str(policy.id),
                                        missing_count=len(missing_channels),
                                    )

                                elif old_cascade_status == GrantStatus.NEEDS_REVIEW:
                                    # NEEDS_REVIEW - update missing_channels, keep status
                                    # User hasn't been accepted yet
                                    logger.info(
                                        "cascade_needs_review_updated",
                                        user_id=grant.user_id,
                                        policy_id=str(cascade_grant.policy_id),
                                        source_policy=str(policy.id),
                                        missing_count=len(missing_channels),
                                    )

                    expired_count += 1

                except Exception as e:
                    errors_count += 1
                    logger.exception(
                        "grace_expiry_processing_error",
                        grant_id=str(grant.id),
                        user_id=grant.user_id,
                        error=str(e),
                    )

            # Commit all changes
            await session.commit()

    except Exception as e:
        logger.error("grace_expiry_watcher_failed", error=str(e))

    logger.info(
        "grace_expiry_watcher_completed",
        expired=expired_count,
        errors=errors_count,
    )
