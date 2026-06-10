from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, require_roles
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.prescription import Prescription
from app.models.user import User
from app.schemas.prescription import PrescriptionResponse
from app.services.prescription_analyzer_service import PrescriptionAnalyzerService
from app.services.storage_service import StorageService

router = APIRouter()


@lru_cache
def get_storage_service() -> StorageService:
    return StorageService()


@lru_cache
def get_prescription_analyzer_service() -> PrescriptionAnalyzerService:
    return PrescriptionAnalyzerService()


def _build_ai_analysis_payload(analysis: dict) -> dict:
    return {
        "analysis": {k: v for k, v in analysis.items() if k != "pipeline"},
        "pipeline": analysis.get("pipeline", {}),
    }


@router.post("/upload", response_model=PrescriptionResponse, status_code=status.HTTP_201_CREATED)
async def upload_prescription(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    analyzer_service: Annotated[
        PrescriptionAnalyzerService, Depends(get_prescription_analyzer_service)
    ],
    file: UploadFile = File(...),
) -> Prescription:
    file_url = await storage_service.upload_file(file, current_user.id)
    processing_path, should_cleanup = await storage_service.materialize_upload_for_processing(file)
    try:
        analysis = await analyzer_service.analyze_prescription_image(processing_path)
    finally:
        await storage_service.cleanup_processing_file(processing_path, should_cleanup)

    ai_analysis = _build_ai_analysis_payload(analysis)

    prescription = Prescription(
        user_id=current_user.id,
        image_url=file_url,
        parsed_data=analysis,
        ai_analysis=ai_analysis,
        confidence_score=analysis.get("confidence_score", 0.0),
    )
    db.add(prescription)
    db.commit()
    db.refresh(prescription)
    return prescription


@router.post("/batch-upload", response_model=list[PrescriptionResponse], status_code=status.HTTP_201_CREATED)
async def batch_upload_prescriptions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    analyzer_service: Annotated[
        PrescriptionAnalyzerService, Depends(get_prescription_analyzer_service)
    ],
    files: list[UploadFile] = File(...),
) -> list[Prescription]:
    saved: list[Prescription] = []
    for file in files:
        file_url = await storage_service.upload_file(file, current_user.id)
        processing_path, should_cleanup = await storage_service.materialize_upload_for_processing(file)
        try:
            analysis = await analyzer_service.analyze_prescription_image(processing_path)
        finally:
            await storage_service.cleanup_processing_file(processing_path, should_cleanup)

        ai_analysis = _build_ai_analysis_payload(analysis)

        prescription = Prescription(
            user_id=current_user.id,
            image_url=file_url,
            parsed_data=analysis,
            ai_analysis=ai_analysis,
            confidence_score=analysis.get("confidence_score", 0.0),
        )
        db.add(prescription)
        db.commit()
        db.refresh(prescription)
        saved.append(prescription)

    return saved


@router.get("/", response_model=list[PrescriptionResponse])
def list_prescriptions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[Prescription]:
    query = db.query(Prescription)
    if current_user.role != UserRole.ADMIN:
        query = query.filter(Prescription.user_id == current_user.id)
    return query.order_by(Prescription.created_at.desc()).all()


@router.get("/{prescription_id}/analysis")
def get_prescription_analysis(
    prescription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    prescription = db.query(Prescription).filter(Prescription.id == prescription_id).first()
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")

    if current_user.role != UserRole.ADMIN and prescription.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return {
        "id": prescription.id,
        "analysis": prescription.ai_analysis,
    }


@router.get("/{prescription_id}", response_model=PrescriptionResponse)
def get_prescription(
    prescription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Prescription:
    prescription = db.query(Prescription).filter(Prescription.id == prescription_id).first()
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")

    if current_user.role != UserRole.ADMIN and prescription.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return prescription


@router.delete("/{prescription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prescription(
    prescription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
) -> None:
    prescription = db.query(Prescription).filter(Prescription.id == prescription_id).first()
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")

    if current_user.role != UserRole.ADMIN and prescription.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    await storage_service.delete_file(prescription.image_url)
    db.delete(prescription)
    db.commit()


@router.put("/{prescription_id}/verify", response_model=PrescriptionResponse)
def verify_prescription(
    prescription_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.DOCTOR, UserRole.ADMIN))],
) -> Prescription:
    prescription = db.query(Prescription).filter(Prescription.id == prescription_id).first()
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")

    prescription.is_verified = True
    if current_user.role == UserRole.DOCTOR and current_user.doctor_profile:
        prescription.verified_by_doctor_id = current_user.doctor_profile.id

    db.add(prescription)
    db.commit()
    db.refresh(prescription)
    return prescription
