from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from app.services.shurjopay_client import ShurjoPayClient


class _FakeResponse:
    def __init__(self, payload: Any, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return str(self._payload)


class _FakeHttpxClient:
    def __init__(self, calls: list[dict[str, Any]], responses: list[_FakeResponse], **_: Any) -> None:
        self._calls = calls
        self._responses = responses

    def __enter__(self) -> _FakeHttpxClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> _FakeResponse:
        self._calls.append(
            {
                "url": url,
                "headers": headers or {},
                "json": json or {},
                "data": data or {},
                "files": files or {},
            }
        )
        if not self._responses:
            raise AssertionError(f"No queued fake response for {url}")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def clear_token_cache() -> None:
    ShurjoPayClient._token_cache.clear()
    yield
    ShurjoPayClient._token_cache.clear()


def test_normalize_api_root_handles_host_only_and_api_urls() -> None:
    assert ShurjoPayClient._normalize_api_root("https://engine.shurjopayment.com") == "https://engine.shurjopayment.com/api"
    assert ShurjoPayClient._normalize_api_root("https://engine.shurjopayment.com/api") == "https://engine.shurjopayment.com/api"
    assert ShurjoPayClient._normalize_api_root("https://engine.shurjopayment.com/api/") == "https://engine.shurjopayment.com/api"


def test_authenticate_reuses_cached_token_until_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    responses = [
        _FakeResponse(
            {
                "token": "cached-token-1",
                "store_id": "store-1",
                "token_type": "Bearer",
                "sp_code": 1000,
                "expires_in": 900000,
            }
        ),
        _FakeResponse(
            {
                "token": "cached-token-2",
                "store_id": "store-2",
                "token_type": "Bearer",
                "sp_code": 1000,
                "expires_in": 900000,
            }
        ),
    ]
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: _FakeHttpxClient(calls, responses, **kwargs))

    client = ShurjoPayClient(
        api_root="https://engine.shurjopayment.com",
        username="HEALTHSYNCH",
        password="secret",
    )

    first = client.authenticate()
    second = client.authenticate()

    assert first["token"] == "cached-token-1"
    assert second["token"] == "cached-token-1"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://engine.shurjopayment.com/api/get_token"
    assert calls[0]["json"] == {"username": "HEALTHSYNCH", "password": "secret"}

    ShurjoPayClient._token_cache[client._cache_key()]["expires_at"] = time.time() - 1
    refreshed = client.authenticate()

    assert refreshed["token"] == "cached-token-2"
    assert len(calls) == 2
    assert calls[1]["url"] == "https://engine.shurjopayment.com/api/get_token"


def test_initiate_payment_uses_documented_api_endpoints_and_refreshes_failed_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    responses = [
        _FakeResponse(
            {
                "token": "token-1",
                "store_id": "store-1",
                "token_type": "Bearer",
                "sp_code": 1000,
                "expires_in": 900000,
            }
        ),
        _FakeResponse({"message": "expired"}, status_code=401),
        _FakeResponse(
            {
                "token": "token-2",
                "store_id": "store-2",
                "token_type": "Bearer",
                "sp_code": 1000,
                "expires_in": 900000,
            }
        ),
        _FakeResponse(
            {
                "checkout_url": "https://engine.shurjopayment.com/checkout/live-1",
                "sp_order_id": "SP-LIVE-1",
                "transactionStatus": "Initiated",
            }
        ),
    ]
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: _FakeHttpxClient(calls, responses, **kwargs))

    client = ShurjoPayClient(
        api_root="https://engine.shurjopayment.com/api",
        username="HEALTHSYNCH",
        password="secret",
        order_prefix="HES",
    )

    payload = client.initiate_payment(
        {
            "amount": "10.00",
            "order_id": "HES-ORDER-1",
            "currency": "BDT",
            "customer_name": "Patient User",
            "customer_address": "123 Patient Road",
            "customer_email": "patient@example.com",
            "customer_phone": "01711111111",
            "customer_city": "Dhaka",
            "customer_post_code": "1207",
            "client_ip": "127.0.0.1",
        },
        return_url="https://api.healthsync.example/api/v1/payments/callback",
        cancel_url="https://api.healthsync.example/api/v1/payments/cancel",
    )

    assert payload["checkout_url"] == "https://engine.shurjopayment.com/checkout/live-1"
    assert [call["url"] for call in calls] == [
        "https://engine.shurjopayment.com/api/get_token",
        "https://engine.shurjopayment.com/api/secret-pay",
        "https://engine.shurjopayment.com/api/get_token",
        "https://engine.shurjopayment.com/api/secret-pay",
    ]

    first_secret_pay = calls[1]
    assert first_secret_pay["headers"]["Authorization"] == "Bearer token-1"
    assert "content-type" not in {k.lower(): v for k, v in first_secret_pay["headers"].items()}
    assert first_secret_pay["files"]["prefix"][1] == "HES"
    assert first_secret_pay["files"]["token"][1] == "token-1"
    assert first_secret_pay["files"]["store_id"][1] == "store-1"
    assert first_secret_pay["files"]["return_url"][1] == "https://api.healthsync.example/api/v1/payments/callback"
    assert first_secret_pay["files"]["cancel_url"][1] == "https://api.healthsync.example/api/v1/payments/cancel"

    refreshed_secret_pay = calls[3]
    assert refreshed_secret_pay["headers"]["Authorization"] == "Bearer token-2"
    assert refreshed_secret_pay["files"]["token"][1] == "token-2"
    assert refreshed_secret_pay["files"]["store_id"][1] == "store-2"
