from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings
from app.schemas.password_policy import StrongPassword


class LoginRequest(BaseModel):
    email: EmailStr
    # Sin la política de contraseñas: una cuenta anterior a la regla vigente debe poder entrar
    password: str = Field(min_length=1, max_length=settings.PASSWORD_MAX_LENGTH)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(OTPVerifyRequest):
    new_password: StrongPassword


class PasswordChange(BaseModel):
    # La actual no pasa por la política: puede ser anterior a la regla vigente
    current_password: str = Field(min_length=1, max_length=settings.PASSWORD_MAX_LENGTH)
    new_password: StrongPassword
