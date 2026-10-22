"""Pruebo AccountService por la red, con el bucket en memoria y los interceptores reales."""

import asyncio
from functools import partial
from pathlib import Path

import grpc
import pytest
from kinesiapp.account.v1 import account_pb2, account_pb2_grpc
from kinesiapp.common.v1 import identity_pb2, storage_pb2

from app.account.account_profile import AccountProfile
from app.account.avatar_management import AvatarManagement
from app.account.inputs import AccountInputRules
from app.account.video_consent import VideoConsent
from app.models.user import UserRole
from app.rpc.account_servicer import AccountServicer
from app.storage.avatar_files import AvatarFiles
from app.storage.avatar_links import AvatarLinks
from app.storage.upload_tickets import UploadTicketService
from tests.grpc_harness import error_info
from tests.rpc_world import AUTH_SETTINGS, FakeBucket, World, bearer, rpc_world, uow_factory

MAX_AVATAR_BYTES = 64
CONSENT_VERSION = 2
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _run(tmp_path: Path, scenario, bucket: FakeBucket | None = None):
    bucket = bucket or FakeBucket()

    def register(session_factory):
        uows = uow_factory(session_factory)
        servicer = AccountServicer(
            AccountInputRules(MAX_AVATAR_BYTES),
            AccountProfile(uows),
            AvatarManagement(uows, AvatarFiles(bucket, UploadTicketService(AUTH_SETTINGS, 60), MAX_AVATAR_BYTES)),
            VideoConsent(uows, CONSENT_VERSION),
            AvatarLinks(bucket),
        )
        return partial(account_pb2_grpc.add_AccountServiceServicer_to_server, servicer)

    async def main():
        async with rpc_world(tmp_path / "account.db", register) as world:
            return await scenario(world, account_pb2_grpc.AccountServiceStub(world.channel), bucket)

    return asyncio.run(main())


async def _error_of(call) -> grpc.aio.AioRpcError:
    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await call
    return raised.value


def test_every_method_needs_a_session(tmp_path: Path) -> None:
    async def scenario(world: World, stub, bucket):
        return await _error_of(stub.GetMyAccount(account_pb2.GetMyAccountRequest()))

    assert _run(tmp_path, scenario).code() == grpc.StatusCode.UNAUTHENTICATED


def test_get_and_rename_my_account(tmp_path: Path) -> None:
    async def scenario(world: World, stub, bucket):
        ana = await world.user("ana@kinesiapp.com", UserRole.COACH)
        renamed = await stub.UpdateMyProfile(
            account_pb2.UpdateMyProfileRequest(full_name="  Ana   María "), metadata=bearer(ana)
        )
        invalid = await _error_of(
            stub.UpdateMyProfile(account_pb2.UpdateMyProfileRequest(full_name="R2D2"), metadata=bearer(ana))
        )
        mine = await stub.GetMyAccount(account_pb2.GetMyAccountRequest(), metadata=bearer(ana))
        return renamed.account, invalid, mine.account

    renamed, invalid, mine = _run(tmp_path, scenario)

    assert renamed.full_name == "Ana María"
    assert invalid.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert (mine.email, mine.full_name, mine.role) == ("ana@kinesiapp.com", "Ana María", identity_pb2.USER_ROLE_COACH)
    assert not mine.HasField("avatar") and not mine.HasField("video_consent_version")


def test_avatar_is_uploaded_directly_and_replaces_the_previous_one(tmp_path: Path) -> None:
    async def scenario(world: World, stub, bucket: FakeBucket):
        ana = await world.user("ana@kinesiapp.com")
        old_key = "avatars/old.png"
        bucket.browser_put(old_key, PNG, "image/png")
        async with world.uow() as uow:
            (await uow.users.get(ana.id)).avatar_url = bucket.url_for(old_key)
            await uow.commit()

        upload = await stub.CreateAvatarUpload(
            account_pb2.CreateAvatarUploadRequest(content_type=storage_pb2.IMAGE_CONTENT_TYPE_PNG, content_length=len(PNG)),
            metadata=bearer(ana),
        )
        key, content_type, length = bucket.signed_uploads[-1]
        bucket.browser_put(key, PNG, content_type)
        confirmed = await stub.ConfirmAvatarUpload(
            account_pb2.ConfirmAvatarUploadRequest(upload_id=upload.upload_id), metadata=bearer(ana)
        )
        again = await stub.ConfirmAvatarUpload(
            account_pb2.ConfirmAvatarUploadRequest(upload_id=upload.upload_id), metadata=bearer(ana)
        )
        return upload, key, length, confirmed.account, again.account

    upload, key, length, confirmed, again = _run(tmp_path, scenario, bucket := FakeBucket())

    assert upload.target.headers["Content-Type"] == "image/png" and length == len(PNG)
    assert key.startswith("avatars/") and key.endswith(".png")
    assert confirmed.avatar.url.startswith(f"https://bucket.test/images/{key}?signature=get")
    # Compruebo que se borra la foto anterior y que confirmar de nuevo no borra la nueva
    assert set(bucket.objects) == {key}
    assert again.avatar.url == confirmed.avatar.url


