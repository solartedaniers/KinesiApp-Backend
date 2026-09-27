"""Add video consent (timestamp + accepted text version) to users.

Revision ID: e5a2c7b9d318
Revises: c3f8a1d6e924
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5a2c7b9d318"
down_revision: Union[str, None] = "c3f8a1d6e924"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: las cuentas existentes quedan "sin consentimiento" y se les pide al grabar
    op.add_column("users", sa.Column("video_consent_given_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("video_consent_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "video_consent_version")
    op.drop_column("users", "video_consent_given_at")
