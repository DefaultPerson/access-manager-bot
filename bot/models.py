from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.core.db import Base

# Association table for MembershipGrant missing channels
grant_missing_channels = Table(
    "grant_missing_channels",
    Base.metadata,
    Column(
        "grant_id",
        ForeignKey("membership_grants.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "channel_id",
        ForeignKey("policy_channels.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class GrantStatus(str, Enum):
    """Membership grant status."""

    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    REVOKED = "REVOKED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EventType(str, Enum):
    """Audit event type."""

    JOIN_APPROVED = "JOIN_APPROVED"
    JOIN_DENIED = "JOIN_DENIED"
    MISSING_CHANNELS_SENT = "MISSING_CHANNELS_SENT"
    GRACE_STARTED = "GRACE_STARTED"
    GRACE_RESOLVED = "GRACE_RESOLVED"
    USER_REVOKED = "USER_REVOKED"
    BROADCAST_SENT = "BROADCAST_SENT"
    ERROR = "ERROR"


class BroadcastState(str, Enum):
    """Broadcast subscriber state — mirrors aiogram_broadcast.SubscriberState values."""

    MEMBER = "member"
    KICKED = "kicked"


class UserProfile(Base):
    """User identity for applicants, admins, and broadcast recipients."""

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(
        String(10), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    broadcast_state: Mapped[str] = mapped_column(
        String(20),
        default=BroadcastState.MEMBER.value,
        server_default=BroadcastState.MEMBER.value,
        nullable=False,
        index=True,
    )

    # Relationships
    membership_grants: Mapped[list["MembershipGrant"]] = relationship(
        "MembershipGrant", back_populates="user", foreign_keys="MembershipGrant.user_id"
    )
    audit_logs_as_actor: Mapped[list["AuditLogEntry"]] = relationship(
        "AuditLogEntry",
        back_populates="actor",
        foreign_keys="AuditLogEntry.actor_user_id",
    )

    def __repr__(self) -> str:
        return f"<UserProfile(user_id={self.user_id}, username='{self.username}')>"


class AccessPolicy(Base):
    """Protected channel/group with compliance enforcement settings."""

    __tablename__ = "access_policies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    protected_chat_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    protected_channel_link: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    channels: Mapped[list["PolicyChannel"]] = relationship(
        "PolicyChannel", back_populates="policy", cascade="all, delete-orphan"
    )
    membership_grants: Mapped[list["MembershipGrant"]] = relationship(
        "MembershipGrant", back_populates="policy", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLogEntry"]] = relationship(
        "AuditLogEntry", back_populates="policy", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AccessPolicy(id={self.id}, chat_id={self.protected_chat_id}, title='{self.title}')>"


class PolicyChannel(Base):
    """Channel entry in an access policy with bookkeeping for compliance decisions."""

    __tablename__ = "policy_channels"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("access_policies.id", ondelete="CASCADE"), nullable=False
    )
    telegram_chat_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    channel_link: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    added_by_admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    policy: Mapped["AccessPolicy"] = relationship(
        "AccessPolicy", back_populates="channels"
    )
    missing_from_grants: Mapped[list["MembershipGrant"]] = relationship(
        "MembershipGrant",
        secondary=grant_missing_channels,
        back_populates="missing_channels",
    )

    def __repr__(self) -> str:
        return f"<PolicyChannel(id={self.id}, chat_id={self.telegram_chat_id})>"


class MembershipGrant(Base):
    """User's standing with a policy after at least one approval, enabling re-checks without losing history."""

    __tablename__ = "membership_grants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("access_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[GrantStatus] = mapped_column(String(20), nullable=False, index=True)
    grace_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    policy: Mapped["AccessPolicy"] = relationship(
        "AccessPolicy", back_populates="membership_grants"
    )
    user: Mapped["UserProfile"] = relationship(
        "UserProfile", back_populates="membership_grants"
    )
    missing_channels: Mapped[list["PolicyChannel"]] = relationship(
        "PolicyChannel",
        secondary=grant_missing_channels,
        back_populates="missing_from_grants",
    )

    def __repr__(self) -> str:
        return f"<MembershipGrant(id={self.id}, user_id={self.user_id}, status={self.status.value})>"


class AuditLogEntry(Base):
    """Immutable log of bot decisions, admin actions, and compliance events published to admin topics."""

    __tablename__ = "audit_log_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    policy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_policies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_profiles.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[EventType] = mapped_column(
        String(30), nullable=False, index=True
    )
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    emitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    policy: Mapped["AccessPolicy | None"] = relationship(
        "AccessPolicy", back_populates="audit_logs"
    )
    actor: Mapped["UserProfile | None"] = relationship(
        "UserProfile",
        back_populates="audit_logs_as_actor",
        foreign_keys=[actor_user_id],
    )

    def __repr__(self) -> str:
        return f"<AuditLogEntry(id={self.id}, event={self.event_type.value}, emitted_at={self.emitted_at})>"


__all__ = [
    "UserProfile",
    "AccessPolicy",
    "PolicyChannel",
    "MembershipGrant",
    "GrantStatus",
    "AuditLogEntry",
    "EventType",
    "BroadcastState",
]