def test_avatar_upload_rejects_wrong_type_size_or_content(tmp_path: Path) -> None:
    async def scenario(world: World, stub, bucket: FakeBucket):
        ana = await world.user("ana@kinesiapp.com")
        too_big = await _error_of(
            stub.CreateAvatarUpload(
                account_pb2.CreateAvatarUploadRequest(content_type=storage_pb2.IMAGE_CONTENT_TYPE_PNG, content_length=999),
                metadata=bearer(ana),
            )
        )
        no_type = await _error_of(
            stub.CreateAvatarUpload(account_pb2.CreateAvatarUploadRequest(content_length=10), metadata=bearer(ana))
        )
        upload = await stub.CreateAvatarUpload(
            account_pb2.CreateAvatarUploadRequest(content_type=storage_pb2.IMAGE_CONTENT_TYPE_JPEG, content_length=len(PNG)),
            metadata=bearer(ana),
        )
        confirm = account_pb2.ConfirmAvatarUploadRequest(upload_id=upload.upload_id)
        not_uploaded = await _error_of(stub.ConfirmAvatarUpload(confirm, metadata=bearer(ana)))
        key = bucket.signed_uploads[-1][0]
        bucket.browser_put(key, PNG, "image/jpeg")
        not_a_jpeg = await _error_of(stub.ConfirmAvatarUpload(confirm, metadata=bearer(ana)))
        other = await world.user("otro@kinesiapp.com")
        someone_elses = await _error_of(stub.ConfirmAvatarUpload(confirm, metadata=bearer(other)))
        return too_big, no_type, not_uploaded, not_a_jpeg, someone_elses, key in bucket.objects

    too_big, no_type, not_uploaded, not_a_jpeg, someone_elses, kept = _run(tmp_path, scenario)

    assert too_big.code() == no_type.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert error_info(not_uploaded).reason == "UPLOAD_NOT_FOUND"
    assert (not_a_jpeg.code(), error_info(not_a_jpeg).reason) == (grpc.StatusCode.INVALID_ARGUMENT, "INVALID_IMAGE")
    assert error_info(someone_elses).reason == "UPLOAD_NOT_FOUND"
    # Compruebo que el archivo que no es la imagen declarada no se queda en el bucket
    assert kept is False


def test_delete_my_avatar_removes_it_from_the_bucket(tmp_path: Path) -> None:
    async def scenario(world: World, stub, bucket: FakeBucket):
        bucket.browser_put("avatars/mine.png", PNG, "image/png")
        ana = await world.user("ana@kinesiapp.com", avatar_url=bucket.url_for("avatars/mine.png"))
        response = await stub.DeleteMyAvatar(account_pb2.DeleteMyAvatarRequest(), metadata=bearer(ana))
        return response.account, dict(bucket.objects)

    account, objects = _run(tmp_path, scenario)

    assert not account.HasField("avatar")
    assert objects == {}


def test_video_consent_only_for_the_current_version_and_roles_that_upload(tmp_path: Path) -> None:
    async def scenario(world: World, stub, bucket):
        athlete = await world.user("ana@kinesiapp.com")
        admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
        granted = await stub.GrantVideoConsent(
            account_pb2.GrantVideoConsentRequest(version=CONSENT_VERSION), metadata=bearer(athlete)
        )
        old_version = await _error_of(
            stub.GrantVideoConsent(account_pb2.GrantVideoConsentRequest(version=1), metadata=bearer(athlete))
        )
        as_admin = await _error_of(
            stub.GrantVideoConsent(account_pb2.GrantVideoConsentRequest(version=CONSENT_VERSION), metadata=bearer(admin))
        )
        return granted.account, old_version, as_admin

    account, old_version, as_admin = _run(tmp_path, scenario)

    assert account.video_consent_version == CONSENT_VERSION and account.HasField("video_consent_given_at")
    assert (old_version.code(), error_info(old_version).reason) == (grpc.StatusCode.INVALID_ARGUMENT, "BAD_REQUEST")
    assert (as_admin.code(), error_info(as_admin).reason) == (grpc.StatusCode.PERMISSION_DENIED, "FORBIDDEN")
