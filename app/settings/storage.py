from pydantic import Field, SecretStr

from app.settings.base import EnvSettings


class StorageSettings(EnvSettings):
    """Configuro el almacenamiento S3 de Neon con los mismos nombres que usa boto3.

    Sin credenciales, subir un archivo responde storage_unavailable.
    """

    AWS_ENDPOINT_URL_S3: str | None = None
    AWS_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: SecretStr | None = None
    S3_VIDEOS_BUCKET: str = Field(default="videos", min_length=1)
    S3_IMAGES_BUCKET: str = Field(default="images", min_length=1)
    # Buckets privados del servidor gRPC, sin default a propósito: los públicos de arriba son de producción
    # y sin estos el servidor responde storage_unavailable en vez de escribir en ellos
    S3_PRIVATE_IMAGES_BUCKET: str | None = None
    S3_PRIVATE_VIDEOS_BUCKET: str | None = None


class MediaSettings(EnvSettings):
    """Fijo los límites y permisos de los videos y avatares que suben las personas."""

    MAX_VIDEO_UPLOAD_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)
    # Lo expongo para que el cliente lo valide leyendo los metadatos del video antes de subirlo
    MAX_VIDEO_DURATION_SECONDS: int = Field(default=40, gt=0)
    # Me alcanza con este tope porque el cliente la redimensiona y comprime en un Web Worker
    MAX_AVATAR_UPLOAD_BYTES: int = Field(default=1_000_000, gt=0)
    # Para subir exijo haber aceptado esta versión vigente del texto de consentimiento de video
    VIDEO_CONSENT_VERSION: int = Field(default=1, gt=0)
    # Le doy una vida corta al token que autoriza reproducir un video porque va en la URL: los
    # reproductores no mandan el header Authorization
    VIDEO_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=10, gt=0)
    # Valido el token de subida directa a la API al terminar de llegar el cuerpo, así que debe durar más
    # que la subida más lenta
    VIDEO_UPLOAD_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    # Hago durar la URL firmada de subida al bucket lo suficiente para cubrir la subida más lenta
    SIGNED_UPLOAD_URL_EXPIRE_SECONDS: int = Field(default=900, gt=0, le=7 * 24 * 3600)
    # Hago durar el upload_id más que la URL porque la subida empieza antes de que la URL venza pero
    # puede terminar después
    UPLOAD_TICKET_EXPIRE_SECONDS: int = Field(default=3600, gt=0)
    # Le doy a la URL firmada de lectura una vida corta; el cliente pide otra al vencer
    SIGNED_READ_URL_EXPIRE_SECONDS: int = Field(default=300, gt=0, le=7 * 24 * 3600)
    # Sin esta clave del proceso que reporta resultados por REST, rechazo toda llamada a ese endpoint
    JUMP_ANALYSIS_SERVICE_API_KEY: SecretStr | None = None
