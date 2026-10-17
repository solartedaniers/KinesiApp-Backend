import grpc
from kinesiapp.auth.v1 import auth_pb2, auth_pb2_grpc

from app.auth.email_verification import EmailVerification
from app.auth.inputs import (
    AuthInputRules,
    CodeInput,
    EmailInput,
    LoginInput,
    PasswordChangeInput,
    PasswordResetInput,
    RefreshTokenInput,
    RegisterInput,
)
from app.auth.password_change import PasswordChange
from app.auth.password_recovery import PasswordRecovery
from app.auth.registration import Registration
from app.auth.session_management import SessionManagement
from app.auth.session_tokens import SessionTokens
from app.identity.principal import current_principal
from app.rpc.proto_values import timestamp
from app.rpc.user_roles import role_from_proto


class AuthServicer(auth_pb2_grpc.AuthServiceServicer):
    """kinesiapp.auth.v1.AuthService: traduce cada RPC al caso de uso que le corresponde."""

    def __init__(
        self,
        rules: AuthInputRules,
        registration: Registration,
        verification: EmailVerification,
        sessions: SessionManagement,
        recovery: PasswordRecovery,
        password_change: PasswordChange,
    ) -> None:
        self._rules = rules
        self._registration = registration
        self._verification = verification
        self._sessions = sessions
        self._recovery = recovery
        self._password_change = password_change

    async def Register(
        self, request: auth_pb2.RegisterRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.RegisterResponse:
        data = self._rules.parse(
            RegisterInput,
            {
                "email": request.email,
                "password": request.password,
                "full_name": request.full_name,
                "role": role_from_proto(request.role),
                "accepted_video_consent_version": request.accepted_video_consent_version,
            },
        )
        await self._registration.register(data)
        return auth_pb2.RegisterResponse()

    async def RequestVerificationCode(
        self, request: auth_pb2.RequestVerificationCodeRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.RequestVerificationCodeResponse:
        data = self._rules.parse(EmailInput, {"email": request.email})
        await self._verification.request_code(data.email)
        return auth_pb2.RequestVerificationCodeResponse()

    async def VerifyEmail(
        self, request: auth_pb2.VerifyEmailRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.VerifyEmailResponse:
        data = self._rules.parse(CodeInput, {"email": request.email, "code": request.code})
        return auth_pb2.VerifyEmailResponse(session=_session(await self._verification.verify(data.email, data.code)))

    async def Login(self, request: auth_pb2.LoginRequest, context: grpc.aio.ServicerContext) -> auth_pb2.LoginResponse:
        data = self._rules.parse(LoginInput, {"email": request.email, "password": request.password})
        return auth_pb2.LoginResponse(session=_session(await self._sessions.login(data.email, data.password)))

    async def RefreshSession(
        self, request: auth_pb2.RefreshSessionRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.RefreshSessionResponse:
        data = self._rules.parse(RefreshTokenInput, {"refresh_token": request.refresh_token})
        return auth_pb2.RefreshSessionResponse(session=_session(await self._sessions.refresh(data.refresh_token)))

    async def Logout(self, request: auth_pb2.LogoutRequest, context: grpc.aio.ServicerContext) -> auth_pb2.LogoutResponse:
        data = self._rules.parse(RefreshTokenInput, {"refresh_token": request.refresh_token})
        await self._sessions.logout(data.refresh_token)
        return auth_pb2.LogoutResponse()

    async def RequestPasswordReset(
        self, request: auth_pb2.RequestPasswordResetRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.RequestPasswordResetResponse:
        data = self._rules.parse(EmailInput, {"email": request.email})
        await self._recovery.request_code(data.email)
        return auth_pb2.RequestPasswordResetResponse()

    async def VerifyPasswordResetCode(
        self, request: auth_pb2.VerifyPasswordResetCodeRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.VerifyPasswordResetCodeResponse:
        data = self._rules.parse(CodeInput, {"email": request.email, "code": request.code})
        await self._recovery.verify_code(data.email, data.code)
        return auth_pb2.VerifyPasswordResetCodeResponse()

    async def ConfirmPasswordReset(
        self, request: auth_pb2.ConfirmPasswordResetRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.ConfirmPasswordResetResponse:
        data = self._rules.parse(
            PasswordResetInput, {"email": request.email, "code": request.code, "new_password": request.new_password}
        )
        await self._recovery.confirm(data.email, data.code, data.new_password)
        return auth_pb2.ConfirmPasswordResetResponse()

    async def ChangePassword(
        self, request: auth_pb2.ChangePasswordRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.ChangePasswordResponse:
        data = self._rules.parse(
            PasswordChangeInput,
            {"current_password": request.current_password, "new_password": request.new_password},
        )
        session = await self._password_change.change(
            current_principal().user_id, data.current_password, data.new_password
        )
        return auth_pb2.ChangePasswordResponse(session=_session(session))


def _session(tokens: SessionTokens) -> auth_pb2.Session:
    return auth_pb2.Session(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_token_expires_at=timestamp(tokens.access_token_expires_at),
        refresh_token_expires_at=timestamp(tokens.refresh_token_expires_at),
    )
