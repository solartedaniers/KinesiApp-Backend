from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Configuración de la aplicación, cargada desde variables de entorno (.env)."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        # Tolera variables obsoletas en .env (p. ej. el antiguo SMTP_FROM)
        extra="ignore",
    )

    PROJECT_NAME: str = "KinesiApp API"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)
    CORS_ALLOW_ORIGIN_REGEX: str | None = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    POSTGRES_USER: str = "kinesiapp"
    POSTGRES_PASSWORD: str = "kinesiapp"
    POSTGRES_HOST: str = "localhost"
    # En desarrollo local de Windows, docker-compose publica PostgreSQL aquí.
    # El servicio API de Docker sobrescribe el puerto a 5432.
    POSTGRES_PORT: int = 5434
    POSTGRES_DB: str = "kinesiapp"

    # JWT: access de vida corta para uso normal, refresh de vida larga solo para renovarlo
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    OTP_EXPIRE_MINUTES: int = Field(gt=0)
    OTP_MAX_ATTEMPTS: int = Field(default=5, gt=0)

    # Gmail usa smtp.gmail.com:587 con STARTTLS y contraseña de aplicación.
    SMTP_HOST: str = Field(min_length=1)
    SMTP_PORT: int = Field(gt=0, le=65535)
    SMTP_USER: str = Field(min_length=1)
    SMTP_PASSWORD: SecretStr = Field(min_length=1)
    # Solo el nombre visible: la dirección remitente siempre es SMTP_USER (requisito de Gmail).
    SMTP_FROM_NAME: str = "KinesiApp"
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = Field(default=15, gt=0, le=120)

    # Videos de salto: se guardan en disco (backend/media/jump_videos) hasta que se procesan
    VIDEO_UPLOAD_DIR: Path = Path(__file__).resolve().parents[2] / "media" / "jump_videos"
    MAX_VIDEO_UPLOAD_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)

    # Análisis de pose (docs/design/video-analysis-pipeline.md §5). La versión se guarda en cada
    # análisis: cambiar de modelo exige cambiarla también
    POSE_MODEL_PATH: Path = Path(__file__).resolve().parents[2] / "models" / "pose_landmarker_full.task"
    POSE_MODEL_VERSION: str = "mediapipe-pose_landmarker_full-float16-v1"
    POSE_MIN_DETECTION_CONFIDENCE: float = Field(default=0.5, ge=0, le=1)
    LANDMARK_VISIBILITY_THRESHOLD: float = Field(default=0.1, ge=0, le=1)
    LANDMARK_SMOOTHING_WINDOW_FRAMES: int = Field(default=3, ge=1)

    # Detección de fases. Calibradas con un solo par de videos por ejercicio (§12): no definitivas
    JUMP_HIP_APEX_PROMINENCE: float = Field(default=0.08, gt=0)
    JUMP_HIP_APEX_MIN_DISTANCE_SECONDS: float = Field(default=0.6, gt=0)
    JUMP_APEX_AIRBORNE_BODY_FRACTION: float = Field(default=0.06, gt=0)
    JUMP_AIRBORNE_BODY_FRACTION: float = Field(default=0.03, gt=0)
    JUMP_GROUND_WINDOW_SECONDS: float = Field(default=1.0, gt=0)
    JUMP_GROUND_PERCENTILE: float = Field(default=90.0, ge=0, le=100)
    JUMP_LANDING_WINDOW_MS: int = Field(default=300, gt=0)
    JUMP_LANDING_END_MARGIN_FRAMES: int = Field(default=3, ge=0)
    SQUAT_BOTTOM_MIN_PROMINENCE_DEG: float = Field(default=25.0, gt=0)
    SQUAT_BOTTOM_MIN_FLEXION_DEG: float = Field(default=50.0, ge=0)
    SQUAT_BOTTOM_MIN_DISTANCE_SECONDS: float = Field(default=0.6, gt=0)
    SQUAT_BOTTOM_WINDOW_MS: int = Field(default=200, ge=0)
    # Respaldo cuando la rodilla no deja picos (bisagra de cadera con piernas casi rectas): el
    # umbral de tronco es RISK_SQUAT_TRUNK_LEAN_ONSET_DEG, el mismo donde empieza el riesgo
    SQUAT_HINGE_MIN_DURATION_SECONDS: float = Field(default=0.3, gt=0)

    # Umbrales de riesgo: placeholders de orden de magnitud tomados del spike, SIN validación
    # clínica (§5, §5.6). Cada parcial es una rampa de "onset" (0) a "saturation" (1)
    RISK_MODEL_VERSION: str = "risk-patterns-v1"
    RISK_JUMP_KNEE_RIGID_ONSET_DEG: float = 60.0
    RISK_JUMP_KNEE_RIGID_SATURATION_DEG: float = 30.0
    RISK_JUMP_KNEE_DEEP_ONSET_DEG: float = 80.0
    RISK_JUMP_KNEE_DEEP_SATURATION_DEG: float = 100.0
    RISK_JUMP_TRUNK_LEAN_ONSET_DEG: float = 25.0
    RISK_JUMP_TRUNK_LEAN_SATURATION_DEG: float = 45.0
    RISK_JUMP_PATTERNS: dict[str, list[str]] = {
        "rigid_landing": ["knee_rigid"],
        "forward_collapse": ["knee_deep", "trunk_lean"],
        "trunk_lean": ["trunk_lean"],
    }
    # Sentadilla: el riesgo es inclinar el tronco EN LUGAR de flexionar la rodilla (rampa de
    # rodilla descendente: menos flexión, más riesgo)
    RISK_SQUAT_KNEE_SHALLOW_ONSET_DEG: float = 90.0
    RISK_SQUAT_KNEE_SHALLOW_SATURATION_DEG: float = 80.0
    RISK_SQUAT_TRUNK_LEAN_ONSET_DEG: float = 70.0
    RISK_SQUAT_TRUNK_LEAN_SATURATION_DEG: float = 90.0
    RISK_SQUAT_PATTERNS: dict[str, list[str]] = {
        "hip_hinge_squat": ["squat_trunk_lean", "squat_knee_shallow"],
    }

    # Clave del proceso interno que reporta resultados a POST /jump-analyses/{id}/results.
    # Sin definir, ese endpoint rechaza toda llamada (cerrado por defecto)
    JUMP_ANALYSIS_SERVICE_API_KEY: SecretStr | None = None
    # Versión vigente del texto de consentimiento de video: subir exige haber aceptado ésta
    VIDEO_CONSENT_VERSION: int = Field(default=1, gt=0)
    # Vida del token que autoriza reproducir un video (va en la URL: los reproductores
    # no pueden mandar el header Authorization), por eso corta
    VIDEO_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=10, gt=0)

    @property
    def database_url(self) -> URL:
        # URL.create escapa correctamente credenciales con @, :, / o %.
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )


@lru_cache
def get_settings() -> Settings:
    # Cacheada para no releer/parsear el .env en cada inyección de dependencia
    return Settings()


settings = get_settings()
