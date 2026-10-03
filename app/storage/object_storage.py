from pathlib import Path
from typing import BinaryIO, Protocol


class ObjectStorageError(Exception):
    """El almacenamiento no respondió, el objeto no existe o la URL no pertenece a este bucket."""


class ObjectStorage(Protocol):
    """Frontera hacia el almacenamiento de objetos: el resto del dominio no sabe que es Neon/S3.

    Cada instancia trabaja sobre un único bucket y identifica los objetos por su URL pública,
    que es lo que se persiste.
    """

    def upload(self, source: BinaryIO, key: str, content_type: str) -> str: ...

    def download(self, public_url: str, destination: Path) -> None: ...

    def delete(self, public_url: str) -> None: ...


class UnconfiguredObjectStorage:
    """Se usa cuando faltan credenciales: la subida degrada a 503 en vez de impedir que arranque la app."""

    def upload(self, source: BinaryIO, key: str, content_type: str) -> str:
        raise ObjectStorageError("No object storage credentials configured")

    def download(self, public_url: str, destination: Path) -> None:
        raise ObjectStorageError("No object storage credentials configured")

    def delete(self, public_url: str) -> None:
        raise ObjectStorageError("No object storage credentials configured")
