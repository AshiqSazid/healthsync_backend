from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models.assessment_document import AssessmentDocument
from app.models.assessment_document_payload import AssessmentDocumentPayload
from app.models.booking import Booking
from app.models.diagnostic import Diagnostic
from app.models.doctor import Doctor
from app.models.enums import BookingStatus, UserRole
from app.models.hospital import Hospital
from app.models.profile import Profile
from app.models.user import User
from app.schemas.assessment_document import (
    AssessmentDocumentCreate,
    AssessmentDocumentResponse,
    AssessmentDocumentUpdate,
)
from app.schemas.dashboard import (
    AdminDashboardCounts,
    AdminDashboardOverview,
    DashboardBookingSummary,
    DashboardContextResponse,
    DashboardDiagnosticSummary,
    DashboardDoctorSummary,
    DashboardHospitalSummary,
    DashboardProfileSummary,
    DashboardUserSummary,
    DoctorDashboardCounts,
    DoctorDashboardOverview,
    UserDashboardCounts,
    UserDashboardOverview,
)

router = APIRouter()


def _build_user_summary(user: User) -> DashboardUserSummary:
    return DashboardUserSummary(
        id=user.id,
        name=user.name,
        email=user.email,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


def _build_doctor_summary(doctor: Doctor) -> DashboardDoctorSummary:
    display_name = doctor.user.name if doctor.user and doctor.user.name else doctor.display_name
    return DashboardDoctorSummary(
        id=doctor.id,
        user_id=doctor.user_id,
        display_name=display_name,
        email=doctor.user.email if doctor.user else None,
        license_number=doctor.license_number,
        specialization=list(doctor.specialization or []),
        experience_years=doctor.experience_years or 0,
        consultation_fee=doctor.consultation_fee,
        hospital_id=doctor.hospital_id,
        hospital_name=doctor.hospital.name if doctor.hospital else None,
        average_rating=doctor.average_rating or 0.0,
        created_at=doctor.created_at,
    )


def _build_hospital_summary(hospital: Hospital | None) -> DashboardHospitalSummary | None:
    if hospital is None:
        return None
    return DashboardHospitalSummary(
        id=hospital.id,
        name=hospital.name,
        address=hospital.address,
        city=hospital.city,
        country=hospital.country,
        phone=hospital.phone,
        email=hospital.email,
    )


def _build_booking_summary(booking: Booking) -> DashboardBookingSummary:
    patient_name = booking.user.name if booking.user else None
    doctor_name = booking.provider_name or None
    if booking.doctor and booking.doctor.user:
        doctor_name = booking.doctor.user.name or booking.doctor.display_name
    elif booking.doctor:
        doctor_name = booking.doctor.display_name

    return DashboardBookingSummary(
        id=booking.id,
        user_id=booking.user_id,
        doctor_id=booking.doctor_id,
        hospital_id=booking.hospital_id,
        patient_name=patient_name,
        doctor_name=doctor_name,
        hospital_name=booking.hospital.name if booking.hospital else booking.location_name,
        linked_assessment_id=booking.linked_assessment_id,
        provider_name=booking.provider_name or doctor_name,
        location_name=booking.location_name or (booking.hospital.name if booking.hospital else None),
        appointment_date=booking.appointment_date,
        appointment_time=booking.appointment_time,
        status=booking.status,
        booking_type=booking.booking_type,
        symptoms_summary=booking.symptoms_summary,
        created_at=booking.created_at,
    )


def _build_profile_summary(profile: Profile | None) -> DashboardProfileSummary | None:
    if profile is None:
        return None
    return DashboardProfileSummary(
        id=profile.id,
        user_id=profile.user_id,
        full_name=profile.full_name,
        phone=profile.phone,
        city=profile.city,
        country=profile.country,
        blood_group=profile.blood_group,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _build_diagnostic_summary(diagnostic: Diagnostic) -> DashboardDiagnosticSummary:
    doctor_name = None
    if diagnostic.doctor and diagnostic.doctor.user:
        doctor_name = diagnostic.doctor.user.name or diagnostic.doctor.display_name
    elif diagnostic.doctor:
        doctor_name = diagnostic.doctor.display_name

    return DashboardDiagnosticSummary(
        id=diagnostic.id,
        user_id=diagnostic.user_id,
        doctor_id=diagnostic.doctor_id,
        doctor_name=doctor_name,
        diagnosis=diagnostic.diagnosis,
        follow_up_date=diagnostic.follow_up_date,
        created_at=diagnostic.created_at,
    )


def _estimate_document_size_bytes(document: AssessmentDocument) -> int:
    payload_source = document.payload
    payload = {
        "intake_payload": (payload_source.intake_payload if payload_source else document.intake_payload) or {},
        "ai_output": (payload_source.ai_output if payload_source else document.ai_output) or {},
        "conversation_log": (payload_source.conversation_log if payload_source else document.conversation_log) or [],
    }
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def _build_assessment_summary(document: AssessmentDocument) -> str | None:
    payload_source = document.payload
    intake_payload = (payload_source.intake_payload if payload_source else document.intake_payload) or {}
    ai_output = (payload_source.ai_output if payload_source else document.ai_output) or {}
    symptom_analysis = ai_output.get("symptom_analysis") or {}
    patient_profile = ai_output.get("patient_profile") or {}
    symptoms = intake_payload.get("symptoms") or intake_payload.get("symptoms_payload") or []
    recommended_specializations = (
        symptom_analysis.get("recommended_specializations")
        or patient_profile.get("recommended_specializations")
        or []
    )
    urgency = symptom_analysis.get("urgency") or patient_profile.get("urgency")

    parts: list[str] = []
    if document.symptom_name:
        parts.append(str(document.symptom_name))
    elif symptoms:
        normalized_symptoms = [str(item).strip() for item in symptoms if str(item).strip()]
        if normalized_symptoms:
            parts.append(", ".join(normalized_symptoms[:2]))
    if urgency:
        parts.append(f"Urgency: {str(urgency).title()}")
    if recommended_specializations:
        parts.append(f"Suggested: {str(recommended_specializations[0])}")

    if parts:
        return " | ".join(parts)

    return "Assessment draft saved. AI summary will appear here after analysis completes."


def _build_assessment_document_response(document: AssessmentDocument) -> AssessmentDocumentResponse:
    payload_source = document.payload
    return AssessmentDocumentResponse(
        id=document.id,
        user_id=document.user_id,
        session_id=document.session_id,
        title=document.title,
        symptom_name=document.symptom_name,
        source_route=document.source_route,
        intake_payload=(payload_source.intake_payload if payload_source else document.intake_payload) or {},
        ai_output=(payload_source.ai_output if payload_source else document.ai_output) or {},
        conversation_log=(payload_source.conversation_log if payload_source else document.conversation_log) or [],
        status=document.status,
        size_bytes=_estimate_document_size_bytes(document),
        summary=_build_assessment_summary(document),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _build_admin_overview(db: Session) -> AdminDashboardOverview:
    recent_users = db.query(User).order_by(User.created_at.desc()).limit(5).all()
    recent_doctors = (
        db.query(Doctor)
        .options(joinedload(Doctor.user), joinedload(Doctor.hospital))
        .order_by(Doctor.created_at.desc())
        .limit(5)
        .all()
    )
    recent_bookings = (
        db.query(Booking)
        .options(
            joinedload(Booking.user),
            joinedload(Booking.doctor).joinedload(Doctor.user),
            joinedload(Booking.hospital),
        )
        .order_by(Booking.created_at.desc())
        .limit(5)
        .all()
    )

    counts = AdminDashboardCounts(
        total_users=db.query(User).count(),
        total_doctors=db.query(Doctor).count(),
        total_hospitals=db.query(Hospital).count(),
        total_bookings=db.query(Booking).count(),
        pending_bookings=db.query(Booking).filter(Booking.status == BookingStatus.PENDING).count(),
        confirmed_bookings=db.query(Booking).filter(Booking.status == BookingStatus.CONFIRMED).count(),
        completed_bookings=db.query(Booking).filter(Booking.status == BookingStatus.COMPLETED).count(),
        cancelled_bookings=db.query(Booking).filter(Booking.status == BookingStatus.CANCELLED).count(),
    )

    return AdminDashboardOverview(
        counts=counts,
        recent_users=[_build_user_summary(user) for user in recent_users],
        recent_doctors=[_build_doctor_summary(doctor) for doctor in recent_doctors],
        recent_bookings=[_build_booking_summary(booking) for booking in recent_bookings],
    )


def _build_doctor_overview(db: Session, current_user: User) -> DoctorDashboardOverview:
    doctor = (
        db.query(Doctor)
        .options(joinedload(Doctor.user), joinedload(Doctor.hospital))
        .filter(Doctor.user_id == current_user.id)
        .first()
    )
    if doctor is None:
        return DoctorDashboardOverview()

    today = datetime.now(timezone.utc).date()
    booking_query = db.query(Booking).filter(Booking.doctor_id == doctor.id)
    booking_feed_query = (
        db.query(Booking)
        .options(
            joinedload(Booking.user),
            joinedload(Booking.doctor).joinedload(Doctor.user),
            joinedload(Booking.hospital),
        )
        .filter(Booking.doctor_id == doctor.id)
    )

    booking_counts = DoctorDashboardCounts(
        total_bookings=booking_query.count(),
        pending_bookings=booking_query.filter(Booking.status == BookingStatus.PENDING).count(),
        confirmed_bookings=booking_query.filter(Booking.status == BookingStatus.CONFIRMED).count(),
        completed_bookings=booking_query.filter(Booking.status == BookingStatus.COMPLETED).count(),
        cancelled_bookings=booking_query.filter(Booking.status == BookingStatus.CANCELLED).count(),
        today_bookings=booking_query.filter(Booking.appointment_date == today).count(),
    )

    upcoming_bookings = (
        booking_feed_query
        .filter(
            Booking.appointment_date >= today,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
        .order_by(Booking.appointment_date.asc(), Booking.appointment_time.asc())
        .limit(5)
        .all()
    )
    recent_bookings = booking_feed_query.order_by(Booking.created_at.desc()).limit(5).all()

    return DoctorDashboardOverview(
        doctor_profile=_build_doctor_summary(doctor),
        hospital=_build_hospital_summary(doctor.hospital),
        booking_counts=booking_counts,
        upcoming_bookings=[_build_booking_summary(booking) for booking in upcoming_bookings],
        recent_bookings=[_build_booking_summary(booking) for booking in recent_bookings],
    )


def _build_user_overview(db: Session, current_user: User) -> UserDashboardOverview:
    today = datetime.now(timezone.utc).date()
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    booking_query = db.query(Booking).filter(Booking.user_id == current_user.id)
    booking_feed_query = (
        db.query(Booking)
        .options(
            joinedload(Booking.user),
            joinedload(Booking.doctor).joinedload(Doctor.user),
            joinedload(Booking.hospital),
        )
        .filter(Booking.user_id == current_user.id)
    )
    diagnostic_feed = (
        db.query(Diagnostic)
        .options(joinedload(Diagnostic.doctor).joinedload(Doctor.user))
        .filter(Diagnostic.user_id == current_user.id)
        .order_by(Diagnostic.created_at.desc())
        .limit(5)
        .all()
    )

    booking_counts = UserDashboardCounts(
        total_bookings=booking_query.count(),
        pending_bookings=booking_query.filter(Booking.status == BookingStatus.PENDING).count(),
        confirmed_bookings=booking_query.filter(Booking.status == BookingStatus.CONFIRMED).count(),
        completed_bookings=booking_query.filter(Booking.status == BookingStatus.COMPLETED).count(),
        cancelled_bookings=booking_query.filter(Booking.status == BookingStatus.CANCELLED).count(),
        total_diagnostics=db.query(Diagnostic).filter(Diagnostic.user_id == current_user.id).count(),
    )

    upcoming_bookings = (
        booking_feed_query
        .filter(
            Booking.appointment_date >= today,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
        .order_by(Booking.appointment_date.asc(), Booking.appointment_time.asc())
        .limit(5)
        .all()
    )
    recent_bookings = booking_feed_query.order_by(Booking.created_at.desc()).limit(5).all()

    return UserDashboardOverview(
        profile=_build_profile_summary(profile),
        has_profile=profile is not None,
        booking_counts=booking_counts,
        upcoming_bookings=[_build_booking_summary(booking) for booking in upcoming_bookings],
        recent_bookings=[_build_booking_summary(booking) for booking in recent_bookings],
        recent_diagnostics=[_build_diagnostic_summary(diagnostic) for diagnostic in diagnostic_feed],
    )


def _build_dashboard_context_response(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DashboardContextResponse:
    payload: dict[str, object] = {
        "user": _build_user_summary(current_user),
        "role": current_user.role,
        "available_interfaces": [current_user.role],
    }

    if current_user.role == UserRole.ADMIN:
        payload["admin"] = _build_admin_overview(db)
    elif current_user.role == UserRole.DOCTOR:
        payload["doctor"] = _build_doctor_overview(db, current_user)
    else:
        payload["user_dashboard"] = _build_user_overview(db, current_user)

    return DashboardContextResponse(**payload)


@router.get("/context", response_model=DashboardContextResponse)
def read_dashboard_context(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DashboardContextResponse:
    return _build_dashboard_context_response(db=db, current_user=current_user)


@router.get("/me", response_model=DashboardContextResponse, include_in_schema=False)
def read_dashboard_context_legacy(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DashboardContextResponse:
    return _build_dashboard_context_response(db=db, current_user=current_user)


@router.get("/documents", response_model=list[AssessmentDocumentResponse])
def list_dashboard_documents(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[AssessmentDocumentResponse]:
    documents = (
        db.query(AssessmentDocument)
        .filter(AssessmentDocument.user_id == current_user.id)
        .order_by(AssessmentDocument.updated_at.desc(), AssessmentDocument.created_at.desc())
        .all()
    )
    return [_build_assessment_document_response(document) for document in documents]


@router.post("/documents", response_model=AssessmentDocumentResponse, status_code=201)
def create_dashboard_document(
    payload: AssessmentDocumentCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AssessmentDocumentResponse:
    document = (
        db.query(AssessmentDocument)
        .filter(
            AssessmentDocument.user_id == current_user.id,
            AssessmentDocument.session_id == payload.session_id,
        )
        .first()
    )
    if document is None:
        document = AssessmentDocument(user_id=current_user.id, **payload.model_dump())
    else:
        for field, value in payload.model_dump().items():
            setattr(document, field, value)
    payload_row = document.payload or AssessmentDocumentPayload(assessment_document=document)
    payload_row.intake_payload = document.intake_payload or {}
    payload_row.ai_output = document.ai_output or {}
    payload_row.conversation_log = document.conversation_log or []
    db.add(payload_row)

    db.add(document)
    db.commit()
    db.refresh(document)
    return _build_assessment_document_response(document)


@router.patch("/documents/{document_id}", response_model=AssessmentDocumentResponse)
def update_dashboard_document(
    document_id: str,
    payload: AssessmentDocumentUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AssessmentDocumentResponse:
    document = (
        db.query(AssessmentDocument)
        .filter(
            AssessmentDocument.id == document_id,
            AssessmentDocument.user_id == current_user.id,
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(document, field, value)
    payload_row = document.payload or AssessmentDocumentPayload(assessment_document=document)
    payload_row.intake_payload = document.intake_payload or {}
    payload_row.ai_output = document.ai_output or {}
    payload_row.conversation_log = document.conversation_log or []
    db.add(payload_row)

    db.add(document)
    db.commit()
    db.refresh(document)
    return _build_assessment_document_response(document)


@router.delete("/documents/{document_id}", status_code=204)
def delete_dashboard_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    document = (
        db.query(AssessmentDocument)
        .filter(
            AssessmentDocument.id == document_id,
            AssessmentDocument.user_id == current_user.id,
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(document)
    db.commit()
