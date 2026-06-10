from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    country: Mapped[str] = mapped_column(String(120), nullable=False)
    pincode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    facilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    operating_hours: Mapped[dict] = mapped_column(JSON, default=dict)
    emergency_services: Mapped[bool] = mapped_column(Boolean, default=False)
    departments: Mapped[list[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    doctors: Mapped[list["Doctor"]] = relationship("Doctor", back_populates="hospital")
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="hospital")
