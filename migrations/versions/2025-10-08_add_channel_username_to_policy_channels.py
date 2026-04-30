"""add_channel_username_to_policy_channels

Revision ID: b5f568c6b8c0
Revises: a13b26396ec3
Create Date: 2025-10-08 12:17:25.244576

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b5f568c6b8c0'
down_revision: Union[str, None] = 'a13b26396ec3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('policy_channels', sa.Column('channel_username', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('policy_channels', 'channel_username')
