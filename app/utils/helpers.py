from __future__ import annotations

import hashlib
import secrets

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.rate_limit_service import RateLimitService


def normalize_email(email: str) -> str:
    return email.strip().lower()


def sanitize_email_for_path(email: str) -> str:
    return normalize_email(email).replace("@", "_at_").replace(".", "_dot_")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_hash(token: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False
    return secrets.compare_digest(hash_token(token), expected_hash)


def build_unique_username(db: Session, *, name: str, email: str) -> str:
    base_value = " ".join(name.split()).strip() or normalize_email(email).split("@", 1)[0] or "user"
    candidate = base_value[:80]
    if len(candidate) < 3:
        candidate = f"{candidate}user"[:80]

    suffix = 1
    while db.query(User.id).filter(User.username == candidate).first() is not None:
        suffix_text = f"-{suffix}"
        candidate = f"{base_value[: max(1, 80 - len(suffix_text))]}{suffix_text}"
        suffix += 1

    return candidate


def enforce_identifier_rate_limit(
    *,
    rate_limit_service: RateLimitService,
    identifier: str,
    endpoint: str,
    max_requests: int,
    window_seconds: int,
    message: str,
) -> None:
    allowed, info = rate_limit_service.check_rate_limit(
        identifier=identifier,
        endpoint=endpoint,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    if allowed:
        return

    reset_after = str(info.get("reset_in_seconds", ""))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=message,
        headers={
            "Retry-After": reset_after,
            "X-RateLimit-Limit": str(info.get("limit", max_requests)),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": reset_after,
        },
    )
