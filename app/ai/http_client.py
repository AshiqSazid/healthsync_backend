from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import httpx
from typing import TypeVar

from app.core.config import settings

_openai_http_client: httpx.AsyncClient | None = None
_openai_concurrency_limit = settings.OPENAI_MAX_CONCURRENT_REQUESTS
_openai_request_semaphore = asyncio.Semaphore(_openai_concurrency_limit)
_T = TypeVar("_T")


def get_openai_http_client() -> httpx.AsyncClient:
    global _openai_http_client
    if _openai_http_client is None:
        _openai_http_client = httpx.AsyncClient(
            timeout=None,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
        )
    return _openai_http_client


def get_openai_concurrency_limit() -> int:
    return _openai_concurrency_limit


async def with_openai_concurrency_cap(work: Callable[[], Awaitable[_T]]) -> _T:
    async with _openai_request_semaphore:
        return await work()


async def close_openai_http_client() -> None:
    global _openai_http_client
    if _openai_http_client is None:
        return
    await _openai_http_client.aclose()
    _openai_http_client = None
