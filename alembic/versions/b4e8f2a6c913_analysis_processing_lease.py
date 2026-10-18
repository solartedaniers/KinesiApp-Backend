"""Add the processing lease and attempt id to jump_analyses.

Revision ID: b4e8f2a6c913
Revises: 9a7c3e5d1b42
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b4e8f2a6c913"
down_revision: Union[str, None] = "9a7c3e5d1b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Las dejo nulas: los análisis que ya existen no tienen dueño y la recuperación los trata como sin reclamar
    op.add_column("jump_analyses", sa.Column("processing_attempt_id", sa.String(length=32), nullable=True))
    op.add_column("jump_analyses", sa.Column("processing_lease_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("jump_analyses", "processing_lease_until")
    op.drop_column("jump_analyses", "processing_attempt_id")
