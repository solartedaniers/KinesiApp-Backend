"""Add teams and team_members (groups of athletes owned by a coach or an admin).

Revision ID: d28e52f6d0b7
Revises: 3b8fa7cd75a7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d28e52f6d0b7"
down_revision: Union[str, None] = "3b8fa7cd75a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_teams_owner_id_name"),
    )
    op.create_index("ix_teams_owner_id", "teams", ["owner_id"])
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["athlete_id"], ["athlete_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("team_id", "athlete_id"),
    )


def downgrade() -> None:
    op.drop_table("team_members")
    op.drop_index("ix_teams_owner_id", table_name="teams")
    op.drop_table("teams")
