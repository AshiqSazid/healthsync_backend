from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, ip_rate_limit
from app.db.session import get_db
from app.models.symptom_checker_session import SymptomCheckerSession
from app.models.user import User
from app.schemas.symptom_checker import (
    SymptomCheckerAnswer,
    SymptomCheckerResult,
    SymptomCheckerSessionResponse,
    SymptomCheckerStart,
)
from app.services.symptom_checker_service import EnhancedSymptomCheckerService

router = APIRouter()
service = EnhancedSymptomCheckerService()


@router.post("/start", response_model=SymptomCheckerSessionResponse)
async def start_symptom_session(
    payload: SymptomCheckerStart,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    _rate_limit: Annotated[None, Depends(ip_rate_limit(max_requests=2, endpoint="symptom_checker_start"))],
) -> SymptomCheckerSession:
    return await service.start_session(
        db,
        current_user.id,
        payload.initial_symptoms,
        payload.prescription_ids,
        payload.language,
    )


@router.post("/{session_id}/answer", response_model=SymptomCheckerSessionResponse)
async def answer_symptom_session(
    session_id: str,
    payload: SymptomCheckerAnswer,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    _rate_limit: Annotated[None, Depends(ip_rate_limit(max_requests=10, endpoint="symptom_checker_answer"))],
) -> SymptomCheckerSession:
    session = db.query(SymptomCheckerSession).filter(SymptomCheckerSession.id == session_id).first()
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return await service.answer_session(db, session, payload.answer, payload.language)


@router.get("/{session_id}", response_model=SymptomCheckerSessionResponse)
def get_symptom_session(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> SymptomCheckerSession:
    session = db.query(SymptomCheckerSession).filter(SymptomCheckerSession.id == session_id).first()
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/{session_id}/results", response_model=SymptomCheckerResult)
def get_symptom_results(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> SymptomCheckerResult:
    session = db.query(SymptomCheckerSession).filter(SymptomCheckerSession.id == session_id).first()
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    history = session.conversation_history or []
    next_question = None
    if history and history[-1].get("role") == "assistant":
        next_question = history[-1].get("message")

    return SymptomCheckerResult(
        session_id=session.id,
        status=session.status,
        summary={
            "detected_symptoms": session.detected_symptoms,
            "confidence_score": session.confidence_score,
            "suggestions": session.ai_suggestions,
        },
        next_question=next_question,
        recommendation_hint=(session.ai_suggestions or {}).get("guidance", []),
    )


@router.delete("/{session_id}", status_code=204)
def delete_symptom_session(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    session = db.query(SymptomCheckerSession).filter(SymptomCheckerSession.id == session_id).first()
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    db.delete(session)
    db.commit()
