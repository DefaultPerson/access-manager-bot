"""make_channel_link_required

Revision ID: e8f901g9e1f3
Revises: d8e790f8d0e2
Create Date: 2025-10-09 17:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8f901g9e1f3"
down_revision: Union[str, None] = "d8e790f8d0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make channel_link fields non-nullable."""
    # Set placeholder for existing NULL values in protected_channel_link
    op.execute(
        """
        UPDATE access_policies
        SET protected_channel_link = 'https://t.me/placeholder'
        WHERE protected_channel_link IS NULL
        """
    )

    # Set placeholder for existing NULL values in policy_channels.channel_link
    op.execute(
        """
        UPDATE policy_channels
        SET channel_link = 'https://t.me/placeholder'
        WHERE channel_link IS NULL
        """
    )

    # Make protected_channel_link non-nullable
    op.alter_column(
        "access_policies",
        "protected_channel_link",
        existing_type=sa.String(255),
        nullable=False,
    )

    # Make channel_link non-nullable
    op.alter_column(
        "policy_channels",
        "channel_link",
        existing_type=sa.String(500),
        nullable=False,
    )


def downgrade() -> None:
    """Revert channel_link fields to nullable."""
    op.alter_column(
        "access_policies",
        "protected_channel_link",
        existing_type=sa.String(255),
        nullable=True,
    )

    op.alter_column(
        "policy_channels",
        "channel_link",
        existing_type=sa.String(500),
        nullable=True,
    )
