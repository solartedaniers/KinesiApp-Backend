"""Pruebo UserAdminService por la red, con los interceptores reales que exigen el rol ADMIN."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import grpc
import pytest
from kinesiapp.admin.v1 import user_admin_pb2, user_admin_pb2_grpc
from kinesiapp.common.v1 import identity_pb2, pagination_pb2

from app.admin.inputs import AdminInputRules
from app.admin.user_activation import UserActivation
from app.admin.user_directory import UserDirectory
from app.admin.user_provisioning import UserProvisioning
from app.admin.user_role_assignment import UserRoleAssignment
from app.auth.one_time_codes import OneTimeCodes
from app.auth.password_hasher import PasswordHasher
from app.core.pagination import PageRules
from app.identity.password_policy import PasswordPolicy
from app.models.athlete import AthleteProfile, Gender
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.rpc.user_admin_servicer import UserAdminServicer
from app.settings.auth import PasswordPolicySettings
from app.storage.avatar_links import AvatarLinks
from tests.grpc_harness import error_info
from tests.rpc_world import AUTH_SETTINGS, FakeBucket, World, bearer, rpc_world, uow_factory

STRONG_PASSWORD = "Kinesi-Prueba-2026"
HASHER = PasswordHasher()


class _Mailbox:
    def __init__(self) -> None:
        self.verification: dict[str, str] = {}

    async def send_verification_code(self, recipient: str, code: str) -> None:
        self.verification[recipient] = code

    async def send_password_reset_code(self, recipient: str, code: str) -> None:
        raise AssertionError("The admin never sends reset codes")


def _run(tmp_path: Path, scenario, mailbox: _Mailbox | None = None):
    mailbox = mailbox or _Mailbox()

    def register(session_factory):
        uows = uow_factory(session_factory)
        servicer = UserAdminServicer(
            AdminInputRules(PasswordPolicy(PasswordPolicySettings(_env_file=None))),
            PageRules(default_size=2, max_size=3),
            UserProvisioning(uows, HASHER, OneTimeCodes(AUTH_SETTINGS, HASHER), mailbox),
            UserDirectory(uows),
            UserRoleAssignment(uows),
            UserActivation(uows),
            AvatarLinks(FakeBucket()),
        )
        return partial(user_admin_pb2_grpc.add_UserAdminServiceServicer_to_server, servicer)

    async def main():
        async with rpc_world(tmp_path / "admin.db", register) as world:
            admin = await world.user("admin@kinesiapp.com", UserRole.ADMIN)
            return await scenario(world, user_admin_pb2_grpc.UserAdminServiceStub(world.channel), admin)

    return asyncio.run(main())


async def _error_of(call) -> grpc.aio.AioRpcError:
    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await call
    return raised.value


def _page(**page) -> user_admin_pb2.ListUsersRequest:
    return user_admin_pb2.ListUsersRequest(page=pagination_pb2.PageRequest(**page))


def test_only_admins_reach_the_service(tmp_path: Path) -> None:
    async def scenario(world: World, stub, admin):
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        return await _error_of(stub.GetUser(user_admin_pb2.GetUserRequest(user_id=admin.id), metadata=bearer(coach)))

    assert _run(tmp_path, scenario).code() == grpc.StatusCode.PERMISSION_DENIED


def test_create_user_sends_the_verification_code_and_rejects_duplicates_and_admins(tmp_path: Path) -> None:
    async def scenario(world: World, stub, admin):
        request = user_admin_pb2.CreateUserRequest(
            email="nuevo@kinesiapp.com", password=STRONG_PASSWORD, full_name="Nuevo Deportista",
            role=identity_pb2.USER_ROLE_ATHLETE,
        )
        created = await stub.CreateUser(request, metadata=bearer(admin))
        duplicated = await _error_of(stub.CreateUser(request, metadata=bearer(admin)))
        request.email, request.role = "otro@kinesiapp.com", identity_pb2.USER_ROLE_ADMIN
        as_admin = await _error_of(stub.CreateUser(request, metadata=bearer(admin)))
        request.role, request.password = identity_pb2.USER_ROLE_COACH, "corta"
        weak = await _error_of(stub.CreateUser(request, metadata=bearer(admin)))
        async with world.session_factory() as session:
            code_hash = (await session.get(User, created.user.id)).verification_code_hash
        return created.user, duplicated, as_admin, weak, code_hash

    user, duplicated, as_admin, weak, code_hash = _run(tmp_path, scenario, mailbox := _Mailbox())

    assert (user.email, user.role, user.is_verified, user.is_active) == (
        "nuevo@kinesiapp.com", identity_pb2.USER_ROLE_ATHLETE, False, False
    )
    assert user.id > 0 and user.HasField("created_at")
    # Compruebo que el código solo llega a la cuenta creada y que es el que quedó guardado
    assert list(mailbox.verification) == ["nuevo@kinesiapp.com"]
    assert asyncio.run(HASHER.verify(mailbox.verification["nuevo@kinesiapp.com"], code_hash))
    assert error_info(duplicated).reason == "EMAIL_ALREADY_REGISTERED"
    assert as_admin.code() == weak.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_list_users_walks_every_page_with_the_token(tmp_path: Path) -> None:
    async def scenario(world: World, stub, admin):
        for index in range(4):
            await world.user(f"persona{index}@kinesiapp.com")
        pages, token = [], ""
        while True:
            response = await stub.ListUsers(_page(page_token=token), metadata=bearer(admin))
            pages.append([user.email for user in response.users])
            token = response.page.next_page_token
            if not token:
                break
        too_big = await stub.ListUsers(_page(page_size=50), metadata=bearer(admin))
        bad_token = await _error_of(stub.ListUsers(_page(page_token="basura"), metadata=bearer(admin)))
        return pages, len(too_big.users), bad_token

    pages, capped, bad_token = _run(tmp_path, scenario)

    assert [len(page) for page in pages] == [2, 2, 1]
    assert pages[0][0] == "admin@kinesiapp.com" and pages[-1] == ["persona3@kinesiapp.com"]
    assert capped == 3
    assert bad_token.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_get_user_reports_missing_accounts(tmp_path: Path) -> None:
    async def scenario(world: World, stub, admin):
        found = await stub.GetUser(user_admin_pb2.GetUserRequest(user_id=admin.id), metadata=bearer(admin))
        missing = await _error_of(stub.GetUser(user_admin_pb2.GetUserRequest(user_id=999), metadata=bearer(admin)))
        return found.user, missing

    user, missing = _run(tmp_path, scenario)

    assert user.role == identity_pb2.USER_ROLE_ADMIN
    assert missing.code() == grpc.StatusCode.NOT_FOUND


def test_role_changes_protect_the_admin_and_the_coach_athletes(tmp_path: Path) -> None:
    async def scenario(world: World, stub, admin):
        athlete = await world.user("deportista@kinesiapp.com")
        coach = await world.user("coach@kinesiapp.com", UserRole.COACH)
        async with world.session_factory() as session:
            session.add(AthleteProfile(full_name="Gestionado Uno", coach_id=coach.id, gender=Gender.FEMALE,
                                       height_cm=170, weight_kg=60, birth_date=date(2004, 5, 1)))
            await session.commit()

        def change(user, role):
            request = user_admin_pb2.UpdateUserRoleRequest(user_id=user.id, role=role)
            return stub.UpdateUserRole(request, metadata=bearer(admin))

        promoted = await change(athlete, identity_pb2.USER_ROLE_COACH)
        own = await _error_of(change(admin, identity_pb2.USER_ROLE_ATHLETE))
        orphaning = await _error_of(change(coach, identity_pb2.USER_ROLE_ATHLETE))
        unspecified = await _error_of(change(athlete, identity_pb2.USER_ROLE_UNSPECIFIED))
        return promoted.user, own, orphaning, unspecified

    promoted, own, orphaning, unspecified = _run(tmp_path, scenario)

    assert promoted.role == identity_pb2.USER_ROLE_COACH
    assert (own.code(), error_info(own).reason) == (grpc.StatusCode.FAILED_PRECONDITION, "CANNOT_MODIFY_OWN_ACCOUNT")
    assert error_info(orphaning).reason == "COACH_HAS_ATHLETES"
    assert unspecified.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_deactivating_a_user_closes_its_sessions(tmp_path: Path) -> None:
    async def scenario(world: World, stub, admin):
        athlete = await world.user("deportista@kinesiapp.com")
        async with world.session_factory() as session:
            session.add(RefreshToken(user_id=athlete.id, token_hash="a" * 64,
                                     expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
            await session.commit()

        def status(user, is_active):
            return stub.UpdateUserStatus(
                user_admin_pb2.UpdateUserStatusRequest(user_id=user.id, is_active=is_active), metadata=bearer(admin)
            )

        disabled = await status(athlete, False)
        own = await _error_of(status(admin, False))
        async with world.session_factory() as session:
            token = await session.get(RefreshToken, 1)
            revoked = token.revoked_at is not None
            still_active = (await session.get(User, athlete.id)).is_active
        return disabled.user, own, revoked, still_active

    user, own, revoked, still_active = _run(tmp_path, scenario)

    assert user.is_active is False and still_active is False
    assert revoked
    assert error_info(own).reason == "CANNOT_MODIFY_OWN_ACCOUNT"
