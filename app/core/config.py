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
        # Tolera variables obsoletas en .env (p. ej. las SMTP_* de antes de Resend)
        extra="ignore",
    )

    PROJECT_NAME: str = "KinesiApp API"
    API_V1_PREFIX: str = "/api/v1"
    CORS_ALLOWED_ORIGINS: list[str] = Field(default_factory=list)
    CORS_ALLOW_ORIGIN_REGEX: str | None = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    # Neon, sin valores por defecto: si faltan, la app falla al arrancar en vez de buscar un
    # Postgres local que ya no existe. Local: endpoint directo; Cloud Run: el "-pooler"
    POSTGRES_USER: str = Field(min_length=1)
    POSTGRES_PASSWORD: SecretStr = Field(min_length=1)
    POSTGRES_HOST: str = Field(min_length=1)
    POSTGRES_PORT: int = Field(default=5432, gt=0, le=65535)
    POSTGRES_DB: str = Field(min_length=1)

    # JWT: access de vida corta para uso normal, refresh de vida larga solo para renovarlo
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    OTP_EXPIRE_MINUTES: int = Field(gt=0)
    OTP_MAX_ATTEMPTS: int = Field(default=5, gt=0)

    # Política de contraseñas nuevas (app/schemas/password_policy.py). El frontend la replica en
    # lib/validation.ts: cambiarla aquí exige cambiarla allí
    PASSWORD_MIN_LENGTH: int = Field(default=8, ge=8)
    PASSWORD_MAX_LENGTH: int = Field(default=128, gt=0)

    # Verificación DNS/MX del dominio del correo en el registro (app/services/email_domain_checker.py)
    EMAIL_DNS_TIMEOUT_SECONDS: int = Field(default=5, gt=0)

    # Correo transaccional con Resend. Sin RESEND_API_KEY el envío falla con un error explícito
    # (503 email_delivery_failed). onboarding@resend.dev sólo entrega al dueño de la cuenta de
    # Resend: para usuarios reales hay que verificar un dominio. Admite "Nombre <correo>"
    RESEND_API_KEY: SecretStr | None = None
    RESEND_FROM_EMAIL: str = Field(default="onboarding@resend.dev", min_length=1)
    RESEND_TIMEOUT_SECONDS: int = Field(default=15, gt=0, le=120)

    MAX_VIDEO_UPLOAD_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)

    # Almacenamiento de objetos compatible con S3 de Neon (app/storage). Mismos nombres que usa
    # boto3. Sin credenciales, subir un video responde 503 storage_unavailable
    AWS_ENDPOINT_URL_S3: str | None = None
    AWS_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: SecretStr | None = None
    # Buckets con lectura pública: la URL del objeto es la que se guarda en la base
    S3_VIDEOS_BUCKET: str = Field(default="videos", min_length=1)
    S3_IMAGES_BUCKET: str = Field(default="images", min_length=1)

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

    # Corte de nivel de riesgo (mismos valores que RISK_THRESHOLDS del frontend): el chat recomienda
    # consulta profesional con nivel "high" (docs/design/video-analysis-pipeline.md §6.3)
    RISK_LEVEL_MODERATE: float = Field(default=0.33, ge=0, le=1)
    RISK_LEVEL_HIGH: float = Field(default=0.66, ge=0, le=1)

    # Chat con Gemini (§6). Sin GEMINI_API_KEY el chat responde 503 assistant_unavailable
    GEMINI_API_KEY: SecretStr | None = None
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    GEMINI_MAX_OUTPUT_TOKENS: int = Field(default=1024, gt=0)
    CHAT_MESSAGE_MAX_CHARS: int = Field(default=1000, gt=0)
    CHAT_HISTORY_MAX_MESSAGES: int = Field(default=10, ge=0)
    CHAT_PROMPT_MAX_REPETITIONS: int = Field(default=5, ge=0)
    CHAT_RATE_LIMIT_PER_USER_PER_HOUR: int = Field(default=20, gt=0)
    # Por debajo del límite de requests por minuto del free tier del modelo (§6.7)
    CHAT_RATE_LIMIT_GLOBAL_PER_MINUTE: int = Field(default=8, gt=0)

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
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )


@lru_cache
def get_settings() -> Settings:
    # Cacheada para no releer/parsear el .env en cada inyección de dependencia
    return Settings()


settings = get_settings()
