"""Join request handler for chat_join_request events."""

from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.types import ChatJoinRequest
from aiogram.utils.i18n.core import I18n
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.keyboards.inline.channels import join_requirements_keyboard, ok_dismiss_keyboard
from bot.models import AccessPolicy, EventType, GrantStatus, MembershipGrant
from bot.services.audit_service import AuditService
from bot.services.membership_service import MembershipService
from bot.services.user_service import UserService

logger = get_logger(__name__)

router = Router()


@router.chat_join_request(F.chat.type.in_({"group", "supergroup", "channel"}))
async def join_request_handler(
    join_request: ChatJoinRequest, bot: Bot, i18n: I18n
) -> None:
    """Handle incoming join requests to protected channels.

    Args:
        join_request: Join request event
        bot: Bot instance
        i18n: I18n instance
    """
    user = join_request.from_user
    chat_id = join_request.chat.id

    async with db_manager.session() as session:
        # Get policy for this chat
        result = await session.execute(
            select(AccessPolicy).where(
                AccessPolicy.protected_chat_id == chat_id,
                AccessPolicy.is_active == True,  # noqa: E712
            )
        )
        policy = result.scalar_one_or_none()

        if not policy:
            # No policy configured - approve by default
            try:
                await bot.approve_chat_join_request(chat_id, user.id)
                logger.info("join_approved_no_policy", user_id=user.id, chat_id=chat_id)
            except Exception as e:
                logger.error(
                    "join_approval_failed",
                    user_id=user.id,
                    chat_id=chat_id,
                    error=str(e),
                )
            return

        # Upsert user profile
        user_service = UserService(session)
        await user_service.upsert_profile(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )

        membership_service = MembershipService(session, bot)
        audit_service = AuditService(session, bot)

        # Check compliance
        is_compliant, missing_channels = await membership_service.check_compliance(
            policy.id, user.id
        )

        # Get existing grant if any
        result = await session.execute(
            select(MembershipGrant)
            .options(selectinload(MembershipGrant.missing_channels))
            .where(
                MembershipGrant.policy_id == policy.id,
                MembershipGrant.user_id == user.id,
            )
        )
        grant = result.scalar_one_or_none()

        if is_compliant:
            # User is compliant - approve immediately
            success, error = await membership_service.approve_with_retry(
                chat_id, user.id
            )

            if success:
                # Update or create grant
                if grant:
                    grant.status = GrantStatus.ACTIVE
                    grant.missing_channels = []
                    grant.grace_expires_at = None
                    grant.last_checked_at = datetime.now(timezone.utc)
                else:
                    grant = MembershipGrant(
                        policy_id=policy.id,
                        user_id=user.id,
                        status=GrantStatus.ACTIVE,
                    )
                    session.add(grant)

                await audit_service.log_event(
                    EventType.JOIN_APPROVED,
                    policy_id=policy.id,
                    user_id=user.id,
                    details={},
                )

                text = i18n.gettext("join-approved").format(channel_name=f"<a href='{policy.protected_channel_link}'>{policy.title}</a>")
                keyboard = ok_dismiss_keyboard(i18n)
                await bot.send_message(user.id, text, reply_markup=keyboard)

                logger.info(
                    "join_request_approved", user_id=user.id, policy_id=str(policy.id)
                )
            else:
                # Approval failed
                await audit_service.log_event(
                    EventType.ERROR,
                    policy_id=policy.id,
                    user_id=user.id,
                    details={"error": "approval_failed", "error_details": error},
                )
                logger.error(
                    "join_approval_failed",
                    user_id=user.id,
                    policy_id=str(policy.id),
                    error=error,
                )

        else:
            # User is not compliant
            # Load PolicyChannel objects from missing channel IDs
            missing_channel_objs = (
                await membership_service.load_missing_channel_objects(missing_channels)
            )

            text = i18n.gettext("missing-channels-message").format(
                channel_name=policy.title
            )

            # Update or create grant as NEEDS_REVIEW
            if grant:
                grant.status = GrantStatus.NEEDS_REVIEW
                grant.missing_channels = list(missing_channel_objs)
                grant.last_checked_at = datetime.now(timezone.utc)
            else:
                grant = MembershipGrant(
                    policy_id=policy.id,
                    user_id=user.id,
                    status=GrantStatus.NEEDS_REVIEW,
                )
                grant.missing_channels = list(missing_channel_objs)
                session.add(grant)

            await audit_service.log_event(
                EventType.MISSING_CHANNELS_SENT,
                policy_id=policy.id,
                user_id=user.id,
                details={"missing_channels_count": len(missing_channels)},
            )

            # Don't decline join request - keep it pending until user meets requirements
            # Join request will be approved automatically when user clicks "Check" and passes compliance

            keyboard = join_requirements_keyboard(
                i18n, missing_channel_objs, str(policy.id)
            )
            await bot.send_message(user.id, text, reply_markup=keyboard)

            logger.info(
                "join_request_needs_review",
                user_id=user.id,
                policy_id=str(policy.id),
                missing_count=len(missing_channels),
            )

        # Commit all changes
        await session.commit()
