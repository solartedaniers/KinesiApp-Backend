from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AthleteProfile(Base):
    """Datos deportivos de un usuario, usados como contexto para el análisis de lesiones."""

    __tablename__ = "athlete_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    sport: Mapped[str] = mapped_column(String(100), nullable=False)
    height_cm: Mapped[float] = mapped_column(Float, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)

    user: Mapped["User"] = relationship(back_populates="athlete_profile")
    jump_analyses: Mapped[list["JumpAnalysis"]] = relationship(
        back_populates="athlete", cascade="all, delete-orphan"
    )
