import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(str, enum.Enum):
    """Los 3 perfiles de acceso de KinesiApp; controla qué puede ver/hacer cada usuario."""

    ATHLETE = "athlete"
    COACH = "coach"
    ADMIN = "admin"


class User(Base):
    """Cuenta de acceso a la aplicación (deportista, entrenador o administrador)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    # El registro público elige ATHLETE o COACH; ADMIN solo lo asigna otro admin
    # vía PATCH /users/{id}/role
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.ATHLETE, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Foto de perfil como data URL (ver app/schemas/avatar.py)
    avatar_data_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Verificación de cuenta por OTP enviado a email
    is_verified: Mapped[bool] = mapped_column(default=False)
    verification_code_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_code_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    verification_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Consentimiento para grabar/subir video de saltos (docs/design/video-analysis-pipeline.md §8.4)
    video_consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    video_consent_version: Mapped[int | None] = mapped_column(nullable=True)

    # Recuperación de contraseña por OTP enviado a email
    password_reset_code_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_reset_code_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    password_reset_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # AthleteProfile tiene 2 FKs hacia users (user_id y coach_id): hay que fijar
    # foreign_keys explícitamente en ambas relaciones para que SQLAlchemy no las confunda
    athlete_profile: Mapped["AthleteProfile | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="AthleteProfile.user_id",
    )
    coached_athletes: Mapped[list["AthleteProfile"]] = relationship(
        back_populates="coach", foreign_keys="AthleteProfile.coach_id"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
