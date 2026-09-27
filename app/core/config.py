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
    # Flexión de rodilla al aterrizar considerada segura. Placeholder de diseño, no un valor
    # clínico validado (ver docs/design/video-analysis-pipeline.md §5)
    RISK_SAFE_KNEE_FLEXION_DEG: float = Field(default=60.0, gt=0)

    # Clave del proceso interno que reporta resultados a POST /jump-analyses/{id}/results.
    # Sin definir, ese endpoint rechaza toda llamada (cerrado por defecto)
    JUMP_ANALYSIS_SERVICE_API_KEY: SecretStr | None = None
    # Versión vigente del texto de consentimiento de video: subir exige haber aceptado ésta
    VIDEO_CONSENT_VERSION: int = Field(default=1, gt=0)

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
