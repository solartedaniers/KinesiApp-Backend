from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.email import AuthEmailService, EmailDeliveryError, get_auth_email_service
from app.core.exceptions import ErrorCode, ServiceUnavailableException
from app.core.security import get_current_user
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    OTPVerifyRequest,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    TokenPair,
)
from app.schemas.user import UserCreate, UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db), RefreshTokenRepository(db))


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    data: UserCreate,
    service: AuthService = Depends(_get_service),
    email_service: AuthEmailService = Depends(get_auth_email_service),
) -> UserRead:
    user, code = service.register(data)
    try:
        email_service.send_verification_code(user.email, code)
    except EmailDeliveryError as error:
        raise ServiceUnavailableException(
            "Verification email could not be delivered",
            code=ErrorCode.EMAIL_DELIVERY_FAILED,
        ) from error
    return user


@router.post("/verification-code/request", status_code=status.HTTP_202_ACCEPTED)
def request_verification_code(
    data: PasswordResetRequest,
    service: AuthService = Depends(_get_service),
    email_service: AuthEmailService = Depends(get_auth_email_service),
) -> dict[str, str]:
    code = service.request_verification_code(data.email)
    if code is not None:
        try:
            email_service.send_verification_code(data.email, code)
        except EmailDeliveryError as error:
            raise ServiceUnavailableException(
                "Verification email could not be delivered",
                code=ErrorCode.EMAIL_DELIVERY_FAILED,
            ) from error
    return {"detail": "If the account can be verified, a new code was sent"}


@router.post("/verify-email", response_model=TokenPair)
def verify_email(data: OTPVerifyRequest, service: AuthService = Depends(_get_service)) -> TokenPair:
    return service.verify_email(data.email, data.code)


@router.post("/login", response_model=TokenPair)
def login(data: LoginRequest, service: AuthService = Depends(_get_service)) -> TokenPair:
    return service.login(data.email, data.password)


@router.post("/refresh", response_model=TokenPair)
def refresh_token(data: RefreshRequest, service: AuthService = Depends(_get_service)) -> TokenPair:
    return service.refresh(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: RefreshRequest, service: AuthService = Depends(_get_service)) -> None:
    service.logout(data.refresh_token)


@router.post("/password-recovery/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    data: PasswordResetRequest,
    service: AuthService = Depends(_get_service),
    email_service: AuthEmailService = Depends(get_auth_email_service),
) -> dict[str, str]:
    code = service.request_password_reset(data.email)
    if code is not None:
        try:
            email_service.send_password_reset_code(data.email, code)
        except EmailDeliveryError as error:
            raise ServiceUnavailableException(
                "Password recovery email could not be delivered",
                code=ErrorCode.EMAIL_DELIVERY_FAILED,
            ) from error
    # Misma respuesta exista o no el email: evita que el endpoint sirva para enumerar usuarios
    return {"detail": "If the email exists, a recovery code was sent"}


@router.post("/password-recovery/verify", status_code=status.HTTP_204_NO_CONTENT)
def verify_password_reset_code(data: OTPVerifyRequest, service: AuthService = Depends(_get_service)) -> None:
    service.verify_password_reset_code(data.email, data.code)


@router.post("/password-recovery/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_reset(data: PasswordResetConfirm, service: AuthService = Depends(_get_service)) -> None:
    service.confirm_password_reset(data.email, data.code, data.new_password)


@router.post("/password/change", response_model=TokenPair)
def change_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    service: AuthService = Depends(_get_service),
) -> TokenPair:
    return service.change_password(current_user, data.current_password, data.new_password)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserRead:
    return current_user
