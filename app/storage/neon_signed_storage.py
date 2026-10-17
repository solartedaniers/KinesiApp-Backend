import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

from boto3.exceptions import Boto3Error
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.signed_storage import PresignedRead, PresignedUpload, StoredObject, storage_unavailable

logger = logging.getLogger(__name__)

_MISSING_OBJECT_CODES = {"404", "NoSuchKey", "NotFound"}
_STORAGE_ERRORS = (BotoCoreError, ClientError, Boto3Error)


class NeonSignedStorage:
    """Adapter sobre el S3 de Neon. boto3 es bloqueante: cada llamada de red va en un hilo."""

    def __init__(
        self, client, endpoint_url: str, bucket: str, upload_expires_seconds: int, read_expires_seconds: int
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._base_url = f"{endpoint_url.rstrip('/')}/{bucket}/"
        self._upload_expires = upload_expires_seconds
        self._read_expires = read_expires_seconds

    def url_for(self, key: str) -> str:
        return self._base_url + quote(key)

    def key_from_url(self, object_url: str) -> str:
        # Una referencia vieja o manipulada nunca puede tocar objetos fuera de este bucket
        if not object_url.startswith(self._base_url):
            raise ValueError(f"URL does not belong to bucket '{self._bucket}'")
        return unquote(object_url.removeprefix(self._base_url))

    # Firmar es un cálculo local con las credenciales: no sale a la red, así que no necesita hilo
    def presign_upload(self, key: str, content_type: str, content_length: int) -> PresignedUpload:
        # Content-Length va en la firma: el bucket rechaza un archivo de otro tamaño
        params = {"Bucket": self._bucket, "Key": key, "ContentType": content_type, "ContentLength": content_length}
        url = self._client.generate_presigned_url("put_object", Params=params, ExpiresIn=self._upload_expires)
        return PresignedUpload(url=url, headers={"Content-Type": content_type}, expires_at=_after(self._upload_expires))

    def presign_read(self, key: str) -> PresignedRead:
        params = {"Bucket": self._bucket, "Key": key}
        url = self._client.generate_presigned_url("get_object", Params=params, ExpiresIn=self._read_expires)
        return PresignedRead(url=url, expires_at=_after(self._read_expires))

    async def describe(self, key: str) -> StoredObject | None:
        try:
            head = await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
                return None
            logger.warning("Could not describe object %s: %s", key, error)
            raise storage_unavailable() from error
        except _STORAGE_ERRORS as error:
            logger.warning("Could not describe object %s: %s", key, error)
            raise storage_unavailable() from error
        return StoredObject(size=head["ContentLength"], content_type=head.get("ContentType"))

    async def read_head(self, key: str, length: int) -> bytes:
        def read() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key, Range=f"bytes=0-{length - 1}")
            return response["Body"].read()

        return await self._call(read)

    async def delete(self, key: str) -> None:
        await self._call(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def _call(self, operation, *args, **kwargs):
        try:
            return await asyncio.to_thread(operation, *args, **kwargs)
        except _STORAGE_ERRORS as error:
            logger.warning("Object storage call failed: %s", error)
            raise storage_unavailable() from error


def _after(seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)
