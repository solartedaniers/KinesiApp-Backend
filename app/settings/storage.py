from pydantic import Field, SecretStr

from app.settings.base import EnvSettings


class StorageSettings(EnvSettings):
    """Almacenamiento de objetos compatible con S3 de Neon, con los mismos nombres que usa boto3.

    Sin credenciales, subir un archivo responde storage_unavailable.
    """

    AWS_ENDPOINT_URL_S3: str | None = None
    AWS_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: SecretStr | None = None
    S3_VIDEOS_BUCKET: str = Field(default="videos", min_length=1)
    S3_IMAGES_BUCKET: str = Field(default="images", min_length=1)


class MediaSettings(EnvSettings):
    """Límites y permisos de los videos y avatares que suben las personas."""

    MAX_VIDEO_UPLOAD_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)
    # El cliente lo valida leyendo los metadatos del video antes de subirlo
    MAX_VIDEO_DURATION_SECONDS: int = Field(default=40, gt=0)
    # El cliente ya la redimensiona y comprime en un Web Worker antes de enviarla
    MAX_AVATAR_UPLOAD_BYTES: int = Field(default=1_000_000, gt=0)
    # Versión vigente del texto de consentimiento de video: subir exige haber aceptado esta
    VIDEO_CONSENT_VERSION: int = Field(default=1, gt=0)
    # Vida del token que autoriza reproducir un video. Va en la URL porque los reproductores no mandan
    # el header Authorization, por eso es corta
    VIDEO_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=10, gt=0)
    # Token con el que el navegador sube un video directo a la API. Se valida al terminar de llegar el
    # cuerpo, así que debe durar más que la subida más lenta
    VIDEO_UPLOAD_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    # Vida de la URL firmada con la que el navegador sube directo al bucket: debe cubrir la subida más lenta
    SIGNED_UPLOAD_URL_EXPIRE_SECONDS: int = Field(default=900, gt=0, le=7 * 24 * 3600)
    # Vida del upload_id con el que se confirma la subida: más larga que la URL, porque la subida empieza
    # antes de que la URL venza pero puede terminar después
    UPLOAD_TICKET_EXPIRE_SECONDS: int = Field(default=3600, gt=0)
    # Vida de la URL firmada para ver un archivo privado; el cliente pide otra al vencer
    SIGNED_READ_URL_EXPIRE_SECONDS: int = Field(default=300, gt=0, le=7 * 24 * 3600)
    # Clave del proceso interno que reporta resultados por REST. Sin definir, ese endpoint rechaza toda llamada
    JUMP_ANALYSIS_SERVICE_API_KEY: SecretStr | None = None
