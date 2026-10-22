"""Agrego a jump_analyses el progreso persistido y el registro de reintentos.

Revision ID: 6e3d1a9b4f20
Revises: 151f2ecce8b2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6e3d1a9b4f20"
down_revision: Union[str, None] = "151f2ecce8b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

analysis_stage = sa.Enum(
    "QUEUED", "DOWNLOADING_VIDEO", "EXTRACTING_POSE", "DETECTING_REPETITIONS", "SCORING_RISK", name="analysisstage"
)


def upgrade() -> None:
    analysis_stage.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "jump_analyses", sa.Column("stage", analysis_stage, nullable=False, server_default="QUEUED")
    )
    op.add_column("jump_analyses", sa.Column("frames_processed", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jump_analyses", sa.Column("frames_total", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jump_analyses", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "jump_analyses",
        sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("jump_analyses", sa.Column("failure_reason", sa.String(length=50), nullable=True))


def downgrade() -> None:
    for column in ("failure_reason", "progress_updated_at", "attempts", "frames_total", "frames_processed", "stage"):
        op.drop_column("jump_analyses", column)
    analysis_stage.drop(op.get_bind(), checkfirst=True)
