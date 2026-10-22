from app.settings.storage import MediaSettings, StorageSettings
from app.storage.neon_signed_storage import NeonSignedStorage
from app.storage.s3_client import build_s3_client
from app.storage.signed_storage import SignedObjectStorage, UnconfiguredSignedStorage


def build_signed_storage(storage: StorageSettings, media: MediaSettings, bucket: str | None) -> SignedObjectStorage:
    secret = storage.AWS_SECRET_ACCESS_KEY.get_secret_value() if storage.AWS_SECRET_ACCESS_KEY else ""
    if not (bucket and storage.AWS_ENDPOINT_URL_S3 and storage.AWS_REGION and storage.AWS_ACCESS_KEY_ID and secret):
        return UnconfiguredSignedStorage()
    client = build_s3_client(storage.AWS_ENDPOINT_URL_S3, storage.AWS_REGION, storage.AWS_ACCESS_KEY_ID, secret)
    return NeonSignedStorage(
        client,
        storage.AWS_ENDPOINT_URL_S3,
        bucket,
        upload_expires_seconds=media.SIGNED_UPLOAD_URL_EXPIRE_SECONDS,
        read_expires_seconds=media.SIGNED_READ_URL_EXPIRE_SECONDS,
    )
