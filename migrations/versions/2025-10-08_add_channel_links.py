"""add_channel_links

Revision ID: c7d689e7c9d1
Revises: b5f568c6b8c0
Create Date: 2025-10-08 14:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d689e7c9d1'
down_revision: Union[str, None] = 'b5f568c6b8c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add protected_channel_link to access_policies
    op.add_column('access_policies', sa.Column('protected_channel_link', sa.String(length=255), nullable=True))

    # Add channel_link to policy_channels
    op.add_column('policy_channels', sa.Column('channel_link', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('access_policies', 'protected_channel_link')
    op.drop_column('policy_channels', 'channel_link')
