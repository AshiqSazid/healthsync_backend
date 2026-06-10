from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VectorDocument:
    id: str
    text: str
    metadata: dict
    embedding: list[float]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: list[VectorDocument] = []

    def add(self, document: VectorDocument) -> None:
        self._items.append(document)

    def similarity_search(self, embedding: list[float], top_k: int = 5) -> list[VectorDocument]:
        def cosine(a: list[float], b: list[float]) -> float:
            if not a or not b:
                return 0.0
            limit = min(len(a), len(b))
            a = a[:limit]
            b = b[:limit]
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(y * y for y in b) ** 0.5
            if na == 0 or nb == 0:
                return 0.0
            return dot / (na * nb)

        ranked = sorted(self._items, key=lambda item: cosine(item.embedding, embedding), reverse=True)
        return ranked[:top_k]
