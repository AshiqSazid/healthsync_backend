import logging
import re
from datetime import date, datetime, time, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Body, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_active_user, require_roles, ip_rate_limit
from app.db.session import get_db
from app.models.booking import Booking
from app.models.doctor import Doctor
from app.models.enums import BookingStatus, BookingType, UserRole
from app.models.profile import Profile
from app.models.user import User
from app.schemas.booking import BookingCreate, BookingFromRecommendation, BookingResponse, BookingUpdate
from app.services.booking_service import BookingService

logger = logging.getLogger(__name__)

router = APIRouter()
service = BookingService()


class RescheduleBookingPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    appointment_date: date | None = Field(default=None, alias="appointmentDate")
    appointment_time: time | None = Field(default=None, alias="appointmentTime")
    provider_name: str | None = Field(default=None, alias="providerName")
    provider_external_id: str | None = Field(default=None, alias="providerExternalId")
    location_name: str | None = Field(default=None, alias="locationName")
    location_address: str | None = Field(default=None, alias="locationAddress")
    symptoms_summary: str | None = Field(default=None, alias="symptomsSummary")
    prescription_ids: list[str] | None = Field(default=None, alias="prescriptionIds")

    @field_validator("appointment_time", mode="before")
    @classmethod
    def normalize_short_time(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            if re.fullmatch(r"\d{2}:\d{2}", cleaned):
                return f"{cleaned}:00"
        return value


@router.post("/from-recommendation", response_model=BookingResponse)
async def create_booking_from_recommendation(
    payload: BookingFromRecommendation,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Booking:
    return await service.create_from_recommendation(db, current_user.id, payload)


@router.post("/", response_model=BookingResponse)
async def create_booking(
    payload: BookingCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    idempotency_key: Annotated[str | None, Header(alias="X-Idempotency-Key")] = None,
) -> Booking:
    if idempotency_key and not payload.client_request_id:
        payload.client_request_id = idempotency_key.strip() or None
    return await service.create_manual(db, current_user.id, payload)


@router.get("/", response_model=list[BookingResponse])
def list_bookings(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[Booking]:
    query = db.query(Booking).options(
        joinedload(Booking.user).joinedload(User.profile),
        joinedload(Booking.doctor).joinedload(Doctor.user),
        joinedload(Booking.hospital),
    )
    if current_user.role == UserRole.USER:
        query = query.filter(Booking.user_id == current_user.id)
    elif current_user.role == UserRole.DOCTOR and current_user.doctor_profile:
        query = query.filter(Booking.doctor_id == current_user.doctor_profile.id)

    return query.order_by(Booking.created_at.desc()).all()


@router.get("/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Booking:
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.user).joinedload(User.profile),
            joinedload(Booking.doctor).joinedload(Doctor.user),
            joinedload(Booking.hospital),
        )
        .filter(Booking.id == booking_id)
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if current_user.role == UserRole.USER and booking.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    if current_user.role == UserRole.DOCTOR and current_user.doctor_profile and booking.doctor_id != current_user.doctor_profile.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return booking


@router.put("/{booking_id}", response_model=BookingResponse)
def update_booking(
    booking_id: str,
    payload: BookingUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Booking:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    for key in [
        "doctor_id",
        "hospital_id",
        "provider_name",
        "provider_external_id",
        "location_name",
        "location_address",
        "appointment_date",
        "appointment_time",
        "status",
        "booking_type",
        "symptoms_summary",
        "prescription_ids",
        "rating",
        "review",
    ]:
        value = getattr(payload, key)
        if value is not None:
            setattr(booking, key, value)

    booking.updated_at = datetime.now(timezone.utc)
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@router.put("/{booking_id}/reschedule", response_model=BookingResponse)
def reschedule_booking(
    booking_id: str,
    payload: RescheduleBookingPayload,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Booking:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    for key in [
        "appointment_date",
        "appointment_time",
        "provider_name",
        "provider_external_id",
        "location_name",
        "location_address",
        "symptoms_summary",
        "prescription_ids",
    ]:
        value = getattr(payload, key)
        if value is not None:
            setattr(booking, key, value)

    booking.status = BookingStatus.PENDING
    booking.updated_at = datetime.now(timezone.utc)
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@router.delete("/{booking_id}", status_code=204)
def cancel_booking(
    booking_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    booking.status = BookingStatus.CANCELLED
    db.add(booking)
    db.commit()


@router.post("/{booking_id}/confirm", response_model=BookingResponse)
def confirm_booking(
    booking_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.DOCTOR, UserRole.ADMIN))],
) -> Booking:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if current_user.role == UserRole.DOCTOR:
        if not current_user.doctor_profile or booking.doctor_id != current_user.doctor_profile.id:
            raise HTTPException(status_code=403, detail="Cannot confirm another doctor's booking")

    booking.status = BookingStatus.CONFIRMED
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


# Public booking schema (matches frontend payload)
class PublicBookingCreate(BaseModel):
    slNo: int = Field(..., description="Serial number for the booking")
    doctorId: int = Field(..., description="Doctor ID")
    doctorName: str = Field(..., description="Doctor name")
    patientName: str = Field(..., description="Patient name")
    patientCellphone: str = Field(..., description="Patient phone number")
    patientSex: str | None = Field(default=None, description="Patient sex")
    appointmentDate: date | None = Field(default=None, description="Appointment date")
    appointmentTime: time | None = Field(default=None, description="Appointment time")
    bookingType: str | None = Field(default=None, description="Booking type")
    locationName: str | None = Field(default=None, description="Location name")
    locationAddress: str | None = Field(default=None, description="Location address")
    symptomsSummary: str | None = Field(default=None, description="Symptoms summary")
    bkashTransactionId: str = Field(default="", description="bKash transaction ID")
    bookingStatus: str = Field(default="PENDING", description="Booking status")


class PublicBookingResponse(BaseModel):
    status: int
    message: str
    data: dict | None


@router.post("/public", response_model=PublicBookingResponse)
async def create_public_booking(
    db: Annotated[Session, Depends(get_db)],
    payload: PublicBookingCreate,
    _rate_limit: Annotated[None, Depends(ip_rate_limit(max_requests=10, endpoint="public_booking"))],
) -> dict:
    """Public booking endpoint that accepts frontend's payload format."""
    try:
        logger.info(f"Received public booking request: {payload}")
        guest_user = service.get_or_create_guest_booking_user(db)
        appointment_date = payload.appointmentDate or datetime.now(timezone.utc).date()
        appointment_time = payload.appointmentTime or time(hour=10, minute=0)
        booking_type = BookingType.ONLINE if str(payload.bookingType or "").strip().lower() == BookingType.ONLINE.value else BookingType.IN_PERSON

        booking = await service.create_manual(
            db,
            guest_user.id,
            BookingCreate(
                doctor_id=None,
                hospital_id=None,
                provider_name=payload.doctorName,
                provider_external_id=str(payload.doctorId),
                location_name=payload.locationName,
                location_address=payload.locationAddress,
                patient_name=payload.patientName,
                patient_phone=payload.patientCellphone,
                patient_sex=payload.patientSex,
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                booking_type=booking_type,
                symptoms_summary=payload.symptomsSummary,
            ),
        )

        return PublicBookingResponse(
            status=200,
            message="Booking request received successfully",
            data={
                "id": booking.id,
                "booking_id": booking.id,
                "doctor_id": str(payload.doctorId),
                "doctor_name": payload.doctorName,
                "patient_name": booking.patient_name,
                "patient_phone": booking.patient_phone,
                "patient_sex": booking.patient_sex,
                "booking_status": booking.status,
                "appointment_date": str(booking.appointment_date),
                "appointment_time": str(booking.appointment_time),
                "created_at": booking.created_at.isoformat(),
            }
        )
    except Exception as e:
        logger.exception("Error creating public booking")
        raise HTTPException(status_code=500, detail=str(e)) from e
