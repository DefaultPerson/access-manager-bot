from uuid import UUID

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.logger import get_logger, send_to_telegram
from bot.models import AuditLogEntry, EventType

logger = get_logger(__name__)


class AuditService:
    """Service for logging bot events and admin actions to DB and Telegram."""

    def __init__(self, session: AsyncSession, bot: Bot):
        """Initialize audit service.

        Args:
            session: Database session
            bot: Telegram bot instance
        """
        self.session = session
        self.bot = bot

    async def log_event(
        self,
        event_type: EventType,
        policy_id: UUID | None = None,
        user_id: int | None = None,
        details: dict | None = None,
    ) -> AuditLogEntry:
        """Log event to database and optionally Telegram.

        Args:
            event_type: Type of event
            policy_id: Optional policy UUID
            user_id: Optional user ID (actor)
            details: Optional event details dict

        Returns:
            Created AuditLogEntry
        """
        entry = AuditLogEntry(
            event_type=event_type,
            policy_id=policy_id,
            actor_user_id=user_id,
            details=details or {},
        )
        self.session.add(entry)
        await self.session.flush()

        logger.info(
            "audit_event_logged",
            event_type=event_type.value,
            policy_id=str(policy_id) if policy_id else None,
            user_id=user_id,
        )

        # Send critical events to Telegram admin topic
        if event_type in self._critical_events():
            # Reload entry with actor relationship for Telegram formatting
            await self.session.refresh(entry, ["actor"])
            await self.send_to_admin_topic(self.format_log_for_telegram(entry))

        return entry

    async def send_to_admin_topic(self, message: str) -> None:
        """Send message to admin topic in Telegram.

        Args:
            message: Formatted message text
        """
        try:
            await send_to_telegram(self.bot, message, level="INFO")
        except Exception as e:
            logger.error("admin_topic_send_failed", error=str(e))

    def format_log_for_telegram(self, entry: AuditLogEntry) -> str:
        """Format audit log entry for Telegram message.

        Args:
            entry: AuditLogEntry instance

        Returns:
            Formatted message string
        """
        emoji_map = {
            EventType.JOIN_APPROVED: "✅",
            EventType.JOIN_DENIED: "❌",
            EventType.MISSING_CHANNELS_SENT: "📋",
            EventType.GRACE_STARTED: "⏳",
            EventType.GRACE_RESOLVED: "✅",
            EventType.USER_REVOKED: "🚫",
            EventType.BROADCAST_SENT: "📢",
            EventType.ERROR: "⚠️",
        }
        emoji = emoji_map.get(entry.event_type, "📝")

        parts = [f"{emoji} <b>{entry.event_type.value}</b>"]

        if entry.actor_user_id:
            user_info = f"User ID: {entry.actor_user_id}"
            # Add username if available via relationship
            if entry.actor and entry.actor.username:
                user_info += f" (@{entry.actor.username})"
            parts.append(user_info)

        if entry.policy_id:
            parts.append(f"Policy: {str(entry.policy_id)[:8]}...")

        if entry.details:
            # Extract key details
            if "missing_channels_count" in entry.details:
                parts.append(
                    f"Missing: {entry.details['missing_channels_count']} channels"
                )
            if "grace_deadline" in entry.details:
                parts.append(f"Grace until: {entry.details['grace_deadline']}")
            if "error" in entry.details:
                parts.append(f"Error: {entry.details['error']}")

        parts.append(f"Time: {entry.emitted_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        return "\n".join(parts)

    def _critical_events(self) -> set[EventType]:
        """Events that should be sent to Telegram admin topic.

        Returns:
            Set of critical event types
        """
        return {
            EventType.USER_REVOKED,
            EventType.ERROR,
            EventType.BROADCAST_SENT,
        }
