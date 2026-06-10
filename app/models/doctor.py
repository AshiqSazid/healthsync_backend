from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    specialization: Mapped[list[str]] = mapped_column(JSON, default=list)
    sub_specializations: Mapped[list[str]] = mapped_column(JSON, default=list)
    license_number: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    experience_years: Mapped[int] = mapped_column(default=0)
    consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    hospital_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("hospitals.id", ondelete="SET NULL"), index=True)
    average_rating: Mapped[float] = mapped_column(default=0.0)
    available_slots: Mapped[list[dict]] = mapped_column(JSON, default=list)
    languages_spoken: Mapped[list[str]] = mapped_column(JSON, default=list)
    conditions_treated: Mapped[list[str]] = mapped_column(JSON, default=list)
    education: Mapped[list[dict]] = mapped_column(JSON, default=list)
    certifications: Mapped[list[dict]] = mapped_column(JSON, default=list)
    photo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    photo_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship("User", back_populates="doctor_profile")
    hospital: Mapped["Hospital"] = relationship("Hospital", back_populates="doctors")

    prescriptions: Mapped[list["Prescription"]] = relationship(
        "Prescription", foreign_keys="Prescription.doctor_id", back_populates="prescribing_doctor"
    )
    verified_prescriptions: Mapped[list["Prescription"]] = relationship(
        "Prescription", foreign_keys="Prescription.verified_by_doctor_id", back_populates="verified_by"
    )
    diagnostics: Mapped[list["Diagnostic"]] = relationship("Diagnostic", back_populates="doctor")
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="doctor")

    @property
    def display_name(self) -> str:
        if self.user and self.user.username:
            return self.user.username
        return self.license_number

    @property
    def image_url(self) -> str | None:
        return self.photo_url

    @property
    def imageUrl(self) -> str | None:
        return self.photo_url
