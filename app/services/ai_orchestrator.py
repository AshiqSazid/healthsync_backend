from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.prescription import Prescription
from app.services.doctor_recommendation_service import DoctorRecommendationService
from app.services.prescription_analyzer_service import PrescriptionAnalyzerService
from app.services.storage_service import StorageService
from app.services.symptom_checker_service import EnhancedSymptomCheckerService


class HealthcareAIOrchestrator:
    def __init__(self) -> None:
        self._storage_service: StorageService | None = None
        self.prescription_analyzer = PrescriptionAnalyzerService()
        self.symptom_checker = EnhancedSymptomCheckerService()
        self.recommender = DoctorRecommendationService()

    @property
    def storage_service(self) -> StorageService:
        if self._storage_service is None:
            self._storage_service = StorageService()
        return self._storage_service

    async def complete_consultation_flow(
        self,
        db: Session,
        user_id: str,
        prescription_images: list[UploadFile],
        symptoms: list[str],
        preferences: dict | None = None,
        language: str = "en",
    ) -> dict:
        prescription_ids: list[str] = []

        for image in prescription_images:
            url = await self.storage_service.upload_file(image, user_id)
            processing_path, should_cleanup = await self.storage_service.materialize_upload_for_processing(image)
            try:
                analysis = await self.prescription_analyzer.analyze_prescription_image(
                    processing_path,
                    language=language,
                )
            finally:
                await self.storage_service.cleanup_processing_file(processing_path, should_cleanup)

            prescription = Prescription(
                user_id=user_id,
                image_url=url,
                parsed_data=analysis,
                ai_analysis={
                    "analysis": {k: v for k, v in analysis.items() if k != "pipeline"},
                    "pipeline": analysis.get("pipeline", {}),
                },
                confidence_score=analysis.get("confidence_score", 0.0),
            )
            db.add(prescription)
            db.commit()
            db.refresh(prescription)
            prescription_ids.append(prescription.id)

        session = await self.symptom_checker.start_session(
            db,
            user_id,
            symptoms,
            prescription_ids,
            language=language,
        )

        # Get previous session context for symptom progression tracking
        previous_session_context = self.symptom_checker.get_previous_session_context(db, user_id)

        recommendation, doctors = await self.recommender.recommend_doctors(
            db=db,
            user_id=user_id,
            symptoms=symptoms,
            prescription_ids=prescription_ids,
            preferences=preferences,
            symptom_checker_session_id=session.id,
            previous_session_context=previous_session_context,
            language=language,
        )

        # Save symptom progression from the analysis into the session
        symptom_analysis = (recommendation.recommendation_criteria or {}).get("symptom_analysis", {})
        self.symptom_checker.save_progression(db, session, symptom_analysis)

        return {
            "prescription_ids": prescription_ids,
            "symptom_session_id": session.id,
            "recommendation_id": recommendation.id,
            "recommended_doctors": doctors,
        }
