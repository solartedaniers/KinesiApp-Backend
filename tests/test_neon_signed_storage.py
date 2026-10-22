import asyncio
import io
from urllib.parse import parse_qs, urlparse

import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.core.domain_error import DomainError
from app.storage.neon_signed_storage import NeonSignedStorage
from app.storage.s3_client import build_s3_client

ENDPOINT = "https://storage.example.neon.tech"


def _storage() -> tuple[NeonSignedStorage, Stubber]:
    client = build_s3_client(ENDPOINT, "eu-central-1", "test-access-key", "test-secret-key")
    storage = NeonSignedStorage(client, ENDPOINT, "images", upload_expires_seconds=900, read_expires_seconds=300)
    return storage, Stubber(client)


def test_upload_url_signs_type_and_size_for_the_given_key() -> None:
    storage, _ = _storage()

    upload = storage.presign_upload("avatars/abc.png", "image/png", 2048)

    url = urlparse(upload.url)
    query = parse_qs(url.query)
    assert url.path == "/images/avatars/abc.png"
    assert query["X-Amz-Expires"] == ["900"]
    signed_headers = query["X-Amz-SignedHeaders"][0].split(";")
    assert {"content-type", "content-length"} <= set(signed_headers)
    assert upload.headers == {"Content-Type": "image/png"}


def test_read_url_expires_with_the_configured_lifetime() -> None:
    storage, _ = _storage()

    read = storage.presign_read("avatars/abc.png")

    assert parse_qs(urlparse(read.url).query)["X-Amz-Expires"] == ["300"]


def test_canonical_urls_round_trip_and_foreign_urls_are_rejected() -> None:
    storage, _ = _storage()

    assert storage.key_from_url(storage.url_for("avatars/a b.png")) == "avatars/a b.png"
    with pytest.raises(ValueError):
        storage.key_from_url("https://otro-bucket.example.com/images/avatars/x.png")


def test_describe_reports_size_or_none_when_missing() -> None:
    storage, stubber = _storage()
    stubber.add_response(
        "head_object", {"ContentLength": 2048, "ContentType": "image/png"}, {"Bucket": "images", "Key": "avatars/ok.png"}
    )
    stubber.add_client_error("head_object", service_error_code="404", http_status_code=404)

    with stubber:
        found = asyncio.run(storage.describe("avatars/ok.png"))
        missing = asyncio.run(storage.describe("avatars/missing.png"))

    assert (found.size, found.content_type) == (2048, "image/png")
    assert missing is None


def test_read_head_asks_only_for_the_first_bytes() -> None:
    storage, stubber = _storage()
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"\x89PNG\r\n\x1a\n...."), 12)},
        {"Bucket": "images", "Key": "avatars/ok.png", "Range": "bytes=0-11"},
    )

    with stubber:
        assert asyncio.run(storage.read_head("avatars/ok.png", 12)).startswith(b"\x89PNG")


def test_provider_errors_become_storage_unavailable() -> None:
    storage, stubber = _storage()
    stubber.add_client_error("delete_object", service_error_code="InternalError", http_status_code=500)

    with stubber, pytest.raises(DomainError) as raised:
        asyncio.run(storage.delete("avatars/x.png"))

    assert raised.value.message == "File storage is not available right now"
