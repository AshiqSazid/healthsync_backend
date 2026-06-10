from functools import lru_cache
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.ai.medical_prompts import get_medical_disclaimer, normalize_response_language
from app.api.deps import get_current_active_user, ip_rate_limit
from app.db.session import get_db
from app.models.user import User
from app.services.ai_orchestrator import HealthcareAIOrchestrator

router = APIRouter()


@lru_cache
def get_ai_orchestrator() -> HealthcareAIOrchestrator:
    return HealthcareAIOrchestrator()


@router.post("/complete-consultation-flow")
async def complete_consultation_flow(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    orchestrator: Annotated[HealthcareAIOrchestrator, Depends(get_ai_orchestrator)],
    _rate_limit: Annotated[None, Depends(ip_rate_limit(max_requests=2, endpoint="ai_consultation"))],
    prescription_images: list[UploadFile] = File(default=[]),
    symptoms: str = Form(...),
    preferences: str | None = Form(default=None),
    language: str = Form(default="en"),
) -> dict:
    """Complete a full consultation flow with prescription analysis and doctor recommendations.

    This endpoint analyzes prescription images, assesses symptoms, and recommends doctors.
    All AI-generated analysis includes appropriate medical disclaimers.
    """
    symptom_list = [item.strip() for item in symptoms.split(",") if item.strip()]
    preference_obj = json.loads(preferences) if preferences else None
    normalized_language = normalize_response_language(language)

    result = await orchestrator.complete_consultation_flow(
        db=db,
        user_id=current_user.id,
        prescription_images=prescription_images,
        symptoms=symptom_list,
        preferences=preference_obj,
        language=normalized_language,
    )

    # Add medical disclaimer to all responses
    result["disclaimer"] = get_medical_disclaimer(normalized_language)
    result["analysis_source"] = "ai_assisted"

    return result
