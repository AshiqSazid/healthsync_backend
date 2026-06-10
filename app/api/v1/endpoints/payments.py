from __future__ import annotations

from datetime import date
import logging
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_current_user_optional,
    require_roles,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.enums import PaymentStatus, UserRole
from app.models.user import User
from app.schemas.payment import (
    PaginatedPaymentsResponse,
    PaymentInitiateRequest,
    PaymentInitiateResponse,
    PaymentResponse,
    PaymentStatsResponse,
    PaymentVerifyRequest,
)
from app.services.payment_service import PaymentService

router = APIRouter()
admin_router = APIRouter()
service = PaymentService()
logger = logging.getLogger(__name__)


def _resolve_client_ip(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        candidate = forwarded_for.split(",", 1)[0].strip()
        if candidate:
            return candidate

    real_ip = str(request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip

    return request.client.host if request.client else "127.0.0.1"


def _resolve_backend_base_url(request: Request) -> str:
    if settings.BACKEND_PUBLIC_URL:
        return settings.BACKEND_PUBLIC_URL
    return str(request.base_url).rstrip("/")


def _extract_reference(request: Request, payload: dict[str, Any] | None = None) -> str | None:
    payload = payload or {}
    candidates = [
        request.query_params.get("order_id"),
        request.query_params.get("sp_order_id"),
        request.path_params.get("order_id"),
        payload.get("order_id"),
        payload.get("sp_order_id"),
        payload.get("spOrderId"),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _payment_result_path(status_value: str | None) -> str:
    normalized = str(status_value or "").strip().lower()
    if normalized == PaymentStatus.COMPLETED.value:
        return "/payment/success"
    if normalized == PaymentStatus.CANCELLED.value:
        return "/payment/cancelled"
    if normalized == PaymentStatus.FAILED.value:
        return "/payment/failed"
    return "/payments/result"


def _build_result_redirect_url(
    payment: PaymentResponse | None,
    *,
    doctor_ref: str | None,
    message: str | None,
    status_value: str | None = None,
    path_override: str | None = None,
) -> str:
    resolved_status = status_value or (payment.status.value if payment else PaymentStatus.FAILED.value)
    params = {
        "status": resolved_status,
        "payment_id": payment.id if payment else None,
        "booking_id": payment.booking_id if payment else None,
        "amount": str(payment.amount) if payment else None,
        "currency": payment.currency if payment else None,
        "payment_method": payment.payment_method if payment else None,
        "customer_order_id": payment.customer_order_id if payment else None,
        "order_id": payment.order_id if payment else None,
        "gateway_transaction_id": payment.gateway_transaction_id if payment else None,
        "sp_order_id": payment.sp_order_id if payment else None,
        "provider_name": payment.provider_name if payment else None,
        "appointment_date": payment.appointment_date.isoformat() if payment and payment.appointment_date else None,
        "appointment_time": payment.appointment_time.isoformat() if payment and payment.appointment_time else None,
        "doctor_ref": doctor_ref,
        "message": message or (payment.status_message if payment else None),
    }
    query = urlencode({key: value for key, value in params.items() if value not in {None, ""}})
    path = path_override or _payment_result_path(resolved_status)
    return f"{settings.FRONTEND_URL}{path}{f'?{query}' if query else ''}"


def _to_paginated_response(items: list[PaymentResponse], *, total: int, page: int, page_size: int) -> PaginatedPaymentsResponse:
    return PaginatedPaymentsResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/initiate", response_model=PaymentInitiateResponse)
@router.post("/shurjopay/initiate", response_model=PaymentInitiateResponse, include_in_schema=False)
def initiate_shurjopay_payment(
    payload: PaymentInitiateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> PaymentInitiateResponse:
    payment = service.initiate_shurjopay_payment(
        db,
        booking_id=payload.booking_id,
        requested_amount=payload.amount,
        currency=payload.currency,
        current_user=current_user,
        patient_phone=payload.patient_phone or payload.phone,
        client_ip=_resolve_client_ip(request),
        backend_base_url=_resolve_backend_base_url(request),
        customer_name=payload.name,
        customer_phone=payload.phone,
        customer_email=payload.email,
        customer_address=payload.address,
        customer_city=payload.city,
        customer_post_code=payload.post_code,
        service_type=payload.service_type,
        service_details=payload.service_details,
        value1=payload.value1,
        value2=payload.value2,
        value3=payload.value3,
        value4=payload.value4,
    )
    return PaymentInitiateResponse(
        payment_id=payment.id,
        booking_id=payment.booking_id,
        customer_order_id=payment.customer_order_id,
        order_id=payment.customer_order_id,
        sp_order_id=payment.gateway_transaction_id,
        checkout_url=payment.checkout_url or "",
        status=payment.status,
    )


@router.get("/callback")
@router.get("/shurjopay/return", include_in_schema=False)
def shurjopay_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    reference = _extract_reference(request)
    if not reference:
        return RedirectResponse(
            _build_result_redirect_url(
                None,
                doctor_ref=None,
                message="ShurjoPay did not return an order reference",
                status_value=PaymentStatus.FAILED.value,
                path_override="/payment/failed",
            ),
            status_code=303,
        )

    payment = service.find_payment_by_reference(db, order_reference=reference, prefer_gateway=True)
    doctor_ref = None
    if payment and payment.booking:
        doctor_ref = payment.booking.provider_external_id or payment.booking.doctor_id

    try:
        verified_payment = service.verify_payment_by_reference(
            db,
            order_reference=reference,
            prefer_gateway=True,
        )
        payment_response = service.build_payment_response(verified_payment)
        if verified_payment.booking:
            doctor_ref = verified_payment.booking.provider_external_id or verified_payment.booking.doctor_id
        target_url = _build_result_redirect_url(
            payment_response,
            doctor_ref=doctor_ref,
            message=payment_response.status_message,
        )
    except HTTPException as exc:
        payment_response = service.build_payment_response(payment) if payment else None
        fallback_status = payment_response.status.value if payment_response else PaymentStatus.FAILED.value
        target_url = _build_result_redirect_url(
            payment_response,
            doctor_ref=doctor_ref,
            message=str(exc.detail),
            status_value=fallback_status,
        )
    return RedirectResponse(target_url, status_code=303)


@router.get("/cancel")
def shurjopay_cancel(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    reference = _extract_reference(request)
    payment = None
    if reference:
        try:
            payment = service.cancel_payment_by_reference(
                db,
                order_reference=str(reference or "").strip(),
                message="Payment cancelled by customer",
                prefer_gateway=True,
            )
        except Exception:
            # Never fail the browser-facing cancellation redirect due to backend
            # reconciliation issues. We still route the user to cancelled UX.
            logger.exception("Failed to persist shurjoPay cancel state reference=%s", reference)
    doctor_ref = None
    payment_response = None
    if payment is not None:
        payment_response = service.build_payment_response(payment)
        if payment.booking:
            doctor_ref = payment.booking.provider_external_id or payment.booking.doctor_id

    target_url = _build_result_redirect_url(
        payment_response,
        doctor_ref=doctor_ref,
        message="Payment cancelled by customer",
        status_value=PaymentStatus.CANCELLED.value,
        path_override="/payment/cancelled",
    )
    return RedirectResponse(target_url, status_code=303)


@router.post("/shurjopay/ipn", response_model=PaymentResponse, include_in_schema=False)
async def shurjopay_ipn(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> PaymentResponse:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    reference = _extract_reference(request, payload)
    if not reference:
        raise HTTPException(status_code=400, detail="Missing ShurjoPay order reference")

    payment = service.verify_payment_by_reference(
        db,
        order_reference=reference,
        ipn_payload=payload,
        prefer_gateway=True,
    )
    return service.build_payment_response(payment)


@router.get("/history", response_model=PaginatedPaymentsResponse)
def payment_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    page: int = 1,
    page_size: int = 10,
    status_filter: Annotated[PaymentStatus | None, Query(alias="status")] = None,
) -> PaginatedPaymentsResponse:
    items, total, safe_page, safe_page_size = service.get_payment_history_page(
        db,
        current_user=current_user,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )
    responses = [service.build_payment_response(payment) for payment in items]
    return _to_paginated_response(responses, total=total, page=safe_page, page_size=safe_page_size)


@router.get("/", response_model=list[PaymentResponse])
def list_payments(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    method: str | None = None,
    query: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    booking_id: str | None = None,
    user_id: str | None = None,
) -> list[PaymentResponse]:
    payments = service.list_payments(
        db,
        current_user=current_user,
        status_filter=status_filter,
        method=method,
        query=query,
        date_from=date_from,
        date_to=date_to,
        booking_id=booking_id,
        user_id=user_id,
    )
    return [service.build_payment_response(payment) for payment in payments]


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PaymentResponse:
    payment = service.get_payment(db, payment_id=payment_id, current_user=current_user)
    return service.build_payment_response(payment)


@router.post("/{payment_id}/verify", response_model=PaymentResponse)
def verify_payment(
    payment_id: str,
    payload: PaymentVerifyRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> PaymentResponse:
    payment = service.verify_payment(
        db,
        payment_id=payment_id,
        current_user=current_user,
        patient_phone=payload.patient_phone,
    )
    return service.build_payment_response(payment)


@admin_router.get("/", response_model=PaginatedPaymentsResponse)
def admin_list_payments(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    page: int = 1,
    page_size: int = 10,
    status_filter: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    method: str | None = None,
    query: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> PaginatedPaymentsResponse:
    items, total, safe_page, safe_page_size = service.list_admin_payments_page(
        db,
        current_user=current_user,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        method=method,
        query=query,
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    responses = [service.build_payment_response(payment) for payment in items]
    return _to_paginated_response(responses, total=total, page=safe_page, page_size=safe_page_size)


@admin_router.get("/stats", response_model=PaymentStatsResponse)
def admin_payment_stats(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    status_filter: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    method: str | None = None,
    query: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = None,
) -> PaymentStatsResponse:
    return service.get_admin_payment_stats(
        db,
        current_user=current_user,
        status_filter=status_filter,
        method=method,
        query=query,
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
    )


@admin_router.get("/export")
def admin_export_payments(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    status_filter: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    method: str | None = None,
    query: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> Response:
    csv_content = service.export_admin_payments_csv(
        db,
        current_user=current_user,
        status_filter=status_filter,
        method=method,
        query=query,
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="payments.csv"'},
    )


@admin_router.get("/{payment_id}", response_model=PaymentResponse)
def admin_get_payment(
    payment_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> PaymentResponse:
    payment = service.get_payment(db, payment_id=payment_id, current_user=current_user)
    return service.build_payment_response(payment)
