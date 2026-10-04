from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Muchos a muchos: un deportista puede estar en varios grupos (p. ej. "Sub-17" y "Delanteros")
team_members = Table(
    "team_members",
    Base.metadata,
    Column("team_id", ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True),
    Column("athlete_id", ForeignKey("athlete_profiles.id", ondelete="CASCADE"), primary_key=True),
)


class Team(Base):
    """Grupo de deportistas que arma un entrenador (o un admin) para organizarlos y filtrar estadísticas."""

    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_teams_owner_id_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Quien lo creó: un COACH (sólo agrupa a sus deportistas) o un ADMIN (a cualquiera)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, nullable=False)

    owner: Mapped["User"] = relationship()
    athletes: Mapped[list["AthleteProfile"]] = relationship(secondary=team_members, back_populates="teams")

    @property
    def athlete_ids(self) -> list[int]:
        return sorted(athlete.id for athlete in self.athletes)
