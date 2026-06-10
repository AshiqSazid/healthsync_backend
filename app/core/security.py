from datetime import timedelta

from app.core.config import settings
from app.services.auth_service import get_auth_service

ALGORITHM = settings.JWT_ALGORITHM


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    auth_service = get_auth_service()
    return auth_service.create_access_token_for_subject(str(subject), expires_delta=expires_delta)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return get_auth_service().verify_password(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return get_auth_service().hash_password(password)
