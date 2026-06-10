from datetime import date, datetime, time

from pydantic import Field

from app.models.enums import BookingStatus, BookingType
from app.schemas.common import ORMModel


class BookingBase(ORMModel):
    doctor_id: str | None = None
    hospital_id: str | None = None
    provider_name: str | None = None
    provider_external_id: str | None = None
    location_name: str | None = None
    location_address: str | None = None
    patient_name: str | None = None
    patient_phone: str | None = None
    patient_sex: str | None = None
    appointment_date: date
    appointment_time: time
    booking_type: BookingType = BookingType.IN_PERSON
    symptoms_summary: str | None = None
    prescription_ids: list[str] = Field(default_factory=list)
    linked_assessment_id: str | None = None


class BookingCreate(BookingBase):
    recommendation_id: str | None = None
    client_request_id: str | None = None


class BookingFromRecommendation(ORMModel):
    recommendation_id: str
    doctor_id: str
    preferred_date: date
    preferred_time: time
    symptoms_summary: str | None = None
    prescription_ids: list[str] = Field(default_factory=list)


class BookingUpdate(ORMModel):
    doctor_id: str | None = None
    hospital_id: str | None = None
    provider_name: str | None = None
    provider_external_id: str | None = None
    location_name: str | None = None
    location_address: str | None = None
    appointment_date: date | None = None
    appointment_time: time | None = None
    status: BookingStatus | None = None
    booking_type: BookingType | None = None
    symptoms_summary: str | None = None
    prescription_ids: list[str] | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    review: str | None = None


class BookingResponse(ORMModel):
    id: str
    user_id: str
    patient_name: str | None = None
    patient_phone: str | None = None
    patient_sex: str | None = None
    patient_email: str | None = None
    doctor_id: str | None = None
    hospital_id: str | None = None
    recommendation_id: str | None = None
    linked_assessment_id: str | None = None
    client_request_id: str | None = None
    provider_name: str | None = None
    provider_external_id: str | None = None
    location_name: str | None = None
    location_address: str | None = None
    appointment_date: date
    appointment_time: time
    status: BookingStatus
    booking_type: BookingType
    symptoms_summary: str | None = None
    prescription_ids: list[str]
    rating: int | None = None
    review: str | None = None
    created_at: datetime
    updated_at: datetime
