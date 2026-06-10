from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.models.enums import PaymentStatus
from app.schemas.common import ORMModel


class PaymentInitiateRequest(ORMModel):
    booking_id: str
    amount: Decimal = Field(..., gt=0)
    currency: str = "BDT"
    patient_phone: str | None = None
    # Customer details collected from the payment form (override booking/profile data)
    name: str | None = None         # → customer_name
    phone: str | None = None        # → customer_phone
    email: str | None = None        # → customer_email
    address: str | None = None      # → customer_address
    city: str | None = None         # → customer_city
    post_code: str | None = None    # → customer_postcode
    service_type: str | None = None
    service_details: dict[str, Any] | None = None
    value1: str | None = None
    value2: str | None = None
    value3: str | None = None
    value4: str | None = None


class PaymentInitiateResponse(ORMModel):
    payment_id: str
    booking_id: str
    customer_order_id: str | None = None
    order_id: str | None = None
    sp_order_id: str | None = None       # ShurjoPay gateway order ID (from /secret-pay response)
    checkout_url: str                     # securepay.shurjopayment.com/spaycheckout?token=...
    status: PaymentStatus


class PaymentVerifyRequest(ORMModel):
    patient_phone: str | None = None


class PaymentResponse(ORMModel):
    id: str
    booking_id: str
    user_id: str
    amount: Decimal
    payable_amount: Decimal | None = None
    discount_amount: Decimal = Decimal("0.00")
    received_amount: Decimal | None = None
    currency: str
    payment_method: str | None = None
    payment_gateway: str | None = None
    status: PaymentStatus
    transaction_id: str | None = None
    customer_order_id: str | None = None
    order_id: str | None = None
    gateway_transaction_id: str | None = None
    sp_order_id: str | None = None
    bank_transaction_id: str | None = None
    checkout_url: str | None = None
    payer_name: str | None = None
    payer_phone: str | None = None
    payer_email: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_email: str | None = None
    customer_address: str | None = None
    customer_city: str | None = None
    service_type: str | None = None
    service_details: dict[str, Any] | None = None
    bank_status: str | None = None
    sp_code: int | None = None
    sp_message: str | None = None
    status_message: str | None = None
    provider_name: str | None = None
    appointment_date: date | None = None
    appointment_time: time | None = None
    transaction_date: datetime | None = None
    verified_at: datetime | None = None
    paid_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    raw_init_payload: dict[str, Any] | None = None
    raw_init_response: dict[str, Any] | None = None
    raw_verify_response: dict[str, Any] | list[Any] | None = None
    raw_ipn_payload: dict[str, Any] | None = None
    raw_response: dict[str, Any] | list[Any] | None = None


class PaginatedPaymentsResponse(ORMModel):
    items: list[PaymentResponse]
    total: int
    page: int
    page_size: int


class PaymentStatsResponse(ORMModel):
    total_revenue: Decimal
    today_revenue: Decimal
    total_transactions: int
    completed_transactions: int
    failed_transactions: int
    cancelled_transactions: int
    pending_transactions: int
    success_rate: float
    failure_rate: float
