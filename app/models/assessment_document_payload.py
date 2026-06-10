from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class AssessmentDocumentPayload(Base):
    __tablename__ = "assessment_document_payloads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    assessment_document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("assessment_documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    intake_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ai_output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    conversation_log: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    assessment_document: Mapped["AssessmentDocument"] = relationship("AssessmentDocument", back_populates="payload")
