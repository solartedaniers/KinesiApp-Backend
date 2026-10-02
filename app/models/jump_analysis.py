import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class JumpAnalysisStatus(str, enum.Enum):
    """Ciclo de vida de un análisis: la IA lo completa de forma asíncrona."""

    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


class MovementType(str, enum.Enum):
    """Qué gesto se grabó: define cómo se busca la repetición y qué patrones de riesgo aplican."""

    JUMP = "jump"
    SQUAT = "squat"


class JumpAnalysis(Base):
    """Un salto capturado en video, pendiente o ya procesado por el modelo de IA."""

    __tablename__ = "jump_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athlete_profiles.id"), nullable=False)
    video_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType), default=MovementType.JUMP, server_default=MovementType.JUMP.name, nullable=False
    )
    status: Mapped[JumpAnalysisStatus] = mapped_column(
        Enum(JumpAnalysisStatus), default=JumpAnalysisStatus.PENDING, nullable=False
    )
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Patrón que determinó el risk_score; None si ninguno se disparó
    dominant_risk_pattern: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Con qué modelo y qué reglas se calculó, para no reinterpretar resultados viejos
    pose_model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    athlete: Mapped["AthleteProfile"] = relationship(back_populates="jump_analyses")
    angle_measurements: Mapped[list["JointAngleMeasurement"]] = relationship(
        back_populates="jump_analysis", cascade="all, delete-orphan"
    )


class JointAngleMeasurement(Base):
    """Ángulo articular puntual entregado por la IA para un frame del salto."""

    __tablename__ = "joint_angle_measurements"

    id: Mapped[int] = mapped_column(primary_key=True)
    jump_analysis_id: Mapped[int] = mapped_column(ForeignKey("jump_analyses.id"), nullable=False)
    joint_name: Mapped[str] = mapped_column(String(50), nullable=False)
    angle_degrees: Mapped[float] = mapped_column(Float, nullable=False)
    frame_timestamp_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    jump_analysis: Mapped["JumpAnalysis"] = relationship(back_populates="angle_measurements")
