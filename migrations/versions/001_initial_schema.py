"""initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-10-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create user_profiles table
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # Create access_policies table
    op.create_table(
        "access_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("protected_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("latest_revision", sa.BigInteger(), nullable=False),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_access_policies_protected_chat_id"), "access_policies", ["protected_chat_id"], unique=True
    )

    # Create policy_channels table
    op.create_table(
        "policy_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("added_revision", sa.BigInteger(), nullable=False),
        sa.Column("removed_revision", sa.BigInteger(), nullable=True),
        sa.Column("added_by_admin_id", sa.BigInteger(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["access_policies.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_policy_channels_telegram_chat_id"), "policy_channels", ["telegram_chat_id"], unique=False)

    # Create access_requests table
    op.create_table(
        "access_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_message_id", sa.Integer(), nullable=True),
        sa.Column("missing_channels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("transient_error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["access_policies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.user_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_access_requests_user_id"), "access_requests", ["user_id"], unique=False)
    op.create_index(op.f("ix_access_requests_status"), "access_requests", ["status"], unique=False)

    # Create policy_revisions table
    op.create_table(
        "policy_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initiated_by_admin_id", sa.BigInteger(), nullable=False),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grace_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_cursor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["access_policies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["policy_channels.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_policy_revisions_revision_number"), "policy_revisions", ["revision_number"], unique=False
    )

    # Create membership_grants table
    op.create_table(
        "membership_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_revision_seen", sa.BigInteger(), nullable=False),
        sa.Column("grace_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missing_channels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rechecked_by_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["access_policies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.user_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_request_id"],
            ["access_requests.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rechecked_by_job_id"],
            ["policy_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_membership_grants_policy_id"), "membership_grants", ["policy_id"], unique=False)
    op.create_index(op.f("ix_membership_grants_user_id"), "membership_grants", ["user_id"], unique=False)
    op.create_index(op.f("ix_membership_grants_status"), "membership_grants", ["status"], unique=False)
    # Composite index for policy + user lookups
    op.create_index("ix_membership_grants_policy_user", "membership_grants", ["policy_id", "user_id"], unique=False)

    # Create audit_log_entries table
    op.create_table(
        "audit_log_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("emitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["access_policies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user_profiles.user_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_entries_policy_id"), "audit_log_entries", ["policy_id"], unique=False)
    op.create_index(op.f("ix_audit_log_entries_actor_user_id"), "audit_log_entries", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_audit_log_entries_event_type"), "audit_log_entries", ["event_type"], unique=False)
    op.create_index(op.f("ix_audit_log_entries_emitted_at"), "audit_log_entries", ["emitted_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("audit_log_entries")
    op.drop_table("membership_grants")
    op.drop_table("policy_revisions")
    op.drop_table("access_requests")
    op.drop_table("policy_channels")
    op.drop_table("access_policies")
    op.drop_table("user_profiles")
