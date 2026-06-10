from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth_service import (
    AuthService,
    TokenExpiredError,
    TokenValidationError,
    get_auth_service,
)
from app.services.rate_limit_service import RateLimitService, get_rate_limit_service

bearer_scheme = HTTPBearer(auto_error=False)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    token: Annotated[str | None, Depends(get_bearer_token)],
) -> User:
    if not token:
        raise _credentials_exception()

    try:
        token_payload = auth_service.decode_access_token(token)
    except (TokenExpiredError, TokenValidationError) as exc:
        raise _credentials_exception() from exc

    user = db.query(User).filter(User.id == token_payload.user_id).first()
    if not user:
        raise _credentials_exception()
    return user


def get_current_user_optional(
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    token: Annotated[str | None, Depends(get_bearer_token)],
) -> User | None:
    if not token:
        return None

    try:
        token_payload = auth_service.decode_access_token(token)
    except (TokenExpiredError, TokenValidationError):
        return None

    user = db.query(User).filter(User.id == token_payload.user_id).first()
    if not user or not user.is_active:
        return None
    return user


def get_current_active_user(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    def checker(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return current_user

    return checker


class RateLimitExceeded(HTTPException):
    """Exception raised when rate limit is exceeded."""

    def __init__(
        self,
        detail: str = "You've reached your free limit. Upgrade to Pro for unlimited access.",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=429, detail=detail, headers=headers)


def check_rate_limit(
    request: Request,
    rate_limit_service: Annotated[RateLimitService, Depends(get_rate_limit_service)],
    max_requests: int | None = None,
    window_seconds: int | None = None,
    endpoint: str | None = None,
    user: User | None = None,
) -> None:
    if user:
        return

    client_ip = rate_limit_service._get_client_ip(request)

    allowed, info = rate_limit_service.check_rate_limit(
        identifier=client_ip,
        max_requests=max_requests,
        window_seconds=window_seconds,
        endpoint=endpoint,
    )

    if not allowed:
        raise RateLimitExceeded(
            detail={
                "message": "You've reached your free limit. Upgrade to Pro for unlimited access.",
                "limit": info.get("limit"),
                "reset_in_seconds": info.get("reset_in_seconds"),
            },
            headers={
                "X-RateLimit-Limit": str(info.get("limit", "")),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(info.get("reset_in_seconds", "")),
                "Retry-After": str(info.get("reset_in_seconds", "")),
            },
        )


def rate_limit_dependency(
    max_requests: int | None = None,
    window_seconds: int | None = None,
    endpoint: str | None = None,
):
    def dependency(
        request: Request,
        rate_limit_service: Annotated[RateLimitService, Depends(get_rate_limit_service)],
        user: Annotated[User | None, Depends(get_current_user_optional)] = None,
    ) -> None:
        if user:
            return

        check_rate_limit(
            request=request,
            max_requests=max_requests,
            window_seconds=window_seconds,
            endpoint=endpoint,
            rate_limit_service=rate_limit_service,
            user=user,
        )

    return dependency


def ip_rate_limit(
    max_requests: int | None = None,
    window_seconds: int | None = None,
    endpoint: str | None = None,
):
    def dependency(
        request: Request,
        rate_limit_service: Annotated[RateLimitService, Depends(get_rate_limit_service)],
    ) -> None:
        check_rate_limit(
            request=request,
            max_requests=max_requests,
            window_seconds=window_seconds,
            endpoint=endpoint,
            rate_limit_service=rate_limit_service,
        )

    return dependency
