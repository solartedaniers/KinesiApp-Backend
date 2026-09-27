"""Add profile photo (data URL) to users and coach-managed athletes.

Revision ID: c3f8a1d6e924
Revises: b7e41d9c2a63
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f8a1d6e924"
down_revision: Union[str, None] = "b7e41d9c2a63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_data_url", sa.Text(), nullable=True))
    op.add_column("athlete_profiles", sa.Column("avatar_data_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("athlete_profiles", "avatar_data_url")
    op.drop_column("users", "avatar_data_url")
