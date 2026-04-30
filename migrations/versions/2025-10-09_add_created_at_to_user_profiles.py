"""add_created_at_to_user_profiles

Revision ID: d8e790f8d0e2
Revises: c7d689e7c9d1
Create Date: 2025-10-09 16:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8e790f8d0e2'
down_revision: Union[str, None] = 'c7d689e7c9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add created_at column with default value same as last_seen_at for existing records
    op.add_column('user_profiles', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')))

    # Remove server default after column creation
    op.alter_column('user_profiles', 'created_at', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_profiles', 'created_at')
