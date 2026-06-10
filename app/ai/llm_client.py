from __future__ import annotations

import json
import logging
import time

import httpx

from app.ai.http_client import get_openai_http_client, with_openai_concurrency_cap
from app.ai.medical_prompts import get_system_prompt, localize_system_prompt
from app.ai.openai_response_utils import candidate_models, extract_message_text, parse_json_message_content
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Enhanced LLM client with improved medical system prompts."""

    JSON_TEMPERATURE = 0.2
    TEXT_TEMPERATURE = 0.3

    def __init__(self) -> None:
        self.api_key = settings.OPENAI_API_KEY
        self.api_base = settings.OPENAI_API_BASE.rstrip("/")
        self.model = settings.OPENAI_TEXT_MODEL
        self.fallback_models = settings.OPENAI_TEXT_FALLBACK_MODELS

    async def complete(self, prompt: str, language: str = "en") -> str:
        """Complete a prompt with the enhanced medical system prompt."""
        messages = [
            {
                "role": "system",
                "content": get_system_prompt(language=language),
            },
            {"role": "user", "content": prompt},
        ]
        response = await self._chat(messages=messages, json_mode=False)
        if not response:
            return f"LLM unavailable (no API key or request failed). Prompt summary: {prompt[:200]}"
        return response

    async def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        language: str = "en",
    ) -> dict | None:
        """Complete a prompt expecting JSON response with enhanced medical system prompt."""
        messages = [
            {
                "role": "system",
                "content": (
                    localize_system_prompt(system_prompt, language)
                    if system_prompt
                    else get_system_prompt(language=language)
                ),
            },
            {"role": "user", "content": prompt},
        ]
        response = await self._chat(messages=messages, json_mode=True)
        if not response:
            return None

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            parsed = parse_json_message_content(response)
            return parsed or None

    async def _chat(self, messages: list[dict], json_mode: bool) -> str | None:
        if not self.api_key:
            logger.warning("OPENAI_API_KEY is not set - LLM calls will fail")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for model_name in candidate_models(self.model, self.fallback_models):
            payload: dict = {
                "model": model_name,
                "messages": messages,
                "temperature": self.JSON_TEMPERATURE if json_mode else self.TEXT_TEMPERATURE,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            started_at = time.monotonic()
            try:
                async def send_request() -> httpx.Response:
                    return await get_openai_http_client().post(
                        f"{self.api_base}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                response = await with_openai_concurrency_cap(send_request)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if self._is_model_not_found_error(e.response):
                    logger.warning("OpenAI text model unavailable: %s. Trying fallback if available.", model_name)
                    continue
                logger.error("OpenAI API HTTP error for model %s: %s - %s", model_name, e.response.status_code, e.response.text)
                return None
            except httpx.RequestError as e:
                logger.error("OpenAI API request error for model %s: %s", model_name, e)
                return None
            except Exception as e:
                logger.error("OpenAI API unexpected error for model %s: %s", model_name, e)
                return None

            data = response.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
            logger.info(
                "OpenAI text request completed model=%s json_mode=%s duration_ms=%d",
                model_name,
                json_mode,
                int((time.monotonic() - started_at) * 1000),
            )
            return extract_message_text(content)

        logger.error("No usable OpenAI text model is available from the configured primary/fallback list.")
        return None

    @staticmethod
    def _is_model_not_found_error(response: httpx.Response) -> bool:
        if response.status_code != 404:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return False
        return str(error.get("code") or "").strip() == "model_not_found"
