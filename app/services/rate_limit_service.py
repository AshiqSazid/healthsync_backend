from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from fastapi import Request

from app.core.config import settings


logger = logging.getLogger(__name__)


class RateLimitService:
    """Service for rate limiting using Redis or in-memory storage as fallback."""

    def __init__(self) -> None:
        self._redis_client = None
        self._in_memory_store: dict[str, dict[str, Any]] = {}
        self._memory_lock = Lock()
        self._use_redis = settings.REDIS_ENABLED and settings.RATE_LIMIT_ENABLED

        if self._use_redis:
            self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection."""
        try:
            from redis import Redis

            self._redis_client = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            # Test connection
            self._redis_client.ping()
            logger.info("Redis connected for rate limiting")
        except Exception as e:
            logger.warning("Redis connection failed: %s. Falling back to in-memory storage.", e)
            self._use_redis = False
            self._redis_client = None

    def _get_client_ip(self, request: Request) -> str:
        """Extract real client IP from request, handling proxies."""
        # Check for forwarded headers (proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, take the first one
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        cf_connecting_ip = request.headers.get("CF-Connecting-IP")
        if cf_connecting_ip:
            return cf_connecting_ip.strip()

        # Fallback to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    def _get_key(self, identifier: str, endpoint: str | None = None) -> str:
        """Generate Redis key for rate limiting."""
        prefix = f"rate_limit:{endpoint or 'global'}"
        return f"{prefix}:{identifier}"

    def _cleanup_expired_memory_entries(self) -> None:
        """Clean up expired entries from in-memory store."""
        now = datetime.now(timezone.utc).timestamp()
        expired_keys = [
            key
            for key, value in self._in_memory_store.items()
            if value.get("expires_at", 0) < now
        ]
        for key in expired_keys:
            del self._in_memory_store[key]

    def check_rate_limit(
        self,
        identifier: str,
        max_requests: int | None = None,
        window_seconds: int | None = None,
        endpoint: str | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """
        Check if the identifier has exceeded the rate limit.

        Args:
            identifier: Unique identifier (IP, user_id, etc.)
            max_requests: Maximum requests allowed (default from settings)
            window_seconds: Time window in seconds (default from settings)
            endpoint: Optional endpoint name for scoped limits

        Returns:
            Tuple of (is_allowed, info_dict)
        """
        if not settings.RATE_LIMIT_ENABLED:
            return True, {"allowed": True, "reason": "Rate limiting disabled"}

        max_requests = max_requests or settings.RATE_LIMIT_FREE_TIER_REQUESTS
        window_seconds = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS

        key = self._get_key(identifier, endpoint)

        if self._use_redis and self._redis_client:
            return self._check_redis(key, max_requests, window_seconds)
        else:
            return self._check_memory(key, max_requests, window_seconds)

    def _check_redis(
        self, key: str, max_requests: int, window_seconds: int
    ) -> tuple[bool, dict[str, Any]]:
        """Check rate limit using Redis."""
        try:
            current = self._redis_client.get(key)
            count = int(current) if current else 0

            if count >= max_requests:
                ttl = self._redis_client.ttl(key)
                return False, {
                    "allowed": False,
                    "count": count,
                    "limit": max_requests,
                    "remaining": 0,
                    "reset_in_seconds": ttl,
                    "reason": "Rate limit exceeded",
                }

            # Increment count
            pipe = self._redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            results = pipe.execute()
            new_count = results[0]

            return True, {
                "allowed": True,
                "count": new_count,
                "limit": max_requests,
                "remaining": max_requests - new_count,
                "reset_in_seconds": window_seconds,
            }

        except Exception as e:
            logger.warning(
                "Redis rate limit check failed for key %s: %s. Falling back to in-memory limiter.",
                key,
                e,
            )
            allowed, info = self._check_memory(key, max_requests, window_seconds)
            info["fallback_active"] = True
            info["fallback_reason"] = "redis_error"
            return allowed, info

    def _check_memory(
        self, key: str, max_requests: int, window_seconds: int
    ) -> tuple[bool, dict[str, Any]]:
        """Check rate limit using in-memory storage."""
        with self._memory_lock:
            self._cleanup_expired_memory_entries()
            now = datetime.now(timezone.utc).timestamp()

            entry = self._in_memory_store.get(key)
            if entry is None or entry.get("expires_at", 0) < now:
                # Create new entry
                self._in_memory_store[key] = {
                    "count": 1,
                    "expires_at": now + window_seconds,
                }
                return True, {
                    "allowed": True,
                    "count": 1,
                    "limit": max_requests,
                    "remaining": max_requests - 1,
                    "reset_in_seconds": window_seconds,
                }

            count = entry["count"]
            if count >= max_requests:
                reset_in = int(entry["expires_at"] - now)
                return False, {
                    "allowed": False,
                    "count": count,
                    "limit": max_requests,
                    "remaining": 0,
                    "reset_in_seconds": reset_in,
                    "reason": "Rate limit exceeded",
                }

            entry["count"] = count + 1
            return True, {
                "allowed": True,
                "count": count + 1,
                "limit": max_requests,
                "remaining": max_requests - count - 1,
                "reset_in_seconds": int(entry["expires_at"] - now),
            }

    def reset_limit(self, identifier: str, endpoint: str | None = None) -> bool:
        """Reset rate limit for a specific identifier."""
        key = self._get_key(identifier, endpoint)

        if self._use_redis and self._redis_client:
            try:
                self._redis_client.delete(key)
                return True
            except Exception as e:
                logger.warning(
                    "Failed to reset rate limit in Redis for key %s: %s. Falling back to in-memory reset.",
                    key,
                    e,
                )
                with self._memory_lock:
                    self._in_memory_store.pop(key, None)
                return True
        else:
            with self._memory_lock:
                self._in_memory_store.pop(key, None)
            return True

    def get_remaining_requests(
        self,
        identifier: str,
        endpoint: str | None = None,
    ) -> int:
        """Get remaining requests for an identifier."""
        max_requests = settings.RATE_LIMIT_FREE_TIER_REQUESTS

        if self._use_redis and self._redis_client:
            try:
                key = self._get_key(identifier, endpoint)
                current = self._redis_client.get(key)
                count = int(current) if current else 0
                return max(0, max_requests - count)
            except Exception as e:
                logger.warning(
                    "Failed to read remaining requests from Redis for %s: %s. Using in-memory fallback.",
                    key,
                    e,
                )
                return self._get_remaining_requests_from_memory(key, max_requests)
        else:
            key = self._get_key(identifier, endpoint)
            return self._get_remaining_requests_from_memory(key, max_requests)

    def _get_remaining_requests_from_memory(self, key: str, max_requests: int) -> int:
        with self._memory_lock:
            self._cleanup_expired_memory_entries()
            entry = self._in_memory_store.get(key)
            if not entry:
                return max_requests
            count = entry.get("count", 0)
            return max(0, max_requests - count)


# Global instance
_rate_limit_service: RateLimitService | None = None


def get_rate_limit_service() -> RateLimitService:
    """Get or create the rate limit service instance."""
    global _rate_limit_service
    if _rate_limit_service is None:
        _rate_limit_service = RateLimitService()
    return _rate_limit_service
