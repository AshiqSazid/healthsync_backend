from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class DoctorRecommendation(Base):
    __tablename__ = "doctor_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symptom_checker_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("symptom_checker_sessions.id", ondelete="SET NULL"), index=True
    )

    prescription_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_doctors: Mapped[list[dict]] = mapped_column(JSON, default=list)
    recommendation_criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(50), default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    user: Mapped["User"] = relationship("User", back_populates="recommendations")
    symptom_checker_session: Mapped["SymptomCheckerSession"] = relationship(
        "SymptomCheckerSession", back_populates="recommendations"
    )
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="recommendation")
