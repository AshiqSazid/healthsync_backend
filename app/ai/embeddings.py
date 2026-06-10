from __future__ import annotations

from hashlib import sha256


class EmbeddingClient:
    def __init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception:
            self.model = None

    def encode(self, text: str) -> list[float]:
        if not text:
            return [0.0] * 32
        if self.model is not None:
            vector = self.model.encode(text)
            return [float(x) for x in vector.tolist()]

        digest = sha256(text.encode("utf-8")).digest()
        return [b / 255 for b in digest]
