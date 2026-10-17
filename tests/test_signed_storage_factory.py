import pytest

from app.settings.storage import MediaSettings, StorageSettings
from app.storage.neon_signed_storage import NeonSignedStorage
from app.storage.signed_storage import UnconfiguredSignedStorage
from app.storage.signed_storage_factory import build_signed_storage

CREDENTIALS = {
    "AWS_ENDPOINT_URL_S3": "https://storage.example.neon.tech",
    "AWS_REGION": "eu-central-1",
    "AWS_ACCESS_KEY_ID": "test-access-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret-key",
}


@pytest.mark.parametrize("private_bucket", [None, ""])
def test_without_a_private_bucket_it_never_falls_back_to_the_public_ones(private_bucket) -> None:
    storage = StorageSettings(_env_file=None, **CREDENTIALS, S3_PRIVATE_IMAGES_BUCKET=private_bucket)

    signed = build_signed_storage(storage, MediaSettings(_env_file=None), storage.S3_PRIVATE_IMAGES_BUCKET)

    assert isinstance(signed, UnconfiguredSignedStorage)


def test_with_a_private_bucket_it_signs_against_that_bucket() -> None:
    storage = StorageSettings(_env_file=None, **CREDENTIALS, S3_PRIVATE_IMAGES_BUCKET="kinesiapp-dev-images")

    signed = build_signed_storage(storage, MediaSettings(_env_file=None), storage.S3_PRIVATE_IMAGES_BUCKET)

    assert isinstance(signed, NeonSignedStorage)
    assert signed.url_for("avatars/a.png") == "https://storage.example.neon.tech/kinesiapp-dev-images/avatars/a.png"
