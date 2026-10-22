"""Hago única jump_analyses.video_reference.

Revision ID: 9a7c3e5d1b42
Revises: 6e3d1a9b4f20
"""
from typing import Sequence, Union

from alembic import op


revision: str = "9a7c3e5d1b42"
down_revision: Union[str, None] = "6e3d1a9b4f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cada video da un solo análisis: si confirman dos veces la misma subida a la vez, la segunda choca aquí
    op.create_unique_constraint("uq_jump_analyses_video_reference", "jump_analyses", ["video_reference"])


def downgrade() -> None:
    op.drop_constraint("uq_jump_analyses_video_reference", "jump_analyses", type_="unique")
