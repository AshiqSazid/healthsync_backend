from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("doctors.id", ondelete="SET NULL"), index=True)

    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    upload_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    parsed_data: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verified_by_doctor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("doctors.id", ondelete="SET NULL"), index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship("User", back_populates="prescriptions")
    prescribing_doctor: Mapped["Doctor"] = relationship(
        "Doctor", foreign_keys=[doctor_id], back_populates="prescriptions"
    )
    verified_by: Mapped["Doctor"] = relationship(
        "Doctor", foreign_keys=[verified_by_doctor_id], back_populates="verified_prescriptions"
    )
    diagnostics: Mapped[list["Diagnostic"]] = relationship("Diagnostic", back_populates="prescription")
