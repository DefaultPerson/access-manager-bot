"""simplify_models_remove_revisions

Revision ID: 1730b6e9e83c
Revises: e8f901g9e1f3
Create Date: 2025-10-10 07:42:24.970017

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1730b6e9e83c'
down_revision: Union[str, None] = 'e8f901g9e1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create association table for grant missing channels
    op.create_table(
        'grant_missing_channels',
        sa.Column('grant_id', sa.UUID(), nullable=False),
        sa.Column('channel_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['grant_id'], ['membership_grants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['channel_id'], ['policy_channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('grant_id', 'channel_id')
    )

    # membership_grants: drop revision-related columns and missing_channels JSONB
    op.drop_constraint('membership_grants_last_request_id_fkey', 'membership_grants', type_='foreignkey')
    op.drop_constraint('membership_grants_rechecked_by_job_id_fkey', 'membership_grants', type_='foreignkey')
    op.drop_column('membership_grants', 'last_request_id')
    op.drop_column('membership_grants', 'last_revision_seen')
    op.drop_column('membership_grants', 'rechecked_by_job_id')
    op.drop_column('membership_grants', 'missing_channels')

    # policy_channels: drop kind, channel_username, and revision columns
    op.drop_column('policy_channels', 'kind')
    op.drop_column('policy_channels', 'channel_username')
    op.drop_column('policy_channels', 'added_revision')
    op.drop_column('policy_channels', 'removed_revision')

    # access_policies: drop revision column
    op.drop_column('access_policies', 'latest_revision')

    # user_profiles: drop is_admin and metadata columns
    op.drop_column('user_profiles', 'is_admin')
    op.drop_column('user_profiles', 'metadata')

    # Drop tables that are no longer needed (after removing all dependencies)
    op.drop_table('policy_revisions')
    op.drop_table('access_requests')


def downgrade() -> None:
    """Downgrade schema."""
    # Restore user_profiles columns
    op.add_column('user_profiles', sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'))
    op.add_column('user_profiles', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'))

    # Restore access_policies columns
    op.add_column('access_policies', sa.Column('latest_revision', sa.BigInteger(), nullable=False, server_default='0'))

    # Restore policy_channels columns
    op.add_column('policy_channels', sa.Column('removed_revision', sa.BigInteger(), nullable=True))
    op.add_column('policy_channels', sa.Column('added_revision', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('policy_channels', sa.Column('channel_username', sa.String(length=255), nullable=True))
    op.add_column('policy_channels', sa.Column('kind', sa.String(length=20), nullable=False, server_default='REQUIRED'))

    # Restore membership_grants columns
    op.add_column('membership_grants', sa.Column('missing_channels', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('membership_grants', sa.Column('rechecked_by_job_id', sa.UUID(), nullable=True))
    op.add_column('membership_grants', sa.Column('last_revision_seen', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('membership_grants', sa.Column('last_request_id', sa.UUID(), nullable=True))

    # Recreate access_requests table
    op.create_table(
        'access_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('policy_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('revision_number', sa.BigInteger(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approval_message_id', sa.Integer(), nullable=True),
        sa.Column('missing_channels', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('transient_error', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['policy_id'], ['access_policies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user_profiles.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_access_requests_user_id', 'access_requests', ['user_id'])
    op.create_index('ix_access_requests_status', 'access_requests', ['status'])

    # Recreate policy_revisions table
    op.create_table(
        'policy_revisions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('policy_id', sa.UUID(), nullable=False),
        sa.Column('revision_number', sa.BigInteger(), nullable=False),
        sa.Column('change_type', sa.String(length=30), nullable=False),
        sa.Column('channel_id', sa.UUID(), nullable=False),
        sa.Column('initiated_by_admin_id', sa.BigInteger(), nullable=False),
        sa.Column('initiated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('grace_deadline', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scan_cursor_user_id', sa.BigInteger(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['policy_id'], ['access_policies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['channel_id'], ['policy_channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_policy_revisions_revision_number', 'policy_revisions', ['revision_number'])

    # Recreate foreign keys for membership_grants
    op.create_foreign_key('membership_grants_last_request_id_fkey', 'membership_grants', 'access_requests', ['last_request_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('membership_grants_rechecked_by_job_id_fkey', 'membership_grants', 'policy_revisions', ['rechecked_by_job_id'], ['id'], ondelete='SET NULL')

    # Drop association table
    op.drop_table('grant_missing_channels')
