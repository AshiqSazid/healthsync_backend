import pytest

from app.ai.llm_client import LLMClient


@pytest.mark.asyncio
async def test_llm_client_does_not_pass_per_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ai.llm_client.settings.OPENAI_API_KEY", "test-key")

    captured_kwargs: dict = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "{\"ok\": true}"
                        }
                    }
                ]
            }

    class _Client:
        async def post(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            return _Response()

    monkeypatch.setattr("app.ai.llm_client.get_openai_http_client", lambda: _Client())

    parsed = await LLMClient().complete_json("hello")

    assert parsed == {"ok": True}
    assert "timeout" not in captured_kwargs
