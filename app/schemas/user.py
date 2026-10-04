from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole
from app.schemas.password_policy import StrongPassword
from app.schemas.person_name import PersonName

# Roles elegibles en el alta pública: ADMIN queda fuera, solo otro admin lo asigna
PublicSignupRole = Literal[UserRole.ATHLETE, UserRole.COACH]


class UserCreate(BaseModel):
    email: EmailStr
    password: StrongPassword
    full_name: PersonName
    role: PublicSignupRole = UserRole.ATHLETE


class UserProfileUpdate(BaseModel):
    # La misma regla que en el registro: si no, se podría saltar editando el perfil
    full_name: PersonName


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserStatusUpdate(BaseModel):
    is_active: bool


class VideoConsentGrant(BaseModel):
    version: int = Field(gt=0)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime
    avatar_url: str | None = None
    video_consent_given_at: datetime | None = None
    video_consent_version: int | None = None
