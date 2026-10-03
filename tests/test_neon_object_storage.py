"""NeonObjectStorage y su armado desde Settings, sin red: botocore Stubber responde en lugar de Neon."""
from io import BytesIO

import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from pydantic import SecretStr

from app.core.config import settings
from app.services.object_storage_factory import build_object_storage
from app.storage.neon_object_storage import NeonObjectStorage
from app.storage.object_storage import ObjectStorageError, UnconfiguredObjectStorage

ENDPOINT = "https://storage.test"
BUCKET = "videos"


@pytest.fixture
def storage():
    storage = NeonObjectStorage(ENDPOINT, "eu-central-1", "test-key-id", "test-secret", BUCKET)
    with Stubber(storage._client) as stubber:
        storage.stubber = stubber
        yield storage
        stubber.assert_no_pending_responses()


def test_upload_returns_the_path_style_public_url(storage):
    storage.stubber.add_response(
        "put_object", {}, {"Bucket": BUCKET, "Key": "a b.mp4", "Body": ANY, "ContentType": "video/mp4"}
    )
    assert storage.upload(BytesIO(b"video"), "a b.mp4", "video/mp4") == f"{ENDPOINT}/{BUCKET}/a%20b.mp4"


def test_download_and_delete_resolve_the_key_from_the_url(storage, tmp_path):
    body = StreamingBody(BytesIO(b"video"), len(b"video"))
    storage.stubber.add_response("get_object", {"Body": body}, {"Bucket": BUCKET, "Key": "a b.mp4"})
    storage.stubber.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": "a b.mp4"})

    storage.download(f"{ENDPOINT}/{BUCKET}/a%20b.mp4", tmp_path / "copy.mp4")
    storage.delete(f"{ENDPOINT}/{BUCKET}/a%20b.mp4")
    assert (tmp_path / "copy.mp4").read_bytes() == b"video"


def test_urls_outside_the_bucket_are_rejected_without_calling_neon(storage, tmp_path):
    for foreign in (f"{ENDPOINT}/images/x.png", "https://evil.test/videos/x.mp4", r"C:\media\jump_videos\x.mp4"):
        with pytest.raises(ObjectStorageError):
            storage.delete(foreign)
        with pytest.raises(ObjectStorageError):
            storage.download(foreign, tmp_path / "x")


def test_provider_errors_become_object_storage_errors(storage):
    storage.stubber.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(ObjectStorageError):
        storage.upload(BytesIO(b"video"), "x.mp4", "video/mp4")


def test_factory_needs_every_credential(monkeypatch):
    monkeypatch.setattr(settings, "AWS_ENDPOINT_URL_S3", ENDPOINT)
    monkeypatch.setattr(settings, "AWS_REGION", "eu-central-1")
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", SecretStr("test-secret"))
    assert isinstance(build_object_storage(settings, settings.S3_VIDEOS_BUCKET), NeonObjectStorage)

    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", SecretStr(""))
    assert isinstance(build_object_storage(settings, settings.S3_VIDEOS_BUCKET), UnconfiguredObjectStorage)
