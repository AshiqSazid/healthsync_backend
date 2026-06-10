from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image
import pytest

from app.ai.http_client import get_openai_concurrency_limit
from app.ai.llm_client import LLMClient
from app.ai.vision_client import VisionClient


@pytest.mark.asyncio
async def test_openai_calls_respect_global_concurrency_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ai.llm_client.settings.OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("app.ai.vision_client.settings.OPENAI_API_KEY", "test-key")

    image_path = tmp_path / "scan.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)

    active_requests = 0
    max_active_requests = 0
    counter_lock = asyncio.Lock()

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "{\"confidence_score\": 0.9, \"medications\": [], \"report_findings\": []}"
                        }
                    }
                ]
            }

    class _Client:
        async def post(self, *args, **kwargs):
            nonlocal active_requests, max_active_requests
            async with counter_lock:
                active_requests += 1
                max_active_requests = max(max_active_requests, active_requests)
            await asyncio.sleep(0.05)
            async with counter_lock:
                active_requests -= 1
            return _Response()

    shared_client = _Client()
    monkeypatch.setattr("app.ai.llm_client.get_openai_http_client", lambda: shared_client)
    monkeypatch.setattr("app.ai.vision_client.get_openai_http_client", lambda: shared_client)

    llm_client = LLMClient()
    vision_client = VisionClient()

    llm_tasks = [llm_client.complete_json(f"hello-{i}") for i in range(8)]
    vision_tasks = [vision_client.analyze_image(str(image_path), "extract this") for _ in range(8)]
    results = await asyncio.gather(*llm_tasks, *vision_tasks)

    assert max_active_requests <= get_openai_concurrency_limit()
    assert all(result is not None for result in results[:8])
    assert all(result.get("status") == "vision_api_success" for result in results[8:])
