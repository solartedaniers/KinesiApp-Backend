import logging
import mimetypes
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import BinaryIO
from urllib.parse import urlparse

from fastapi import status

from app.core.exceptions import AppException, ErrorCode, ServiceUnavailableException
from app.storage.object_storage import ObjectStorage, ObjectStorageError

logger = logging.getLogger(__name__)


class JumpVideoStorage:
    """Valida el video subido de un salto y lo guarda en el almacenamiento de objetos."""

    def __init__(self, object_storage: ObjectStorage, max_bytes: int) -> None:
        self._object_storage = object_storage
        self._max_bytes = max_bytes

    def save(self, source: BinaryIO, content_type: str | None) -> str:
        """Devuelve la URL pública del video. `source` debe admitir seek (el UploadFile lo admite)."""
        if not content_type or not content_type.startswith("video/"):
            raise AppException(
                "The uploaded file must be a video",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                ErrorCode.INVALID_VIDEO,
            )
        # El tamaño se mide antes de subir: un video demasiado grande no llega a la red
        if source.seek(0, os.SEEK_END) > self._max_bytes:
            raise AppException(
                "The video exceeds the maximum allowed size",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                ErrorCode.VIDEO_TOO_LARGE,
            )
        source.seek(0)
        # Sin parámetros: guess_extension("video/webm;codecs=vp8") da None y el video quedaría
        # como .bin, y el Content-Type con codecs confunde a algunos reproductores
        media_type = content_type.split(";")[0].strip()
        key = f"{uuid.uuid4().hex}{mimetypes.guess_extension(media_type) or '.bin'}"
        try:
            return self._object_storage.upload(source, key, media_type)
        except ObjectStorageError as error:
            logger.warning("Video upload failed: %s", error)
            raise ServiceUnavailableException(
                "Video storage is not available right now", code=ErrorCode.STORAGE_UNAVAILABLE
            ) from error

    def delete(self, video_url: str) -> None:
        # Se llama después de borrar la fila: si falla, sólo queda un objeto huérfano en el bucket
        try:
            self._object_storage.delete(video_url)
        except ObjectStorageError as error:
            logger.warning("Could not delete video %s: %s", video_url, error)

    @contextmanager
    def local_copy(self, video_url: str) -> Iterator[Path]:
        """Copia temporal en disco para el análisis (MediaPipe lee archivos); se borra al salir."""
        with TemporaryDirectory(prefix="kinesiapp-video-") as directory:
            path = Path(directory) / PurePosixPath(urlparse(video_url).path).name
            self._object_storage.download(video_url, path)
            yield path
