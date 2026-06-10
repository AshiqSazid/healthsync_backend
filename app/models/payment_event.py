from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        Index("ix_payment_events_payment_id_created_at", "payment_id", "created_at"),
        Index("ix_payment_events_event_type_created_at", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_source: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    payment: Mapped["Payment"] = relationship("Payment", back_populates="events")
