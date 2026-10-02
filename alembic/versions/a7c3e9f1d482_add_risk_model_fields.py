"""Add dominant risk pattern and model versions to jump_analyses.

Revision ID: a7c3e9f1d482
Revises: f1b8d4a6c273
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e9f1d482"
down_revision: Union[str, None] = "f1b8d4a6c273"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jump_analyses", sa.Column("dominant_risk_pattern", sa.String(length=50), nullable=True))
    op.add_column("jump_analyses", sa.Column("pose_model_version", sa.String(length=100), nullable=True))
    op.add_column("jump_analyses", sa.Column("risk_model_version", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("jump_analyses", "risk_model_version")
    op.drop_column("jump_analyses", "pose_model_version")
    op.drop_column("jump_analyses", "dominant_risk_pattern")
