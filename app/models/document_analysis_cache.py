from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class DocumentAnalysisCache(Base):
    __tablename__ = "document_analysis_cache"
    __table_args__ = (
        UniqueConstraint(
            "content_hash",
            "document_kind",
            "language",
            "vision_model",
            "prompt_version",
            name="uq_document_analysis_cache_lookup",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    vision_model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="v1")
    analysis_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
