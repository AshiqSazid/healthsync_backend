from __future__ import annotations

import logging

from app.services.rate_limit_service import RateLimitService


class _BrokenRedisClient:
    def get(self, key: str):
        raise TimeoutError(f"Redis unavailable for {key}")


def test_rate_limit_falls_back_to_memory_when_redis_fails(
    caplog,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.services.rate_limit_service.settings.RATE_LIMIT_ENABLED", True, raising=False)
    service = RateLimitService()
    service._use_redis = True
    service._redis_client = _BrokenRedisClient()

    identifier = "203.0.113.10"
    endpoint = "public_suggest_doctors"

    with caplog.at_level(logging.WARNING):
        outcomes = [
            service.check_rate_limit(
                identifier=identifier,
                max_requests=30,
                window_seconds=60,
                endpoint=endpoint,
            )
            for _ in range(50)
        ]

    allowed_results = [allowed for allowed, _info in outcomes]
    blocked_results = [not allowed for allowed, _info in outcomes]

    assert allowed_results.count(True) == 30
    assert blocked_results.count(True) == 20

    first_blocked_info = outcomes[30][1]
    assert first_blocked_info["allowed"] is False
    assert first_blocked_info["limit"] == 30
    assert first_blocked_info["fallback_active"] is True
    assert first_blocked_info["fallback_reason"] == "redis_error"

    assert "Falling back to in-memory limiter." in caplog.text
