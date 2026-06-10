from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def candidate_models(primary_model: str, fallback_models: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in [primary_model, *fallback_models]:
        model_name = str(item or "").strip()
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)
        ordered.append(model_name)
    return ordered


def extract_message_text(content: Any) -> str | None:
    if isinstance(content, str):
        text = content.strip()
        return text or None

    if isinstance(content, list):
        text_parts = [
            str(part.get("text") or "").strip()
            for part in content
            if isinstance(part, dict) and str(part.get("text") or "").strip()
        ]
        joined = "\n".join(text_parts).strip()
        return joined or None

    return None


def parse_json_message_content(content: Any) -> dict[str, Any]:
    text = extract_message_text(content)
    if not text:
        return {}

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(default, 1.0))
    if parsed != parsed:  # NaN guard without importing math.
        return max(0.0, min(default, 1.0))
    return max(0.0, min(parsed, 1.0))
