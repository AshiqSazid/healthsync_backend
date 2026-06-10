from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from app.models.enums import UserRole
from app.schemas.common import ORMModel

try:
    import email_validator  # noqa: F401
    from pydantic import EmailStr

    EmailType = EmailStr
except ModuleNotFoundError:
    EmailType = Annotated[str, StringConstraints(min_length=5, max_length=255)]


class UserBase(ORMModel):
    email: EmailType
    username: str = Field(min_length=3, max_length=80)
    role: UserRole = UserRole.USER

    @field_validator("email")
    @classmethod
    def validate_email_fallback(cls, value: str) -> str:
        # If email-validator is installed, EmailStr already handles this.
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("Invalid email address")
        return value


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(ORMModel):
    email: EmailType | None = None
    username: str | None = Field(default=None, min_length=3, max_length=80)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None
    is_verified: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_optional_email_fallback(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("Invalid email address")
        return value


class UserResponse(UserBase):
    id: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
