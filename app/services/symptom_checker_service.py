from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.medical_prompts import normalize_response_language
from app.models.enums import SessionStatus
from app.models.prescription import Prescription
from app.models.symptom_checker_session import SymptomCheckerSession
from app.services.rag_service import RAGService


class EnhancedSymptomCheckerService:
    def __init__(self) -> None:
        self.rag_service = RAGService()

    async def start_session(
        self,
        db: Session,
        user_id: str,
        symptoms: list[str],
        prescription_ids: list[str] | None = None,
        language: str = "en",
    ) -> SymptomCheckerSession:
        normalized_language = normalize_response_language(language)
        prescriptions = await self._load_prescriptions(db, user_id, prescription_ids)
        medical_context = await self._build_medical_context(prescriptions)
        rag_output = await self.rag_service.start_conversation(
            symptoms=symptoms,
            medical_history=medical_context,
            language=normalized_language,
        )

        session = SymptomCheckerSession(
            user_id=user_id,
            conversation_history=[
                {
                    "role": "system",
                    "message": "সেশন শুরু হয়েছে"
                    if normalized_language == "bn"
                    else "Session started",
                },
                {"role": "assistant", "message": rag_output.get("next_question")},
            ],
            detected_symptoms=symptoms,
            ai_suggestions={
                "guidance": rag_output.get("guidance", []),
                "medical_context": medical_context,
                "language": normalized_language,
            },
            confidence_score=0.6,
            status=SessionStatus.ONGOING,
            prescription_ids=prescription_ids or [],
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    async def answer_session(
        self,
        db: Session,
        session: SymptomCheckerSession,
        answer: str,
        language: str = "en",
    ) -> SymptomCheckerSession:
        normalized_language = normalize_response_language(language)
        history = list(session.conversation_history or [])
        history.append({"role": "user", "message": answer})
        next_question = await self.rag_service.generate_follow_up(
            history,
            answer,
            language=normalized_language,
        )
        history.append({"role": "assistant", "message": next_question})

        session.conversation_history = history
        if len([item for item in history if item.get("role") == "user"]) >= 3:
            session.status = SessionStatus.COMPLETED
            session.confidence_score = 0.8

        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    async def _load_prescriptions(
        self, db: Session, user_id: str, prescription_ids: list[str] | None
    ) -> list[Prescription]:
        if not prescription_ids:
            return []
        return (
            db.query(Prescription)
            .filter(Prescription.user_id == user_id, Prescription.id.in_(prescription_ids))
            .all()
        )

    def save_progression(self, db: Session, session: SymptomCheckerSession, symptom_analysis: dict) -> None:
        """Save symptom progression data from AI analysis into the session."""
        progression = symptom_analysis.get("symptom_progression")
        if progression and isinstance(progression, dict):
            session.symptom_progression = progression
            db.add(session)
            db.commit()
            db.refresh(session)

    def get_previous_session(self, db: Session, user_id: str) -> SymptomCheckerSession | None:
        """Get the most recent completed session for a user (for progression tracking)."""
        return (
            db.query(SymptomCheckerSession)
            .filter(
                SymptomCheckerSession.user_id == user_id,
                SymptomCheckerSession.status == SessionStatus.COMPLETED,
            )
            .order_by(SymptomCheckerSession.created_at.desc())
            .first()
        )

    def get_previous_session_context(self, db: Session, user_id: str) -> dict:
        """Get previous session context for symptom progression comparison."""
        previous = self.get_previous_session(db, user_id)
        if not previous:
            return {
                "previous_symptoms": "Not provided",
                "previous_progression": "Not provided",
                "days_since_last": "Not provided",
            }
        days_since = (datetime.now(timezone.utc) - previous.created_at).days
        return {
            "previous_symptoms": ", ".join(previous.detected_symptoms) if previous.detected_symptoms else "Not provided",
            "previous_progression": str(previous.symptom_progression) if previous.symptom_progression else "Not provided",
            "days_since_last": str(days_since),
        }

    async def _build_medical_context(self, prescriptions: list[Prescription]) -> dict:
        conditions: list[str] = []
        medications: list[str] = []
        for prescription in prescriptions:
            parsed = prescription.parsed_data or {}
            diagnosis = parsed.get("diagnosis")
            if diagnosis:
                conditions.append(diagnosis)
            meds = parsed.get("medications") or []
            for med in meds:
                if med.get("name"):
                    medications.append(med["name"])

        return {
            "chronic_conditions": sorted(set([c.lower() for c in conditions if c])),
            "medications": sorted(set([m.lower() for m in medications if m])),
        }
