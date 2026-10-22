import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class JumpAnalysisStatus(str, enum.Enum):
    """Ciclo de vida de un análisis: la IA lo completa de forma asíncrona."""

    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


class AnalysisStage(str, enum.Enum):
    """Etapa en curso de un análisis PENDING; mismos valores que kinesiapp.common.v1.AnalysisStage."""

    QUEUED = "queued"
    DOWNLOADING_VIDEO = "downloading_video"
    EXTRACTING_POSE = "extracting_pose"
    DETECTING_REPETITIONS = "detecting_repetitions"
    SCORING_RISK = "scoring_risk"


class MovementType(str, enum.Enum):
    """Qué gesto se grabó: define cómo se busca la repetición y qué patrones de riesgo aplican."""

    JUMP = "jump"
    SQUAT = "squat"


class JumpAnalysis(Base):
    """Un salto capturado en video, pendiente o ya procesado por el modelo de IA."""

    __tablename__ = "jump_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athlete_profiles.id"), nullable=False)
    video_reference: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType), default=MovementType.JUMP, server_default=MovementType.JUMP.name, nullable=False
    )
    status: Mapped[JumpAnalysisStatus] = mapped_column(
        Enum(JumpAnalysisStatus), default=JumpAnalysisStatus.PENDING, nullable=False
    )
    # Progreso persistido: quien se conecta tarde o tras un reinicio lee esto antes del stream en vivo
    stage: Mapped[AnalysisStage] = mapped_column(
        Enum(AnalysisStage), default=AnalysisStage.QUEUED, server_default=AnalysisStage.QUEUED.name, nullable=False
    )
    frames_processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # 0 mientras no se conoce
    frames_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Con progress_updated_at, el arranque detecta análisis atascados y decide si reintentarlos
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    progress_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Quién procesa el análisis y hasta cuándo: otra instancia solo lo reclama con el lease vencido, y un
    # intento que ya no es el dueño no puede escribir
    processing_attempt_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    processing_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Nombre del ErrorReason del contrato (p. ej. "VIDEO_UNREADABLE") cuando status es FAILED
    failure_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Patrón que determinó el risk_score; None si ninguno se disparó
    dominant_risk_pattern: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Desglose por patrón, señal y repetición (kinesiapp_ai.analysis.risk_details). NULL en los análisis
    # procesados antes de que existiera: el chat los atiende en modo reducido
    risk_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
