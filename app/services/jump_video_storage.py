import mimetypes
import uuid
from pathlib import Path
from typing import BinaryIO

from fastapi import status

from app.core.exceptions import AppException, ErrorCode

# Bloques de 1 MB: el video nunca se carga entero en memoria del servidor
CHUNK_SIZE = 1024 * 1024


class JumpVideoStorage:
    """Guarda en disco el video subido de un salto, copiándolo por bloques."""

    def __init__(self, directory: Path, max_bytes: int) -> None:
        self._directory = directory
        self._max_bytes = max_bytes

    def save(self, source: BinaryIO, content_type: str | None) -> Path:
        if not content_type or not content_type.startswith("video/"):
            raise AppException(
                "The uploaded file must be a video",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                ErrorCode.INVALID_VIDEO,
            )
        self._directory.mkdir(parents=True, exist_ok=True)
        suffix = mimetypes.guess_extension(content_type) or ".bin"
        target = self._directory / f"{uuid.uuid4().hex}{suffix}"
        written = 0
        try:
            with target.open("wb") as destination:
                while chunk := source.read(CHUNK_SIZE):
                    written += len(chunk)
                    # Se corta en cuanto supera el límite, sin terminar de leer el resto
                    if written > self._max_bytes:
                        raise AppException(
                            "The video exceeds the maximum allowed size",
                            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            ErrorCode.VIDEO_TOO_LARGE,
                        )
                    destination.write(chunk)
        except BaseException:
            # Nunca deja archivos a medio escribir
            target.unlink(missing_ok=True)
            raise
        return target

    def delete(self, path: Path) -> None:
        # Sólo borra dentro del directorio de videos: una video_reference vieja o
        # manipulada nunca puede apuntar a otro archivo del servidor
        if path.resolve().is_relative_to(self._directory.resolve()):
            path.unlink(missing_ok=True)
