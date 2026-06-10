from __future__ import annotations

import re
from datetime import datetime

from pydantic import EmailStr, Field, field_validator, model_validator

from app.models.enums import UserRole
from app.schemas.common import ORMModel
from app.utils.helpers import normalize_email

PASSWORD_COMPLEXITY_PATTERN = re.compile(r"^(?=.*[A-Z])(?=.*\d).{8,128}$")


def _validate_password_complexity(value: str) -> str:
    if not PASSWORD_COMPLEXITY_PATTERN.match(value):
        raise ValueError("Password must be at least 8 characters and include 1 uppercase letter and 1 number")
    return value


class SignupRequest(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            raise ValueError("Name is required")
        return cleaned

    @field_validator("email")
    @classmethod
    def normalize_signup_email(cls, value: EmailStr) -> str:
        return normalize_email(str(value))

    @field_validator("phone")
    @classmethod
    def normalize_signup_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(str(value).split()).strip()
        return cleaned or None

    @field_validator("password")
    @classmethod
    def validate_signup_password(cls, value: str) -> str:
        return _validate_password_complexity(value)


class LoginRequest(ORMModel):
    email: EmailStr | None = None
    identifier: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, value: EmailStr | None) -> str | None:
        if value is None:
            return None
        return normalize_email(str(value))

    @field_validator("identifier")
    @classmethod
    def normalize_login_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return normalize_email(cleaned) if "@" in cleaned else cleaned

    @field_validator("username")
    @classmethod
    def normalize_login_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_login_identifier(self) -> "LoginRequest":
        if self.identifier is None and self.username is not None:
            self.identifier = self.username
        if self.email is None and self.identifier is None:
            raise ValueError("Email or identifier is required")
        return self


class ForgotPasswordRequest(ORMModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_forgot_password_email(cls, value: EmailStr) -> str:
        return normalize_email(str(value))


class ResetPasswordRequest(ORMModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_reset_password(cls, value: str) -> str:
        return _validate_password_complexity(value)


class RefreshTokenRequest(ORMModel):
    refresh_token: str | None = None


class SessionCodeExchangeRequest(ORMModel):
    session_code: str = Field(min_length=1)


class GoogleAuthorizationUrlResponse(ORMModel):
    authorization_url: str


class AuthUserResponse(ORMModel):
    id: str
    name: str
    email: EmailStr
    username: str
    role: UserRole
    doctor_profile_id: str | None = None


class AuthResponse(ORMModel):
    access_token: str
    refresh_token: str
    user: AuthUserResponse


class RefreshTokenResponse(ORMModel):
    access_token: str
    refresh_token: str


class MessageResponse(ORMModel):
    message: str


class MeResponse(AuthUserResponse):
    created_at: datetime
    is_active: bool
    is_verified: bool
