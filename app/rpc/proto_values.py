from datetime import datetime

from google.protobuf.timestamp_pb2 import Timestamp
from kinesiapp.common.v1 import storage_pb2

from app.storage.image_formats import ImageFormat
from app.storage.signed_storage import PresignedRead, PresignedUpload

_IMAGE_PREFIX = "IMAGE_CONTENT_TYPE_"


def timestamp(moment: datetime) -> Timestamp:
    value = Timestamp()
    value.FromDatetime(moment)
    return value


def signed_url(read: PresignedRead) -> storage_pb2.SignedUrl:
    return storage_pb2.SignedUrl(url=read.url, expires_at=timestamp(read.expires_at))


def upload_target(upload: PresignedUpload) -> storage_pb2.UploadTarget:
    return storage_pb2.UploadTarget(url=upload.url, headers=upload.headers, expires_at=timestamp(upload.expires_at))


def image_format_from_proto(content_type: storage_pb2.ImageContentType.ValueType) -> ImageFormat | None:
    # Devuelvo None para IMAGE_CONTENT_TYPE_UNSPECIFIED y el validador lo reporta como campo inválido
    return ImageFormat.__members__.get(storage_pb2.ImageContentType.Name(content_type).removeprefix(_IMAGE_PREFIX))
