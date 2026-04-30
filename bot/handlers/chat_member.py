from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatMemberUpdated, Message
from aiogram.utils.i18n.core import I18n
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config.settings import settings
from bot.core.db import db_manager
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
from bot.services.membership_service import MembershipService

logger = get_logger(__name__)

router = Router()


@router.chat_member(F.chat.type.in_({"group", "supergroup", "channel"}))
async def chat_member_handler(update: ChatMemberUpdated, bot: Bot, i18n: I18n) -> None:
    """Handle chat member updates for event-driven compliance.

    Args:
        update: Chat member update event
        bot: Bot instance
        i18n: I18n instance
    """
    user_id = update.from_user.id
    chat_id = update.chat.id
    old_status = update.old_chat_member.status
    new_status = update.new_chat_member.status

    was_member = old_status in {"member", "administrator", "creator"}
    is_member = new_status in {"member", "administrator", "creator"}

    if was_member == is_member:
        # No membership change
        return

    async with db_manager.session() as session:
        # Upsert user profile
        from bot.services.user_service import UserService

        user_service = UserService(session)
        await user_service.upsert_profile(
            user_id=user_id,
            username=update.from_user.username,
            full_name=update.from_user.full_name,
        )

        # Create services (needed for all branches)
        membership_service = MembershipService(session, bot)
        audit_service = AuditService(session, bot)

        # Find all policies that reference this channel
        result = await session.execute(
            select(PolicyChannel).where(
                PolicyChannel.telegram_chat_id == chat_id,
            )
        )
        policy_channels = result.scalars().all()

        if not policy_channels:
            # This channel is not a requirement for any policy
            # BUT if user joined, we must check ALL their grants for cross-policy compliance
            if is_member:
                # Invalidate cache for this channel
                await membership_service.invalidate_membership_cache(chat_id, user_id)

                # Find ALL grants that might benefit from this join
                result = await session.execute(
                    select(MembershipGrant)
                    .options(selectinload(MembershipGrant.policy))
                    .where(
                        MembershipGrant.user_id == user_id,
                        MembershipGrant.status.in_([
                            GrantStatus.NEEDS_REVIEW,
                            GrantStatus.GRACE,
                        ]),
                    )
                )
                all_grants = result.scalars().all()

                for grant in all_grants:
                    # Load policy with channels
                    policy_result = await session.execute(
                        select(AccessPolicy)
                        .options(selectinload(AccessPolicy.channels))
                        .where(AccessPolicy.id == grant.policy_id)
                    )
                    policy = policy_result.scalar_one_or_none()

                    if not policy:
                        continue

                    # Invalidate cache for ALL channels in this policy
                    for channel in policy.channels:
                        await membership_service.invalidate_membership_cache(
                            channel.telegram_chat_id, user_id
                        )

                    # Check compliance
                    is_compliant, _ = await membership_service.check_compliance(
                        grant.policy_id, user_id
                    )

                    if is_compliant:
                        old_status = grant.status
                        grant.status = GrantStatus.ACTIVE
                        grant.missing_channels = []
                        grant.grace_expires_at = None
                        grant.last_checked_at = datetime.now(timezone.utc)

                        await audit_service.log_event(
                            EventType.GRACE_RESOLVED if old_status == GrantStatus.GRACE else EventType.JOIN_APPROVED,
                            policy_id=grant.policy_id,
                            user_id=user_id,
                            details={
                                "previous_status": (
                                    old_status.value
                                    if hasattr(old_status, "value")
                                    else old_status
                                ),
                                "trigger": "protected_only_channel_join",
                            },
                        )

                        # Try to approve pending join request
                        try:
                            await bot.approve_chat_join_request(
                                policy.protected_chat_id, user_id
                            )
                            logger.info(
                                "join_auto_approved_protected_only",
                                user_id=user_id,
                                policy_id=str(grant.policy_id),
                                trigger_channel=chat_id,
                                old_status=(
                                    old_status.value
                                    if hasattr(old_status, "value")
                                    else old_status
                                ),
                            )
                        except TelegramBadRequest:
                            # No pending request - fine
                            pass
                        except Exception as e:
                            logger.warning(
                                "join_auto_approve_failed_protected_only",
                                user_id=user_id,
                                policy_id=str(grant.policy_id),
                                error=str(e),
                            )

                # Commit all changes
                await session.commit()

            return

        # Get all grants for this user that might be affected (with pessimistic lock)
        policy_ids = [pc.policy_id for pc in policy_channels]
        result = await session.execute(
            select(MembershipGrant)
            .options(
                selectinload(MembershipGrant.policy).selectinload(AccessPolicy.channels),
                selectinload(MembershipGrant.missing_channels),
            )
            .where(
                MembershipGrant.user_id == user_id,
                MembershipGrant.policy_id.in_(policy_ids),
                MembershipGrant.status.in_([
                    GrantStatus.ACTIVE,
                    GrantStatus.GRACE,
                    GrantStatus.NEEDS_REVIEW,
                ]),
            )
            .with_for_update()
        )
        grants = result.scalars().all()

        if not grants:
            # User has no active grants affected by this channel
            # BUT we must invalidate cache so future compliance checks are accurate
            if is_member:
                # User joined - invalidate cache for this channel
                await membership_service.invalidate_membership_cache(chat_id, user_id)

                # Try to auto-approve pending join requests for OTHER policies
                # where this channel is required and user had NEEDS_REVIEW status
                result = await session.execute(
                    select(MembershipGrant)
                    .options(selectinload(MembershipGrant.policy))
                    .where(
                        MembershipGrant.user_id == user_id,
                        MembershipGrant.status == GrantStatus.NEEDS_REVIEW,
                    )
                )
                needs_review_grants = result.scalars().all()

                for grant in needs_review_grants:
                    # Invalidate cache for ALL channels in this policy (not just chat_id)
                    policy_result = await session.execute(
                        select(AccessPolicy)
                        .options(selectinload(AccessPolicy.channels))
                        .where(AccessPolicy.id == grant.policy_id)
                    )
                    policy = policy_result.scalar_one_or_none()

                    if not policy:
                        continue

                    for channel in policy.channels:
                        await membership_service.invalidate_membership_cache(
                            channel.telegram_chat_id, user_id
                        )

                    # Check if user is now compliant (cache is fresh after invalidation)
                    is_compliant, _ = await membership_service.check_compliance(
                        grant.policy_id, user_id
                    )
                    if is_compliant:
                        grant.status = GrantStatus.ACTIVE
                        grant.missing_channels = []
                        grant.grace_expires_at = None
                        grant.last_checked_at = datetime.now(timezone.utc)

                        # Try to approve pending join request
                        try:
                            await bot.approve_chat_join_request(
                                policy.protected_chat_id, user_id
                            )
                            logger.info(
                                "join_auto_approved_cross_policy",
                                user_id=user_id,
                                policy_id=str(grant.policy_id),
                                trigger_channel=chat_id,
                            )
                        except TelegramBadRequest:
                            # No pending request - fine
                            pass
                        except Exception as e:
                            logger.warning(
                                "join_auto_approve_failed_cross_policy",
                                user_id=user_id,
                                policy_id=str(grant.policy_id),
                                error=str(e),
                            )

                # Commit cross-policy updates
                await session.commit()

            return

        # Track which users we've already notified to avoid duplicates
        notified_users = set()

        if not is_member:
            # User LEFT a required channel - trigger grace or revocation
            for grant in grants:
                # Invalidate cache for ALL channels in policy before compliance check
                for channel in grant.policy.channels:
                    await membership_service.invalidate_membership_cache(
                        channel.telegram_chat_id, user_id
                    )

                # Recheck compliance
                is_compliant, missing_channels = (
                    await membership_service.check_compliance(grant.policy_id, user_id)
                )

                if not is_compliant:
                    # Load PolicyChannel objects from missing channel IDs
                    missing_channel_objs = (
                        await membership_service.load_missing_channel_objects(
                            missing_channels
                        )
                    )

                    # Only move to GRACE if user was previously ACTIVE
                    # Users with NEEDS_REVIEW stay in NEEDS_REVIEW
                    old_status = grant.status
                    if old_status == GrantStatus.ACTIVE or old_status == GrantStatus.GRACE:
                        grant.status = GrantStatus.GRACE
                        grant.missing_channels = list(missing_channel_objs)
                        grant.grace_expires_at = datetime.now(timezone.utc) + timedelta(
                            minutes=settings.GRACE_PERIOD_MINUTES
                        )
                        grant.last_checked_at = datetime.now(timezone.utc)

                        await audit_service.log_event(
                            EventType.GRACE_STARTED,
                            policy_id=grant.policy_id,
                            user_id=user_id,
                            details={"missing_channels_count": len(missing_channels)},
                        )

                        # Send grace period notification only once per user (avoid duplicates)
                        if user_id not in notified_users:
                            notified_users.add(user_id)

                            policy = grant.policy
                            grace_minutes = settings.GRACE_PERIOD_MINUTES

                            text = i18n.gettext("grace-message").format(
                                channel_name=policy.title,
                                grace_minutes=grace_minutes,
                            )

                            keyboard = join_requirements_keyboard(
                                i18n, list(missing_channel_objs), str(grant.policy_id)
                            )

                            try:
                                await bot.send_message(user_id, text, reply_markup=keyboard)
                            except Exception as e:
                                logger.warning(
                                    "grace_message_send_failed",
                                    user_id=user_id,
                                    policy_id=str(grant.policy_id),
                                    error=str(e),
                                )

                            logger.info(
                                "user_entered_grace",
                                user_id=user_id,
                                policy_id=str(grant.policy_id),
                                grace_minutes=grace_minutes,
                            )

                        # Preventive cascade: if this channel is protected in OTHER policies,
                        # put those grants into GRACE too (preventive)
                        result = await session.execute(
                            select(PolicyChannel).where(
                                PolicyChannel.telegram_chat_id
                                == grant.policy.protected_chat_id
                            )
                        )
                        preventive_cascade_channels = result.scalars().all()

                        if preventive_cascade_channels:
                            cascade_policy_ids = [
                                pc.policy_id for pc in preventive_cascade_channels
                            ]

                            # Find user's grants in those policies (ACTIVE only)
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
                                    MembershipGrant.user_id == user_id,
                                    MembershipGrant.policy_id.in_(cascade_policy_ids),
                                    MembershipGrant.status == GrantStatus.ACTIVE,
                                )
                            )
                            preventive_grants = result.scalars().all()

                            for prev_grant in preventive_grants:
                                # Don't check compliance - transition to GRACE unconditionally
                                # because the required channel (grant.policy.protected_chat_id)
                                # is under threat (source policy in GRACE)

                                # Find the PolicyChannel object for the threatened channel
                                result = await session.execute(
                                    select(PolicyChannel).where(
                                        PolicyChannel.policy_id == prev_grant.policy_id,
                                        PolicyChannel.telegram_chat_id
                                        == grant.policy.protected_chat_id,
                                    )
                                )
                                threatened_channel = result.scalar_one_or_none()

                                if threatened_channel:
                                    # Transition to GRACE preventively
                                    prev_grant.status = GrantStatus.GRACE
                                    prev_grant.missing_channels = [threatened_channel]
                                    # Don't set grace_expires_at - will be set when source policy is revoked
                                    prev_grant.grace_expires_at = None
                                    prev_grant.last_checked_at = datetime.now(
                                        timezone.utc
                                    )

                                    await audit_service.log_event(
                                        EventType.GRACE_STARTED,
                                        policy_id=prev_grant.policy_id,
                                        user_id=user_id,
                                        details={
                                            "trigger": "preventive_cascade",
                                            "source_policy": str(grant.policy_id),
                                            "threatened_channel": grant.policy.protected_chat_id,
                                        },
                                    )

                                    # Send notification (avoid duplicates)
                                    if user_id not in notified_users:
                                        notified_users.add(user_id)

                                        text = i18n.gettext("grace-message").format(
                                            channel_name=prev_grant.policy.title,
                                            grace_minutes=settings.GRACE_PERIOD_MINUTES,
                                        )
                                        keyboard = join_requirements_keyboard(
                                            i18n,
                                            [threatened_channel],
                                            str(prev_grant.policy_id),
                                        )

                                        try:
                                            await bot.send_message(
                                                user_id, text, reply_markup=keyboard
                                            )
                                        except Exception as e:
                                            logger.warning(
                                                "preventive_cascade_notification_failed",
                                                user_id=user_id,
                                                policy_id=str(prev_grant.policy_id),
                                                error=str(e),
                                            )

                                        logger.info(
                                            "preventive_cascade_grace_started",
                                            user_id=user_id,
                                            policy_id=str(prev_grant.policy_id),
                                            source_policy=str(grant.policy_id),
                                        )

                    elif old_status == GrantStatus.NEEDS_REVIEW:
                        # Update missing channels but keep NEEDS_REVIEW status
                        grant.missing_channels = list(missing_channel_objs)
                        grant.last_checked_at = datetime.now(timezone.utc)

        else:
            # User JOINED a required channel - recheck compliance for all affected grants
            for grant in grants:
                # Invalidate cache for ALL channels in policy before compliance check
                for channel in grant.policy.channels:
                    await membership_service.invalidate_membership_cache(
                        channel.telegram_chat_id, user_id
                    )

                is_compliant, missing_channels = (
                    await membership_service.check_compliance(grant.policy_id, user_id)
                )

                if is_compliant:
                    # Restore to ACTIVE
                    old_status = grant.status
                    grant.status = GrantStatus.ACTIVE
                    grant.missing_channels = []
                    grant.grace_expires_at = None
                    grant.last_checked_at = datetime.now(timezone.utc)

                    await audit_service.log_event(
                        EventType.GRACE_RESOLVED,
                        policy_id=grant.policy_id,
                        user_id=user_id,
                        details={
                            "previous_status": (
                                old_status.value
                                if hasattr(old_status, "value")
                                else old_status
                            )
                        },
                    )

                    # Try to auto-approve pending join request if exists
                    try:
                        await bot.approve_chat_join_request(
                            grant.policy.protected_chat_id, user_id
                        )
                        logger.info(
                            "join_auto_approved_on_membership",
                            user_id=user_id,
                            policy_id=str(grant.policy_id),
                        )
                    except TelegramBadRequest:
                        # No pending request - this is fine
                        pass
                    except Exception as e:
                        logger.warning(
                            "join_auto_approve_failed_on_membership",
                            user_id=user_id,
                            policy_id=str(grant.policy_id),
                            error=str(e),
                        )

                    # Send restoration message only once per user (avoid duplicates)
                    if user_id not in notified_users:
                        notified_users.add(user_id)

                        policy = grant.policy
                        text = i18n.gettext("compliance-restored").format(
                            channel_name=f"<a href='{policy.protected_channel_link}'>{policy.title}</a>"
                        )

                        keyboard = ok_dismiss_keyboard(i18n)

                        try:
                            await bot.send_message(user_id, text, reply_markup=keyboard)
                        except Exception as e:
                            logger.warning(
                                "compliance_restored_message_send_failed",
                                user_id=user_id,
                                policy_id=str(grant.policy_id),
                                error=str(e),
                            )

                        logger.info(
                            "compliance_restored",
                            user_id=user_id,
                            policy_id=str(grant.policy_id),
                            previous_status=(
                                old_status.value
                                if hasattr(old_status, "value")
                                else old_status
                            ),
                        )

            # Cascade restoration: if restored channel is required in OTHER policies,
            # check and restore those grants too
            for grant in grants:
                if grant.status == GrantStatus.ACTIVE:  # Only for just-restored grants
                    # Find policies that require this grant's protected channel
                    result = await session.execute(
                        select(PolicyChannel).where(
                            PolicyChannel.telegram_chat_id == grant.policy.protected_chat_id
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
                                )
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
                            is_compliant, _ = await membership_service.check_compliance(
                                cascade_grant.policy_id, user_id
                            )

                            if is_compliant:
                                # Restore to ACTIVE
                                old_cascade_status = cascade_grant.status
                                cascade_grant.status = GrantStatus.ACTIVE
                                cascade_grant.missing_channels = []
                                cascade_grant.grace_expires_at = None
                                cascade_grant.last_checked_at = datetime.now(timezone.utc)

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
                                        "trigger": "cascade_restoration",
                                        "source_policy": str(grant.policy_id),
                                    },
                                )

                                # Send restoration message (avoid duplicates)
                                if user_id not in notified_users:
                                    notified_users.add(user_id)

                                    cascade_policy = cascade_grant.policy
                                    text = i18n.gettext("compliance-restored").format(
                            channel_name=f"<a href='{policy.protected_channel_link}'>{policy.title}</a>"
                                    )
                                    keyboard = ok_dismiss_keyboard(i18n)

                                    try:
                                        await bot.send_message(
                                            user_id, text, reply_markup=keyboard
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            "cascade_restoration_notification_failed",
                                            user_id=user_id,
                                            policy_id=str(cascade_grant.policy_id),
                                            error=str(e),
                                        )

                                    logger.info(
                                        "cascade_restoration_completed",
                                        user_id=user_id,
                                        policy_id=str(cascade_grant.policy_id),
                                        source_policy=str(grant.policy_id),
                                    )

        # Proactive check: find ALL policies where this channel is required
        # and check if user has grants that can be auto-approved
        if is_member:
            # Find ALL PolicyChannel records for this chat_id
            result = await session.execute(
                select(PolicyChannel).where(
                    PolicyChannel.telegram_chat_id == chat_id,
                )
            )
            all_policy_channels = result.scalars().all()

            if all_policy_channels:
                all_policy_ids = [pc.policy_id for pc in all_policy_channels]

                # Find ALL grants for this user in these policies (any status)
                result = await session.execute(
                    select(MembershipGrant)
                    .options(selectinload(MembershipGrant.policy))
                    .where(
                        MembershipGrant.user_id == user_id,
                        MembershipGrant.policy_id.in_(all_policy_ids),
                        MembershipGrant.status.in_([
                            GrantStatus.NEEDS_REVIEW,
                            GrantStatus.GRACE,
                        ]),
                    )
                )
                all_grants = result.scalars().all()

                for grant in all_grants:
                    # Invalidate cache for ALL channels in this policy
                    policy_result = await session.execute(
                        select(AccessPolicy)
                        .options(selectinload(AccessPolicy.channels))
                        .where(AccessPolicy.id == grant.policy_id)
                    )
                    policy = policy_result.scalar_one_or_none()

                    if policy:
                        for channel in policy.channels:
                            await membership_service.invalidate_membership_cache(
                                channel.telegram_chat_id, user_id
                            )

                        # Check compliance
                        is_compliant, _ = await membership_service.check_compliance(
                            grant.policy_id, user_id
                        )

                        if is_compliant:
                            old_status = grant.status
                            grant.status = GrantStatus.ACTIVE
                            grant.missing_channels = []
                            grant.grace_expires_at = None
                            grant.last_checked_at = datetime.now(timezone.utc)

                            await audit_service.log_event(
                                EventType.GRACE_RESOLVED if old_status == GrantStatus.GRACE else EventType.JOIN_APPROVED,
                                policy_id=grant.policy_id,
                                user_id=user_id,
                                details={
                                    "previous_status": (
                                        old_status.value
                                        if hasattr(old_status, "value")
                                        else old_status
                                    ),
                                    "trigger": "proactive_cross_policy",
                                },
                            )

                            # Try to approve pending join request
                            try:
                                await bot.approve_chat_join_request(
                                    policy.protected_chat_id, user_id
                                )
                                logger.info(
                                    "join_auto_approved_proactive",
                                    user_id=user_id,
                                    policy_id=str(grant.policy_id),
                                    trigger_channel=chat_id,
                                    old_status=(
                                        old_status.value
                                        if hasattr(old_status, "value")
                                        else old_status
                                    ),
                                )
                            except TelegramBadRequest:
                                # No pending request - fine
                                pass
                            except Exception as e:
                                logger.warning(
                                    "join_auto_approve_failed_proactive",
                                    user_id=user_id,
                                    policy_id=str(grant.policy_id),
                                    error=str(e),
                                )

                            # Send restoration message only once per user (avoid duplicates)
                            if user_id not in notified_users:
                                notified_users.add(user_id)

                                text = i18n.gettext("compliance-restored").format(
                            channel_name=f"<a href='{policy.protected_channel_link}'>{policy.title}</a>"
                                )

                                keyboard = ok_dismiss_keyboard(i18n)

                                try:
                                    await bot.send_message(
                                        user_id, text, reply_markup=keyboard
                                    )
                                except Exception as e:
                                    logger.warning(
                                        "compliance_restored_message_send_failed_proactive",
                                        user_id=user_id,
                                        policy_id=str(grant.policy_id),
                                        error=str(e),
                                    )

                                logger.info(
                                    "compliance_restored_proactive",
                                    user_id=user_id,
                                    policy_id=str(grant.policy_id),
                                    trigger_channel=chat_id,
                                    previous_status=(
                                        old_status.value
                                        if hasattr(old_status, "value")
                                        else old_status
                                    ),
                                )

        # Commit all changes
        await session.commit()


@router.message(
    F.chat.type.in_({"group", "supergroup", "channel"}),
    F.content_type.in_(
        [
            ContentType.NEW_CHAT_MEMBERS,
            ContentType.LEFT_CHAT_MEMBER,
        ]
    ),
)
async def delete_join_left_messages(message: Message) -> None:
    """Delete service messages about users joining/leaving in groups.

    Args:
        message: Service message about new/left chat members
    """
    try:
        await message.delete()
        logger.info(
            "service_message_deleted",
            chat_id=message.chat.id,
            message_id=message.message_id,
            content_type=str(message.content_type),
        )
    except Exception as e:
        logger.error(
            "service_message_delete_failed",
            chat_id=message.chat.id,
            message_id=message.message_id,
            content_type=str(message.content_type),
            error=str(e),
        )
