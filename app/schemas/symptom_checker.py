from datetime import datetime

from pydantic import field_validator

from app.ai.medical_prompts import normalize_response_language
from app.models.enums import SessionStatus
from app.schemas.common import ORMModel


class SymptomCheckerStart(ORMModel):
    initial_symptoms: list[str]
    prescription_ids: list[str] | None = None
    medical_history_consent: bool = False
    language: str = "en"

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return normalize_response_language(value)


class SymptomCheckerAnswer(ORMModel):
    answer: str
    language: str = "en"

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return normalize_response_language(value)


class SymptomCheckerSessionResponse(ORMModel):
    id: str
    user_id: str
    conversation_history: list[dict]
    detected_symptoms: list[str]
    ai_suggestions: dict
    confidence_score: float
    status: SessionStatus
    prescription_ids: list[str]
    created_at: datetime
    updated_at: datetime


class SymptomCheckerResult(ORMModel):
    session_id: str
    status: SessionStatus
    summary: dict
    next_question: str | None = None
    recommendation_hint: list[str] = []
