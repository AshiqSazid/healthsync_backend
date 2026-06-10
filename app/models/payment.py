from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import PaymentStatus


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_status_created_at", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    booking_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bookings.id", ondelete="CASCADE"), unique=True, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payable_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    received_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="BDT")
    payment_method: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    payment_gateway: Mapped[str | None] = mapped_column(String(120), nullable=True, default="shurjopay")
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.PENDING,
        index=True,
    )
    customer_order_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    gateway_transaction_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True, index=True)
    bank_transaction_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(120), nullable=True, default="doctor_booking")
    service_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bank_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sp_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sp_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_init_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_init_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_verify_response: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    raw_ipn_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    transaction_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    booking: Mapped["Booking"] = relationship("Booking", back_populates="payment")
    user: Mapped["User"] = relationship("User", back_populates="payments")
    events: Mapped[list["PaymentEvent"]] = relationship(
        "PaymentEvent",
        back_populates="payment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
