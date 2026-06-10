from __future__ import annotations

from datetime import date, datetime, time, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, JSON, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import BookingStatus, BookingType


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="booking_rating_check"),
        Index("ix_bookings_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("doctors.id", ondelete="SET NULL"), index=True)
    hospital_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("hospitals.id", ondelete="SET NULL"), index=True)
    recommendation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("doctor_recommendations.id", ondelete="SET NULL"), index=True
    )
    linked_assessment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assessment_documents.id", ondelete="SET NULL"), index=True
    )
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    provider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    patient_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    patient_phone_snapshot: Mapped[str | None] = mapped_column(String(30), nullable=True)
    patient_sex_snapshot: Mapped[str | None] = mapped_column(String(30), nullable=True)

    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    appointment_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, name="booking_status"), default=BookingStatus.PENDING, index=True
    )
    booking_type: Mapped[BookingType] = mapped_column(
        SAEnum(BookingType, name="booking_type"), default=BookingType.IN_PERSON, index=True
    )
    symptoms_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    prescription_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rating: Mapped[int | None] = mapped_column(nullable=True)
    review: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship("User", back_populates="bookings")
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="bookings")
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="bookings")
    recommendation: Mapped["DoctorRecommendation"] = relationship("DoctorRecommendation", back_populates="bookings")
    linked_assessment: Mapped["AssessmentDocument | None"] = relationship("AssessmentDocument", back_populates="bookings")
    payment: Mapped["Payment"] = relationship("Payment", back_populates="booking", uselist=False)

    @property
    def patient_name(self) -> str | None:
        if self.patient_name_snapshot:
            return self.patient_name_snapshot
        if self.user is None:
            return None
        if self.user.profile and self.user.profile.full_name:
            return self.user.profile.full_name
        if self.user.name:
            return self.user.name
        return self.user.username

    @property
    def patient_phone(self) -> str | None:
        if self.patient_phone_snapshot:
            return self.patient_phone_snapshot
        if self.user and self.user.profile:
            return self.user.profile.phone
        return None

    @property
    def patient_email(self) -> str | None:
        if self.user:
            return self.user.email
        return None

    @property
    def patient_sex(self) -> str | None:
        if self.patient_sex_snapshot:
            return self.patient_sex_snapshot
        if self.user and self.user.profile:
            return self.user.profile.gender
        return None
