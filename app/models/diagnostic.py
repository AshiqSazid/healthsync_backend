from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Diagnostic(Base):
    __tablename__ = "diagnostics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    symptom_checker_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("symptom_checker_sessions.id", ondelete="SET NULL"), index=True
    )
    prescription_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("prescriptions.id", ondelete="SET NULL"), index=True
    )

    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    prescription_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    lab_tests: Mapped[list[dict]] = mapped_column(JSON, default=list)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship("User", back_populates="diagnostics")
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="diagnostics")
    symptom_checker_session: Mapped["SymptomCheckerSession"] = relationship(
        "SymptomCheckerSession", back_populates="diagnostics"
    )
    prescription: Mapped["Prescription"] = relationship("Prescription", back_populates="diagnostics")
