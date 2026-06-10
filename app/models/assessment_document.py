from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import AssessmentDocumentStatus


class AssessmentDocument(Base):
    __tablename__ = "assessment_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    symptom_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_route: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intake_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_output: Mapped[dict] = mapped_column(JSON, default=dict)
    conversation_log: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[AssessmentDocumentStatus] = mapped_column(
        SAEnum(
            AssessmentDocumentStatus,
            name="assessment_document_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=AssessmentDocumentStatus.DRAFT,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["User"] = relationship("User", back_populates="assessment_documents")
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="linked_assessment")
    payload: Mapped["AssessmentDocumentPayload | None"] = relationship(
        "AssessmentDocumentPayload",
        back_populates="assessment_document",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
