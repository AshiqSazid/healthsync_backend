import pytest

from app.ai.vector_store import VectorDocument
from app.services.rag_service import RAGService


def _contains_bangla(text: str) -> bool:
    return any("\u0980" <= char <= "\u09ff" for char in str(text or ""))


@pytest.mark.asyncio
async def test_start_conversation_localizes_guidance_and_context_to_bangla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RAGService()
    monkeypatch.setattr(service.embedding_client, "encode", lambda text: [0.0] * 32)
    monkeypatch.setattr(
        service.vector_store,
        "similarity_search",
        lambda embedding, top_k=3: [
            VectorDocument(
                id="cardiac-chest-pain",
                text="Chest pain guidance",
                metadata={"source": "seed"},
                embedding=[0.0] * 32,
            )
        ],
    )

    result = await service.start_conversation(
        symptoms=["chest pain"],
        medical_history={"chronic_conditions": ["diabetes"]},
        language="bn",
    )

    assert result["guidance"]
    assert _contains_bangla(result["guidance"][0])
    assert any("প্রেসক্রিপশন ইতিহাস" in item for item in result["guidance"])
    assert _contains_bangla(result["next_question"])
