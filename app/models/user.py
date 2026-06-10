from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        default=UserRole.USER,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reset_token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    profile: Mapped["Profile"] = relationship("Profile", back_populates="user", uselist=False)
    doctor_profile: Mapped["Doctor"] = relationship("Doctor", back_populates="user", uselist=False)

    prescriptions: Mapped[list["Prescription"]] = relationship("Prescription", back_populates="user")
    symptom_sessions: Mapped[list["SymptomCheckerSession"]] = relationship(
        "SymptomCheckerSession", back_populates="user", cascade="all, delete-orphan"
    )
    assessment_documents: Mapped[list["AssessmentDocument"]] = relationship(
        "AssessmentDocument", back_populates="user", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["DoctorRecommendation"]] = relationship("DoctorRecommendation", back_populates="user")
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="user")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user")
    diagnostics: Mapped[list["Diagnostic"]] = relationship("Diagnostic", back_populates="user")
    uploads: Mapped[list["Upload"]] = relationship("Upload", back_populates="user", cascade="all, delete-orphan")

    @property
    def hashed_password(self) -> str:
        return self.password_hash

    @hashed_password.setter
    def hashed_password(self, value: str) -> None:
        self.password_hash = value
