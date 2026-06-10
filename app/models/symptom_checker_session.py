from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import SessionStatus


class SymptomCheckerSession(Base):
    __tablename__ = "symptom_checker_sessions"
    __table_args__ = (Index("ix_symptom_sessions_status_created_at", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)

    conversation_history: Mapped[list[dict]] = mapped_column(JSON, default=list)
    detected_symptoms: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_suggestions: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(SessionStatus, name="session_status"), default=SessionStatus.ONGOING, index=True
    )
    prescription_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    symptom_progression: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship("User", back_populates="symptom_sessions")
    recommendations: Mapped[list["DoctorRecommendation"]] = relationship(
        "DoctorRecommendation", back_populates="symptom_checker_session"
    )
    diagnostics: Mapped[list["Diagnostic"]] = relationship("Diagnostic", back_populates="symptom_checker_session")
