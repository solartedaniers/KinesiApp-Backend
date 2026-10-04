import logging
import uuid
from collections.abc import Callable
from io import BytesIO
from typing import TypeVar

from app.core.exceptions import ErrorCode, ServiceUnavailableException
from app.schemas.avatar import AvatarUpload
from app.storage.object_storage import ObjectStorage, ObjectStorageError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Los tipos que admite AvatarUpload, con la extensión de la clave del objeto
_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class AvatarStorage:
    """Fotos de perfil en el almacenamiento de objetos (bucket de imágenes): en la base sólo va la URL."""

    def __init__(self, object_storage: ObjectStorage) -> None:
        self._object_storage = object_storage

    def replace(self, previous_url: str | None, upload: AvatarUpload | None, persist: Callable[[str | None], T]) -> T:
        """Sube la foto nueva (o ninguna, para quitarla), la persiste con `persist` y recién entonces
        borra la anterior. Si persistir falla, borra la recién subida: nunca quedan objetos huérfanos
        por un error, ni una URL en la base que apunte a un objeto inexistente."""
        new_url = self._save(upload) if upload is not None else None
        try:
            result = persist(new_url)
        except Exception:
            if new_url is not None:
                self.delete(new_url)
            raise
        if previous_url is not None:
            self.delete(previous_url)
        return result

    def delete(self, url: str) -> None:
        # Tras borrar la fila: si falla, sólo queda un objeto huérfano en el bucket
        try:
            self._object_storage.delete(url)
        except ObjectStorageError as error:
            logger.warning("Could not delete avatar %s: %s", url, error)

    def _save(self, upload: AvatarUpload) -> str:
        key = f"avatars/{uuid.uuid4().hex}{_EXTENSIONS[upload.content_type]}"
        try:
            return self._object_storage.upload(BytesIO(upload.content()), key, upload.content_type)
        except ObjectStorageError as error:
            logger.warning("Avatar upload failed: %s", error)
            raise ServiceUnavailableException(
                "Image storage is not available right now", code=ErrorCode.STORAGE_UNAVAILABLE
            ) from error
