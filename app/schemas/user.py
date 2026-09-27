from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole

# Roles elegibles en el alta pública: ADMIN queda fuera, solo otro admin lo asigna
PublicSignupRole = Literal[UserRole.ATHLETE, UserRole.COACH]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)
    role: PublicSignupRole = UserRole.ATHLETE


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime
