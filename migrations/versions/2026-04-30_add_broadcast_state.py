"""Add broadcast_state column to user_profiles

Revision ID: f4a7c2b18d39
Revises: 1730b6e9e83c
Create Date: 2026-04-30 11:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f4a7c2b18d39'
down_revision: Union[str, None] = '1730b6e9e83c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'user_profiles',
        sa.Column(
            'broadcast_state',
            sa.String(length=20),
            nullable=False,
            server_default='member',
        ),
    )
    op.create_index(
        op.f('ix_user_profiles_broadcast_state'),
        'user_profiles',
        ['broadcast_state'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_user_profiles_broadcast_state'),
        table_name='user_profiles',
    )
    op.drop_column('user_profiles', 'broadcast_state')
