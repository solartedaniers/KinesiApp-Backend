from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kinesiapp.common.v1.errors_pb2 import ErrorReason

from app.core.domain_error import DomainError


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    # Devuelvo estos headers porque forman parte de la firma: el PUT del navegador debe llevarlos tal cual
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class PresignedRead:
    url: str
    expires_at: datetime


@dataclass(frozen=True)
class StoredObject:
    size: int
    content_type: str | None


class SignedObjectStorage(Protocol):
    """Represento un bucket privado: el navegador sube y lee con URLs firmadas; yo solo firmo y verifico.

    En la base guardo la URL canónica del objeto (sin firma), la misma que guardaba el REST.
    """

    def url_for(self, key: str) -> str: ...

    # Espero ValueError si la URL no es de este bucket
    def key_from_url(self, object_url: str) -> str: ...

    def presign_upload(self, key: str, content_type: str, content_length: int) -> PresignedUpload: ...

    def presign_read(self, key: str) -> PresignedRead: ...

    async def describe(self, key: str) -> StoredObject | None: ...

    async def read_head(self, key: str, length: int) -> bytes: ...

    async def delete(self, key: str) -> None: ...


def storage_unavailable() -> DomainError:
    return DomainError(ErrorReason.ERROR_REASON_STORAGE_UNAVAILABLE, "File storage is not available right now")


class UnconfiguredSignedStorage:
    """La uso sin credenciales del bucket: respondo STORAGE_UNAVAILABLE en vez de impedir que arranque el servidor."""

    def url_for(self, key: str) -> str:
        raise storage_unavailable()

    def key_from_url(self, object_url: str) -> str:
        raise storage_unavailable()

    def presign_upload(self, key: str, content_type: str, content_length: int) -> PresignedUpload:
        raise storage_unavailable()

    def presign_read(self, key: str) -> PresignedRead:
        raise storage_unavailable()

    async def describe(self, key: str) -> StoredObject | None:
        raise storage_unavailable()

    async def read_head(self, key: str, length: int) -> bytes:
        raise storage_unavailable()

    async def delete(self, key: str) -> None:
        raise storage_unavailable()
