from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import bcrypt
import jwt
from fastapi import Response
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import settings
from app.models.user import User
from app.utils.helpers import hash_token


class TokenValidationError(Exception):
    pass


class TokenExpiredError(TokenValidationError):
    pass


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    email: str | None
    token_type: str
    jti: str | None
    expires_at: datetime | None


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class OAuthStatePayload:
    next_path: str
    expires_at: datetime | None


class AuthService:
    def __init__(self) -> None:
        self.algorithm = settings.JWT_ALGORITHM

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        if not plain_password or not hashed_password:
            return False
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        except ValueError:
            return False

    @staticmethod
    def hash_stored_token(token: str) -> str:
        return hash_token(token)

    def _encode_token(
        self,
        *,
        user_id: str,
        email: str | None,
        secret: str,
        token_type: str,
        expires_delta: timedelta,
    ) -> str:
        issued_at = self._now()
        expires_at = issued_at + expires_delta
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "user_id": str(user_id),
            "email": email,
            "type": token_type,
            "jti": uuid4().hex,
            "iat": issued_at,
            "exp": expires_at,
        }
        return jwt.encode(payload, secret, algorithm=self.algorithm)

    def create_access_token(self, user: User, expires_delta: timedelta | None = None) -> str:
        return self._encode_token(
            user_id=user.id,
            email=user.email,
            secret=settings.JWT_SECRET,
            token_type="access",
            expires_delta=expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        )

    def create_access_token_for_subject(self, subject: str, expires_delta: timedelta | None = None) -> str:
        return self._encode_token(
            user_id=subject,
            email=None,
            secret=settings.JWT_SECRET,
            token_type="access",
            expires_delta=expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        )

    def create_refresh_token(self, user: User) -> str:
        return self._encode_token(
            user_id=user.id,
            email=user.email,
            secret=settings.JWT_REFRESH_SECRET,
            token_type="refresh",
            expires_delta=timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        )

    def create_reset_token(self, user: User) -> str:
        return self._encode_token(
            user_id=user.id,
            email=user.email,
            secret=settings.JWT_SECRET,
            token_type="reset",
            expires_delta=timedelta(minutes=settings.JWT_RESET_TOKEN_EXPIRE_MINUTES),
        )

    def create_session_code(self, user: User) -> str:
        return self._encode_token(
            user_id=user.id,
            email=user.email,
            secret=settings.JWT_SECRET,
            token_type="session_code",
            expires_delta=timedelta(seconds=120),
        )

    def decode_session_code(self, token: str) -> TokenPayload:
        return self._decode_token(token, secret=settings.JWT_SECRET, expected_type="session_code")

    def create_oauth_state_token(self, *, next_path: str, expires_delta: timedelta | None = None) -> str:
        issued_at = self._now()
        expires_at = issued_at + (
            expires_delta or timedelta(minutes=settings.GOOGLE_OAUTH_STATE_EXPIRE_MINUTES)
        )
        payload: dict[str, Any] = {
            "type": "oauth_state",
            "next": next_path,
            "jti": uuid4().hex,
            "iat": issued_at,
            "exp": expires_at,
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=self.algorithm)

    def build_token_pair(self, user: User) -> TokenPair:
        return TokenPair(
            access_token=self.create_access_token(user),
            refresh_token=self.create_refresh_token(user),
        )

    def _decode_token(self, token: str, *, secret: str, expected_type: str) -> TokenPayload:
        try:
            payload = jwt.decode(token, secret, algorithms=[self.algorithm])
        except ExpiredSignatureError as exc:
            raise TokenExpiredError("Token has expired") from exc
        except InvalidTokenError as exc:
            raise TokenValidationError("Token is invalid") from exc

        token_type = str(payload.get("type") or "")
        if token_type != expected_type:
            raise TokenValidationError("Token type is invalid")

        user_id = str(payload.get("user_id") or payload.get("sub") or "").strip()
        if not user_id:
            raise TokenValidationError("Token subject is missing")

        exp_raw = payload.get("exp")
        expires_at = None
        if isinstance(exp_raw, (int, float)):
            expires_at = datetime.fromtimestamp(exp_raw, tz=timezone.utc)

        email = payload.get("email")
        if email is not None:
            email = str(email)

        return TokenPayload(
            user_id=user_id,
            email=email,
            token_type=token_type,
            jti=str(payload.get("jti")) if payload.get("jti") else None,
            expires_at=expires_at,
        )

    def decode_access_token(self, token: str) -> TokenPayload:
        return self._decode_token(token, secret=settings.JWT_SECRET, expected_type="access")

    def decode_refresh_token(self, token: str) -> TokenPayload:
        return self._decode_token(token, secret=settings.JWT_REFRESH_SECRET, expected_type="refresh")

    def decode_reset_token(self, token: str) -> TokenPayload:
        return self._decode_token(token, secret=settings.JWT_SECRET, expected_type="reset")

    def decode_oauth_state_token(self, token: str) -> OAuthStatePayload:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[self.algorithm])
        except ExpiredSignatureError as exc:
            raise TokenExpiredError("OAuth state has expired") from exc
        except InvalidTokenError as exc:
            raise TokenValidationError("OAuth state is invalid") from exc

        token_type = str(payload.get("type") or "")
        if token_type != "oauth_state":
            raise TokenValidationError("OAuth state type is invalid")

        next_path = str(payload.get("next") or "").strip() or "/"
        exp_raw = payload.get("exp")
        expires_at = None
        if isinstance(exp_raw, (int, float)):
            expires_at = datetime.fromtimestamp(exp_raw, tz=timezone.utc)

        return OAuthStatePayload(next_path=next_path, expires_at=expires_at)

    @staticmethod
    def _is_secure_cookie() -> bool:
        frontend_is_https = settings.FRONTEND_URL.startswith("https://")
        backend_is_https = bool(settings.BACKEND_PUBLIC_URL and settings.BACKEND_PUBLIC_URL.startswith("https://"))
        return frontend_is_https or backend_is_https or settings.ENVIRONMENT == "production"

    @staticmethod
    def _resolved_cookie_domain() -> str | None:
        configured = (settings.JWT_REFRESH_COOKIE_DOMAIN or "").strip()
        if not configured:
            return None

        backend_host = (urlparse(settings.BACKEND_PUBLIC_URL or "").hostname or "").strip().lower()
        if not backend_host:
            return configured

        normalized = configured.lstrip(".").lower()
        if backend_host == normalized or backend_host.endswith(f".{normalized}"):
            return configured
        return None

    def set_refresh_cookie(self, response: Response, refresh_token: str) -> None:
        max_age = int(timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS).total_seconds())
        response.set_cookie(
            key=settings.JWT_REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=self._is_secure_cookie(),
            samesite="none" if self._is_secure_cookie() else "lax",
            max_age=max_age,
            expires=max_age,
            path="/",
            domain=self._resolved_cookie_domain(),
        )

    def clear_refresh_cookie(self, response: Response) -> None:
        response.delete_cookie(
            key=settings.JWT_REFRESH_COOKIE_NAME,
            httponly=True,
            secure=self._is_secure_cookie(),
            samesite="none" if self._is_secure_cookie() else "lax",
            path="/",
            domain=self._resolved_cookie_domain(),
        )


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService()
