from pydantic import BaseModel, EmailStr, Field

from app.schemas.password_policy import StrongPassword


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


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
    current_password: str = Field(min_length=1, max_length=128)
    new_password: StrongPassword
