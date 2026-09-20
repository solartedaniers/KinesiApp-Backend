from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """Cuenta de acceso a la aplicación (deportista, entrenador o administrador)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Verificación de cuenta por OTP enviado a email
    is_verified: Mapped[bool] = mapped_column(default=False)
    verification_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    verification_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Recuperación de contraseña por OTP enviado a email
    password_reset_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    password_reset_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    athlete_profile: Mapped["AthleteProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
