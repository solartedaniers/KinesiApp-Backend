"""Add risk_details (per-pattern, per-signal, per-repetition breakdown) to jump_analyses.

Revision ID: d4b9f2a7c615
Revises: a7c3e9f1d482
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4b9f2a7c615"
down_revision: Union[str, None] = "a7c3e9f1d482"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sin backfill: los análisis anteriores no guardaron landmarks ni ventanas, no se puede recalcular
    op.add_column("jump_analyses", sa.Column("risk_details", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jump_analyses", "risk_details")
