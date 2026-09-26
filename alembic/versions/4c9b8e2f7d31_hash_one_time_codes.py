"""Store only hashed OTPs and limit verification attempts.

Revision ID: 4c9b8e2f7d31
Revises: 83fa42007776
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c9b8e2f7d31"
down_revision: Union[str, None] = "83fa42007776"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("verification_code_hash", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "users", sa.Column("password_reset_code_hash", sa.String(length=128), nullable=True)
    )
    op.add_column("users", sa.Column("verification_code_attempts", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("password_reset_code_attempts", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE users SET verification_code_attempts = 0, "
            "password_reset_code_attempts = 0"
        )
    )
    op.alter_column("users", "verification_code_attempts", nullable=False)
    op.alter_column("users", "password_reset_code_attempts", nullable=False)

    # Los códigos vigentes en el esquema anterior eran texto plano. Se invalidan
    # al migrar; el cliente puede solicitar otro con /auth/verification-code/request.
    op.drop_column("users", "verification_code")
    op.drop_column("users", "password_reset_code")


def downgrade() -> None:
    # Los hashes no se pueden revertir a códigos originales; las columnas nuevas
    # quedan vacías y el sistema previo podrá emitir códigos nuevos.
    op.add_column("users", sa.Column("verification_code", sa.String(length=6), nullable=True))
    op.add_column("users", sa.Column("password_reset_code", sa.String(length=6), nullable=True))
    op.drop_column("users", "verification_code_attempts")
    op.drop_column("users", "password_reset_code_attempts")
    op.drop_column("users", "verification_code_hash")
    op.drop_column("users", "password_reset_code_hash")
