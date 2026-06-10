from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)

    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emergency_contact: Mapped[str | None] = mapped_column(String(120), nullable=True)

    medical_history: Mapped[dict] = mapped_column(JSON, default=dict)
    chronic_conditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    allergies: Mapped[list[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship("User", back_populates="profile")
