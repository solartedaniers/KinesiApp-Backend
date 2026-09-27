"""Allow coach-managed athlete profiles without a user account.

Revision ID: 9d2e6a1c5b47
Revises: 4c9b8e2f7d31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d2e6a1c5b47"
down_revision: Union[str, None] = "4c9b8e2f7d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("athlete_profiles", sa.Column("full_name", sa.String(length=150), nullable=True))
    op.alter_column("athlete_profiles", "user_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "ck_athlete_profiles_owner",
        "athlete_profiles",
        "user_id IS NOT NULL OR (full_name IS NOT NULL AND coach_id IS NOT NULL)",
    )


def downgrade() -> None:
    # Los perfiles gestionados no caben en el esquema anterior (user_id obligatorio):
    # se eliminan junto con sus análisis antes de restaurar la restricción.
    op.execute(
        "DELETE FROM joint_angle_measurements WHERE jump_analysis_id IN ("
        "SELECT ja.id FROM jump_analyses ja JOIN athlete_profiles ap ON ap.id = ja.athlete_id "
        "WHERE ap.user_id IS NULL)"
    )
    op.execute(
        "DELETE FROM jump_analyses WHERE athlete_id IN "
        "(SELECT id FROM athlete_profiles WHERE user_id IS NULL)"
    )
    op.execute("DELETE FROM athlete_profiles WHERE user_id IS NULL")
    op.drop_constraint("ck_athlete_profiles_owner", "athlete_profiles", type_="check")
    op.alter_column("athlete_profiles", "user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("athlete_profiles", "full_name")
