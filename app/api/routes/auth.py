from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.email import send_password_reset_email, send_verification_email
from app.core.security import get_current_user
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    OTPVerifyRequest,
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
    data: UserCreate, background_tasks: BackgroundTasks, service: AuthService = Depends(_get_service)
) -> UserRead:
    user = service.register(data)
    background_tasks.add_task(send_verification_email, user.email, user.verification_code)
    return user


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
    data: PasswordResetRequest, background_tasks: BackgroundTasks, service: AuthService = Depends(_get_service)
) -> dict[str, str]:
    code = service.request_password_reset(data.email)
    if code is not None:
        background_tasks.add_task(send_password_reset_email, data.email, code)
    # Misma respuesta exista o no el email: evita que el endpoint sirva para enumerar usuarios
    return {"detail": "If the email exists, a recovery code was sent"}


@router.post("/password-recovery/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_reset(data: PasswordResetConfirm, service: AuthService = Depends(_get_service)) -> None:
    service.confirm_password_reset(data.email, data.code, data.new_password)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserRead:
    return current_user
