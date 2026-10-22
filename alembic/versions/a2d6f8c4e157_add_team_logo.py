"""Agrego el logo del equipo (URL canónica en el bucket privado de imágenes).

Revision ID: a2d6f8c4e157
Revises: b4e8f2a6c913
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2d6f8c4e157"
down_revision: Union[str, None] = "b4e8f2a6c913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("logo_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("teams", "logo_url")
