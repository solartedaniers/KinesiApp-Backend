import shutil
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, unquote

import boto3
from boto3.exceptions import Boto3Error
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.object_storage import ObjectStorageError


class NeonObjectStorage:
    """Almacenamiento S3 de Neon vía boto3. Cualquier falla del proveedor sale como ObjectStorageError."""

    def __init__(
        self, endpoint_url: str, region: str, access_key_id: str, secret_access_key: str, bucket: str
    ) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            # Neon sólo publica URLs path-style: su certificado no cubre <bucket>.<endpoint>
            config=Config(s3={"addressing_style": "path"}),
        )
        self._bucket = bucket
        self._public_base_url = f"{endpoint_url.rstrip('/')}/{bucket}/"

    def upload(self, source: BinaryIO, key: str, content_type: str) -> str:
        try:
            # ContentType queda en el objeto: el navegador lo reproduce directo desde la URL pública
            self._client.put_object(Bucket=self._bucket, Key=key, Body=source, ContentType=content_type)
        except (BotoCoreError, ClientError, Boto3Error) as error:
            raise ObjectStorageError(str(error)) from error
        return self._public_base_url + quote(key)

    def download(self, public_url: str, destination: Path) -> None:
        key = self._key_from_url(public_url)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            with destination.open("wb") as target:
                shutil.copyfileobj(response["Body"], target)
        except (BotoCoreError, ClientError, Boto3Error) as error:
            raise ObjectStorageError(str(error)) from error

    def delete(self, public_url: str) -> None:
        key = self._key_from_url(public_url)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError, Boto3Error) as error:
            raise ObjectStorageError(str(error)) from error

    def _key_from_url(self, public_url: str) -> str:
        # Una referencia vieja o manipulada nunca puede tocar objetos fuera de este bucket
        if not public_url.startswith(self._public_base_url):
            raise ObjectStorageError(f"URL does not belong to bucket '{self._bucket}'")
        return unquote(public_url.removeprefix(self._public_base_url))
