"""Pruebo AuthService por la red, con los interceptores reales y SQLite asíncrono en un archivo temporal."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import grpc
import pytest
from kinesiapp.auth.v1 import auth_pb2, auth_pb2_grpc
from kinesiapp.common.v1 import identity_pb2
from kinesiapp.common.v1.errors_pb2 import ErrorReason
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  registra todos los modelos en Base.metadata
from app.auth.email_verification import EmailVerification
from app.auth.inputs import AuthInputRules
from app.auth.one_time_codes import OneTimeCodes
from app.auth.password_change import PasswordChange
from app.auth.password_hasher import PasswordHasher
from app.auth.password_recovery import PasswordRecovery
from app.auth.password_replacer import PasswordReplacer
from app.auth.registration import Registration
from app.auth.session_issuer import SessionIssuer
from app.auth.session_management import SessionManagement
from app.auth.session_tokens import SessionTokenService
from app.core.async_database import build_session_factory
from app.core.domain_error import DomainError
from app.identity.access_tokens import JwtAccessTokenVerifier
from app.identity.password_policy import PasswordPolicy
from app.models.base import Base
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.repositories.unit_of_work import UnitOfWork
from app.rpc.auth_servicer import AuthServicer
from app.rpc.interceptors.auth import AuthInterceptor
from app.rpc.interceptors.errors import ErrorInterceptor
from app.settings.auth import AuthSettings, PasswordPolicySettings
from tests.grpc_harness import error_info, field_violations, serving

EMAIL = "ana@kinesiapp.com"
PASSWORD = "Kinesi#2026"
CONSENT_VERSION = 3


@dataclass
class _Mailbox:
    """Simulo el mailer: guardo el último código enviado a cada correo, o fallo si me lo piden."""

    verification: dict[str, str] = field(default_factory=dict)
    reset: dict[str, str] = field(default_factory=dict)
    failing: bool = False

    async def send_verification_code(self, recipient: str, code: str) -> None:
        self._fail_if_asked()
        self.verification[recipient] = code

    async def send_password_reset_code(self, recipient: str, code: str) -> None:
        self._fail_if_asked()
        self.reset[recipient] = code

    def _fail_if_asked(self) -> None:
        if self.failing:
            raise DomainError(ErrorReason.ERROR_REASON_EMAIL_DELIVERY_FAILED, "The email could not be delivered")


class _DomainChecker:
    def is_deliverable(self, email: str) -> bool:
        return not email.endswith("@dominio-inventado.com")


@dataclass
class _Backend:
    stub: auth_pb2_grpc.AuthServiceStub
    mailbox: _Mailbox
    session_factory: async_sessionmaker[AsyncSession]

    async def user(self, email: str = EMAIL) -> User:
        async with self.session_factory() as session:
            return await session.scalar(select(User).where(User.email == email))

    async def registered_and_verified(self) -> auth_pb2.Session:
        await self.stub.Register(_register_request())
        response = await self.stub.VerifyEmail(
            auth_pb2.VerifyEmailRequest(email=EMAIL, code=self.mailbox.verification[EMAIL])
        )
        return response.session


@asynccontextmanager
async def _auth_backend(database: Path) -> AsyncIterator[_Backend]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = build_session_factory(engine)
    settings = AuthSettings(_env_file=None, JWT_SECRET_KEY="auth-rpc-test-secret-key", OTP_EXPIRE_MINUTES=10)
    uow_factory = partial(UnitOfWork, session_factory)
    hasher = PasswordHasher()
    tokens = SessionTokenService(settings)
    sessions = SessionIssuer(tokens)
    codes = OneTimeCodes(settings, hasher)
    passwords = PasswordReplacer(hasher)
    mailbox = _Mailbox()
    servicer = AuthServicer(
        AuthInputRules(PasswordPolicy(PasswordPolicySettings(_env_file=None)), settings.OTP_LENGTH),
        Registration(uow_factory, hasher, codes, mailbox, _DomainChecker(), CONSENT_VERSION),
        EmailVerification(uow_factory, codes, mailbox, sessions),
        SessionManagement(uow_factory, hasher, tokens, sessions),
        PasswordRecovery(uow_factory, codes, mailbox, passwords),
        PasswordChange(uow_factory, hasher, passwords, sessions),
    )
    interceptors = [ErrorInterceptor(), AuthInterceptor(JwtAccessTokenVerifier(settings, session_factory))]
    try:
        async with serving(partial(auth_pb2_grpc.add_AuthServiceServicer_to_server, servicer), interceptors) as channel:
            yield _Backend(auth_pb2_grpc.AuthServiceStub(channel), mailbox, session_factory)
    finally:
        await engine.dispose()


def _run(tmp_path: Path, scenario: Callable[[_Backend], Awaitable[object]]) -> object:
    async def main() -> object:
        async with _auth_backend(tmp_path / "auth.db") as backend:
            return await scenario(backend)

    return asyncio.run(main())


def _register_request(**overrides: object) -> auth_pb2.RegisterRequest:
    fields = {
        "email": EMAIL,
        "password": PASSWORD,
        "full_name": "Ana María",
        "role": identity_pb2.USER_ROLE_COACH,
        "accepted_video_consent_version": CONSENT_VERSION,
    }
    return auth_pb2.RegisterRequest(**{**fields, **overrides})


async def _error_of(call: Awaitable[object]) -> grpc.aio.AioRpcError:
    with pytest.raises(grpc.aio.AioRpcError) as raised:
        await call
    return raised.value


def _bearer(session: auth_pb2.Session) -> tuple[tuple[str, str], ...]:
    return (("authorization", f"Bearer {session.access_token}"),)


def test_register_verify_and_login(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> None:
        session = await backend.registered_and_verified()
        assert session.access_token and session.refresh_token
        assert session.access_token_expires_at.seconds < session.refresh_token_expires_at.seconds

        user = await backend.user()
        assert (user.is_verified, user.is_active, user.role) == (True, True, UserRole.COACH)
        assert user.video_consent_version == CONSENT_VERSION
        login = await backend.stub.Login(auth_pb2.LoginRequest(email=EMAIL, password=PASSWORD))
        assert login.session.access_token

    _run(tmp_path, scenario)


def test_register_requires_the_current_video_consent(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> grpc.aio.AioRpcError:
        return await _error_of(backend.stub.Register(_register_request(accepted_video_consent_version=1)))

    error = _run(tmp_path, scenario)

    assert error.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert error_info(error).reason == "CONSENT_REQUIRED"


def test_register_reports_every_invalid_field(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> grpc.aio.AioRpcError:
        request = _register_request(
            email="no-es-correo", password="debil", full_name="R2D2", role=identity_pb2.USER_ROLE_ADMIN
        )
        return await _error_of(backend.stub.Register(request))

    error = _run(tmp_path, scenario)

    assert error.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert sorted(field_violations(error)) == ["email", "full_name", "password", "role"]


def test_register_rejects_undeliverable_domains_and_verified_emails(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> list[grpc.aio.AioRpcError]:
        undeliverable = await _error_of(backend.stub.Register(_register_request(email="ana@dominio-inventado.com")))
        await backend.registered_and_verified()
        taken = await _error_of(backend.stub.Register(_register_request()))
        return [undeliverable, taken]

    undeliverable, taken = _run(tmp_path, scenario)

    assert error_info(undeliverable).reason == "EMAIL_DOMAIN_UNDELIVERABLE"
    assert taken.code() == grpc.StatusCode.ALREADY_EXISTS
    assert error_info(taken).reason == "EMAIL_ALREADY_REGISTERED"


def test_registering_again_an_unverified_email_replaces_the_pending_account(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> User:
        await backend.stub.Register(_register_request(full_name="Primer Intento"))
        await backend.stub.Register(_register_request(full_name="Segundo Intento"))
        return await backend.user()

    assert _run(tmp_path, scenario).full_name == "Segundo Intento"


def test_login_errors_follow_the_account_state(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> list[str]:
        unknown = await _error_of(backend.stub.Login(auth_pb2.LoginRequest(email="nadie@kinesiapp.com", password="x")))
        await backend.stub.Register(_register_request())
        unverified = await _error_of(backend.stub.Login(auth_pb2.LoginRequest(email=EMAIL, password=PASSWORD)))
        wrong = await _error_of(backend.stub.Login(auth_pb2.LoginRequest(email=EMAIL, password="Otra#2026x")))
        return [error_info(e).reason for e in (unknown, unverified, wrong)]

    assert _run(tmp_path, scenario) == ["EMAIL_NOT_REGISTERED", "EMAIL_NOT_VERIFIED", "INVALID_CREDENTIALS"]


def test_wrong_codes_count_until_the_code_is_no_longer_usable(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> tuple[list[str], int]:
        await backend.stub.Register(_register_request())
        good = backend.mailbox.verification[EMAIL]
        wrong = "000000" if good != "000000" else "111111"
        reasons = []
        for code in [wrong] * 5 + [good]:
            error = await _error_of(backend.stub.VerifyEmail(auth_pb2.VerifyEmailRequest(email=EMAIL, code=code)))
            reasons.append(error_info(error).reason)
        return reasons, (await backend.user()).verification_code_attempts

    reasons, attempts = _run(tmp_path, scenario)

    # Compruebo que tras los 5 intentos fallidos ni el código correcto sirve
    assert reasons == ["INVALID_OTP"] * 6
    assert attempts == 5


def test_concurrent_wrong_codes_never_exceed_the_attempt_limit(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> tuple[list[str], int, str]:
        await backend.stub.Register(_register_request())
        good = backend.mailbox.verification[EMAIL]
        wrong = "000000" if good != "000000" else "111111"
        errors = await asyncio.gather(
            *(_error_of(backend.stub.VerifyEmail(auth_pb2.VerifyEmailRequest(email=EMAIL, code=wrong))) for _ in range(12))
        )
        late = await _error_of(backend.stub.VerifyEmail(auth_pb2.VerifyEmailRequest(email=EMAIL, code=good)))
        attempts = (await backend.user()).verification_code_attempts
        return [error_info(e).reason for e in errors], attempts, error_info(late).reason

    reasons, attempts, late = _run(tmp_path, scenario)

    assert reasons == ["INVALID_OTP"] * 12
    assert attempts == 5
    assert late == "INVALID_OTP"


def test_concurrent_refreshes_with_the_same_token_open_a_single_session(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> tuple[list[str], int]:
        first = await backend.registered_and_verified()
        request = auth_pb2.RefreshSessionRequest(refresh_token=first.refresh_token)
        outcomes = await asyncio.gather(
            backend.stub.RefreshSession(request), backend.stub.RefreshSession(request), return_exceptions=True
        )
        async with backend.session_factory() as session:
            active = await session.scalar(
                select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))
            )
        return sorted("ok" if isinstance(o, auth_pb2.RefreshSessionResponse) else error_info(o).reason
                      for o in outcomes), active

    outcomes, active = _run(tmp_path, scenario)

    assert outcomes == ["INVALID_REFRESH_TOKEN", "ok"]
    assert active == 1


def test_refresh_rotates_the_token_and_logout_is_idempotent(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> list[str]:
        first = await backend.registered_and_verified()
        renewed = await backend.stub.RefreshSession(auth_pb2.RefreshSessionRequest(refresh_token=first.refresh_token))
        reused = await _error_of(
            backend.stub.RefreshSession(auth_pb2.RefreshSessionRequest(refresh_token=first.refresh_token))
        )
        await backend.stub.Logout(auth_pb2.LogoutRequest(refresh_token=renewed.session.refresh_token))
        await backend.stub.Logout(auth_pb2.LogoutRequest(refresh_token=renewed.session.refresh_token))
        after_logout = await _error_of(
            backend.stub.RefreshSession(auth_pb2.RefreshSessionRequest(refresh_token=renewed.session.refresh_token))
        )
        forged = await _error_of(backend.stub.RefreshSession(auth_pb2.RefreshSessionRequest(refresh_token="x.y.z")))
        return [error_info(e).reason for e in (reused, after_logout, forged)]

    assert _run(tmp_path, scenario) == ["INVALID_REFRESH_TOKEN"] * 3


def test_password_recovery_changes_the_password_and_closes_every_session(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> tuple[str, bool, bool]:
        session = await backend.registered_and_verified()
        await backend.stub.RequestPasswordReset(auth_pb2.RequestPasswordResetRequest(email="nadie@kinesiapp.com"))
        await backend.stub.RequestPasswordReset(auth_pb2.RequestPasswordResetRequest(email=EMAIL))
        code = backend.mailbox.reset[EMAIL]
        await backend.stub.VerifyPasswordResetCode(auth_pb2.VerifyPasswordResetCodeRequest(email=EMAIL, code=code))
        await backend.stub.ConfirmPasswordReset(
            auth_pb2.ConfirmPasswordResetRequest(email=EMAIL, code=code, new_password="Nueva#2026x")
        )
        old_session = await _error_of(
            backend.stub.RefreshSession(auth_pb2.RefreshSessionRequest(refresh_token=session.refresh_token))
        )
        login = await backend.stub.Login(auth_pb2.LoginRequest(email=EMAIL, password="Nueva#2026x"))
        # Compruebo que a un correo sin cuenta no le envío nada, aunque la respuesta sea la misma
        return error_info(old_session).reason, bool(login.session.access_token), "nadie@kinesiapp.com" in backend.mailbox.reset

    assert _run(tmp_path, scenario) == ("INVALID_REFRESH_TOKEN", True, False)


def test_change_password_needs_a_session_and_the_current_password(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> list[tuple[grpc.StatusCode, str]]:
        session = await backend.registered_and_verified()
        anonymous = await _error_of(
            backend.stub.ChangePassword(auth_pb2.ChangePasswordRequest(current_password=PASSWORD, new_password="Nueva#2026x"))
        )
        wrong_current = await _error_of(
            backend.stub.ChangePassword(
                auth_pb2.ChangePasswordRequest(current_password="Mala#2026x", new_password="Nueva#2026x"),
                metadata=_bearer(session),
            )
        )
        reused = await _error_of(
            backend.stub.ChangePassword(
                auth_pb2.ChangePasswordRequest(current_password=PASSWORD, new_password=PASSWORD),
                metadata=_bearer(session),
            )
        )
        changed = await backend.stub.ChangePassword(
            auth_pb2.ChangePasswordRequest(current_password=PASSWORD, new_password="Nueva#2026x"),
            metadata=_bearer(session),
        )
        assert changed.session.access_token
        old_refresh = await _error_of(
            backend.stub.RefreshSession(auth_pb2.RefreshSessionRequest(refresh_token=session.refresh_token))
        )
        return [(e.code(), error_info(e).reason) for e in (anonymous, wrong_current, reused, old_refresh)]

    assert _run(tmp_path, scenario) == [
        (grpc.StatusCode.UNAUTHENTICATED, "UNAUTHORIZED"),
        # Espero INVALID_ARGUMENT y no UNAUTHENTICATED, que haría que el cliente renueve la sesión
        (grpc.StatusCode.INVALID_ARGUMENT, "INVALID_CURRENT_PASSWORD"),
        (grpc.StatusCode.ALREADY_EXISTS, "PASSWORD_REUSED"),
        (grpc.StatusCode.UNAUTHENTICATED, "INVALID_REFRESH_TOKEN"),
    ]


def test_mail_failure_is_reported_as_unavailable(tmp_path: Path) -> None:
    async def scenario(backend: _Backend) -> grpc.aio.AioRpcError:
        backend.mailbox.failing = True
        return await _error_of(backend.stub.Register(_register_request()))

    error = _run(tmp_path, scenario)

    assert error.code() == grpc.StatusCode.UNAVAILABLE
    assert error_info(error).reason == "EMAIL_DELIVERY_FAILED"
