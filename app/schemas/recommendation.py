from datetime import datetime
from typing import Any

from pydantic import field_validator

from app.ai.medical_prompts import normalize_response_language
from app.schemas.common import ORMModel


class DoctorMatch(ORMModel):
    doctor_id: str
    name: str
    specialization: list[str] = []
    match_score: float
    reasons: list[str] = []
    details: dict = {}


class RecommendationRequest(ORMModel):
    symptoms: list[str]
    prescription_ids: list[str] | None = None
    preferences: dict | None = None
    symptom_checker_session_id: str | None = None
    language: str = "en"

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return normalize_response_language(value)


class RecommendationResponse(ORMModel):
    recommendation_id: str
    doctors: list[DoctorMatch]


class RecommendationRecordResponse(ORMModel):
    id: str
    user_id: str
    symptom_checker_session_id: str | None = None
    prescription_ids: list[str]
    recommended_doctors: list[dict]
    recommendation_criteria: dict
    algorithm_version: str
    created_at: datetime


class ExternalDoctorCandidate(ORMModel):
    doctor_id: str
    name: str = ""
    specialization: list[str] = []
    experience_years: float = 0.0
    average_rating: float = 0.0
    match_score: float = 0.0
    current_reasons: list[str] = []


class ExternalDoctorPreviewRequest(ORMModel):
    symptoms: list[str]
    doctors: list[ExternalDoctorCandidate]
    limit: int = 6
    language: str = "en"

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return normalize_response_language(value)


class ExternalDoctorPreviewResponse(ORMModel):
    previews: dict[str, dict[str, Any]]
    analysis_source: str


class ReportFindingExplanationRequest(ORMModel):
    test_name: str
    observed_value: str | None = None
    reference_range: str | None = None
    status: str = "unknown"
    language: str = "en"
    context: str | None = None

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return normalize_response_language(value)


class ReportFindingExplanationResponse(ORMModel):
    explanation: str
