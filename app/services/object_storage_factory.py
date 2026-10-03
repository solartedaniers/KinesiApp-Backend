from functools import lru_cache

from app.core.config import Settings, settings
from app.storage.neon_object_storage import NeonObjectStorage
from app.storage.object_storage import ObjectStorage, UnconfiguredObjectStorage


def build_object_storage(config: Settings, bucket: str) -> ObjectStorage:
    # Un mismo armado para cualquier bucket (S3_VIDEOS_BUCKET, S3_IMAGES_BUCKET)
    secret = config.AWS_SECRET_ACCESS_KEY.get_secret_value() if config.AWS_SECRET_ACCESS_KEY else ""
    if not (config.AWS_ENDPOINT_URL_S3 and config.AWS_REGION and config.AWS_ACCESS_KEY_ID and secret):
        return UnconfiguredObjectStorage()
    return NeonObjectStorage(
        endpoint_url=config.AWS_ENDPOINT_URL_S3,
        region=config.AWS_REGION,
        access_key_id=config.AWS_ACCESS_KEY_ID,
        secret_access_key=secret,
        bucket=bucket,
    )


@lru_cache
def get_video_object_storage() -> ObjectStorage:
    # Un cliente de boto3 por proceso (es thread-safe), reutilizado entre requests
    return build_object_storage(settings, settings.S3_VIDEOS_BUCKET)
