from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SAEnum, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.enums import SymptomCategory


class Symptom(Base):
    __tablename__ = "symptoms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[SymptomCategory] = mapped_column(
        SAEnum(SymptomCategory, name="symptom_category"), default=SymptomCategory.GENERAL, index=True
    )
    severity_level: Mapped[int] = mapped_column(default=1)

    common_causes: Mapped[list[str]] = mapped_column(JSON, default=list)
    related_symptoms: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_specializations: Mapped[list[str]] = mapped_column(JSON, default=list)
    urgency_indicators: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
