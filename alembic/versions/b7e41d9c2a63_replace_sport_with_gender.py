"""Replace athlete sport with gender (the app is football-only).

Revision ID: b7e41d9c2a63
Revises: 9d2e6a1c5b47
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e41d9c2a63"
down_revision: Union[str, None] = "9d2e6a1c5b47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Los perfiles existentes no tienen género conocido: quedan como OTHER y el
    # deportista puede corregirlo desde la edición de su ficha.
    op.add_column(
        "athlete_profiles",
        sa.Column("gender", sa.String(length=10), nullable=False, server_default="OTHER"),
    )
    op.alter_column("athlete_profiles", "gender", server_default=None)
    op.drop_column("athlete_profiles", "sport")


def downgrade() -> None:
    op.add_column(
        "athlete_profiles",
        sa.Column("sport", sa.String(length=100), nullable=False, server_default="football"),
    )
    op.alter_column("athlete_profiles", "sport", server_default=None)
    op.drop_column("athlete_profiles", "gender")
