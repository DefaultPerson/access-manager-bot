"""Add preferred_language column to user_profiles

Revision ID: a13b26396ec3
Revises: 001_initial_schema
Create Date: 2025-10-08 10:27:10.494772

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a13b26396ec3'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add preferred_language column
    op.add_column('user_profiles', sa.Column('preferred_language', sa.String(length=10), nullable=True))
    op.create_index(op.f('ix_user_profiles_preferred_language'), 'user_profiles', ['preferred_language'], unique=False)

    # Migrate existing data from metadata JSON to preferred_language column
    op.execute("""
        UPDATE user_profiles
        SET preferred_language = metadata->>'preferred_language'
        WHERE metadata ? 'preferred_language'
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Migrate data back to metadata before dropping column
    op.execute("""
        UPDATE user_profiles
        SET metadata = jsonb_set(metadata, '{preferred_language}', to_jsonb(preferred_language), true)
        WHERE preferred_language IS NOT NULL
    """)

    # Drop column and index
    op.drop_index(op.f('ix_user_profiles_preferred_language'), table_name='user_profiles')
    op.drop_column('user_profiles', 'preferred_language')
