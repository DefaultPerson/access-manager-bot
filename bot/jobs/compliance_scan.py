from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.models import AccessPolicy, EventType, GrantStatus, MembershipGrant
from bot.services.audit_service import AuditService
from bot.services.compliance_service import ComplianceService
from bot.services.membership_service import MembershipService

logger = get_logger(__name__)


async def daily_compliance_scan(bot: Bot) -> None:
    """Run daily compliance scan for all active grants.

    Checks all users with ACTIVE status to ensure they still comply with policies.
    This is a safety mechanism to catch any missed events.

    Args:
        bot: Bot instance
    """
    logger.info("daily_compliance_scan_started")

    checked_count = 0
    violations_count = 0
    errors_count = 0

    try:
        async with db_manager.session() as session:
            # Get all active policies
            result = await session.execute(
                select(AccessPolicy).where(AccessPolicy.is_active == True)  # noqa: E712
            )
            active_policies = result.scalars().all()

            membership_service = MembershipService(session, bot)
            compliance_service = ComplianceService(session, bot)
            audit_service = AuditService(session, bot)

            for policy in active_policies:
                # Get all ACTIVE grants for this policy
                result = await session.execute(
                    select(MembershipGrant)
                    .options(selectinload(MembershipGrant.missing_channels))
                    .where(
                        MembershipGrant.policy_id == policy.id,
                        MembershipGrant.status == GrantStatus.ACTIVE,
                    )
                )
                active_grants = result.scalars().all()

                for grant in active_grants:
                    try:
                        # Check compliance
                        is_compliant, missing_channels = (
                            await membership_service.check_compliance(
                                policy.id, grant.user_id
                            )
                        )

                        checked_count += 1

                        if not is_compliant:
                            # Start grace period
                            violations_count += 1

                            await compliance_service.start_grace_period(
                                grant_id=grant.id,
                                missing_channels=missing_channels,
                            )

                            await audit_service.log_event(
                                EventType.GRACE_STARTED,
                                policy_id=policy.id,
                                user_id=grant.user_id,
                                details={
                                    "missing_channels_count": len(missing_channels),
                                    "detected_by": "daily_scan",
                                },
                            )

                            logger.warning(
                                "compliance_violation_detected",
                                policy_id=str(policy.id),
                                user_id=grant.user_id,
                                missing_count=len(missing_channels),
                            )
                        else:
                            # Update last checked timestamp
                            grant.last_checked_at = datetime.now(timezone.utc)

                    except Exception as e:
                        errors_count += 1
                        logger.error(
                            "compliance_check_error",
                            policy_id=str(policy.id),
                            user_id=grant.user_id,
                            error=str(e),
                        )

            # Scan summary is logged via logger.info below
            await session.commit()

    except Exception as e:
        logger.error("daily_compliance_scan_failed", error=str(e))

    logger.info(
        "daily_compliance_scan_completed",
        checked=checked_count,
        violations=violations_count,
        errors=errors_count,
    )
