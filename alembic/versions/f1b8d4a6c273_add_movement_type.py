"""Add movement_type (jump/squat) to jump_analyses.

Revision ID: f1b8d4a6c273
Revises: e5a2c7b9d318
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1b8d4a6c273"
down_revision: Union[str, None] = "e5a2c7b9d318"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mismo criterio que el resto de enums del proyecto: Postgres guarda el NOMBRE del miembro
movement_type = sa.Enum("JUMP", "SQUAT", name="movementtype")


def upgrade() -> None:
    # El tipo de Postgres se crea explícito antes de la columna (add_column no lo crea solo)
    movement_type.create(op.get_bind(), checkfirst=True)
    # server_default: los análisis que ya existen eran todos saltos
    op.add_column(
        "jump_analyses",
        sa.Column("movement_type", movement_type, nullable=False, server_default="JUMP"),
    )


def downgrade() -> None:
    op.drop_column("jump_analyses", "movement_type")
    movement_type.drop(op.get_bind(), checkfirst=True)
