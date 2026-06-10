from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import false, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.booking import Booking
from app.models.doctor import Doctor
from app.models.enums import PaymentStatus, UserRole
from app.models.payment import Payment
from app.models.payment_event import PaymentEvent
from app.models.profile import Profile
from app.models.user import User
from app.schemas.payment import PaymentResponse, PaymentStatsResponse
from app.services.booking_service import BookingService
from app.services.shurjopay_client import ShurjoPayClient, ShurjoPayError

logger = logging.getLogger(__name__)


class PaymentService:
    GUEST_BOOKING_USERNAME = BookingService.GUEST_BOOKING_USERNAME
    RETRYABLE_STATUSES = {
        PaymentStatus.PENDING,
        PaymentStatus.FAILED,
        PaymentStatus.CANCELLED,
    }
    DEFAULT_HISTORY_PAGE_SIZE = 10
    MAX_PAGE_SIZE = 100

    def _record_payment_event(
        self,
        db: Session,
        *,
        payment: Payment,
        event_type: str,
        event_source: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = PaymentEvent(
            payment=payment,
            event_type=event_type,
            event_source=event_source,
            payload=self._coerce_json_value(payload or {}),
        )
        db.add(event)

    def _create_client(self) -> ShurjoPayClient:
        return ShurjoPayClient()

    def list_payments(
        self,
        db: Session,
        *,
        current_user: User,
        status_filter: PaymentStatus | None = None,
        method: str | None = None,
        query: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        booking_id: str | None = None,
        user_id: str | None = None,
    ) -> list[Payment]:
        payment_query = self._payment_query(db)
        payment_query = self._apply_role_scope(payment_query, current_user)
        payment_query = self._apply_payment_filters(
            payment_query,
            status_filter=status_filter,
            method=method,
            query=query,
            date_from=date_from,
            date_to=date_to,
            booking_id=booking_id,
            user_id=(user_id if current_user.role == UserRole.ADMIN else None),
        )
        return payment_query.order_by(Payment.created_at.desc()).all()

    def get_payment_history_page(
        self,
        db: Session,
        *,
        current_user: User,
        page: int,
        page_size: int,
        status_filter: PaymentStatus | None = None,
    ) -> tuple[list[Payment], int, int, int]:
        payment_query = self._payment_query(db)
        payment_query = self._apply_role_scope(payment_query, current_user)
        payment_query = self._apply_payment_filters(payment_query, status_filter=status_filter)
        payment_query = payment_query.order_by(Payment.created_at.desc())
        return self._paginate_query(payment_query, page=page, page_size=page_size)

    def list_admin_payments_page(
        self,
        db: Session,
        *,
        current_user: User,
        page: int,
        page_size: int,
        status_filter: PaymentStatus | None = None,
        method: str | None = None,
        query: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        user_id: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> tuple[list[Payment], int, int, int]:
        self._assert_admin(current_user)
        payment_query = self._payment_query(db)
        payment_query = self._apply_payment_filters(
            payment_query,
            status_filter=status_filter,
            method=method,
            query=query,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
        )
        payment_query = self._apply_sorting(payment_query, sort_by=sort_by, sort_order=sort_order)
        return self._paginate_query(payment_query, page=page, page_size=page_size)

    def get_admin_payment_stats(
        self,
        db: Session,
        *,
        current_user: User,
        status_filter: PaymentStatus | None = None,
        method: str | None = None,
        query: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        user_id: str | None = None,
    ) -> PaymentStatsResponse:
        self._assert_admin(current_user)
        payment_query = self._payment_query(db)
        payment_query = self._apply_payment_filters(
            payment_query,
            status_filter=status_filter,
            method=method,
            query=query,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
        )
        payments = payment_query.order_by(Payment.created_at.desc()).all()
        total_transactions = len(payments)
        completed = [payment for payment in payments if payment.status == PaymentStatus.COMPLETED]
        failed = [payment for payment in payments if payment.status == PaymentStatus.FAILED]
        cancelled = [payment for payment in payments if payment.status == PaymentStatus.CANCELLED]
        pending = [payment for payment in payments if payment.status == PaymentStatus.PENDING]
        total_revenue = sum((self._effective_revenue_amount(payment) for payment in completed), Decimal("0.00"))
        today_utc = datetime.now(timezone.utc).date()
        today_revenue = sum(
            (
                self._effective_revenue_amount(payment)
                for payment in completed
                if self._payment_activity_datetime(payment)
                and self._payment_activity_datetime(payment).astimezone(timezone.utc).date() == today_utc
            ),
            Decimal("0.00"),
        )
        success_rate = round((len(completed) / total_transactions) * 100, 2) if total_transactions else 0.0
        failure_rate = round(((len(failed) + len(cancelled)) / total_transactions) * 100, 2) if total_transactions else 0.0

        return PaymentStatsResponse(
            total_revenue=total_revenue.quantize(Decimal("0.01")),
            today_revenue=today_revenue.quantize(Decimal("0.01")),
            total_transactions=total_transactions,
            completed_transactions=len(completed),
            failed_transactions=len(failed),
            cancelled_transactions=len(cancelled),
            pending_transactions=len(pending),
            success_rate=success_rate,
            failure_rate=failure_rate,
        )

    def export_admin_payments_csv(
        self,
        db: Session,
        *,
        current_user: User,
        status_filter: PaymentStatus | None = None,
        method: str | None = None,
        query: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        user_id: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> str:
        self._assert_admin(current_user)
        payment_query = self._payment_query(db)
        payment_query = self._apply_payment_filters(
            payment_query,
            status_filter=status_filter,
            method=method,
            query=query,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
        )
        payment_query = self._apply_sorting(payment_query, sort_by=sort_by, sort_order=sort_order)
        payments = payment_query.all()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "payment_id",
                "booking_id",
                "user_id",
                "payer_name",
                "payer_email",
                "payer_phone",
                "order_id",
                "sp_order_id",
                "bank_transaction_id",
                "amount",
                "payable_amount",
                "discount_amount",
                "received_amount",
                "currency",
                "payment_method",
                "status",
                "service_type",
                "provider_name",
                "transaction_date",
                "verified_at",
                "created_at",
            ]
        )
        for payment in payments:
            payment_response = self.build_payment_response(payment)
            writer.writerow(
                [
                    payment_response.id,
                    payment_response.booking_id,
                    payment_response.user_id,
                    payment_response.customer_name or "",
                    payment_response.customer_email or "",
                    payment_response.customer_phone or "",
                    payment_response.order_id or "",
                    payment_response.sp_order_id or "",
                    payment_response.bank_transaction_id or "",
                    self._format_decimal(payment_response.amount),
                    self._format_decimal(payment_response.payable_amount),
                    self._format_decimal(payment_response.discount_amount),
                    self._format_decimal(payment_response.received_amount),
                    payment_response.currency,
                    payment_response.payment_method or "",
                    payment_response.status.value,
                    payment_response.service_type or "",
                    payment_response.provider_name or "",
                    payment_response.transaction_date.isoformat() if payment_response.transaction_date else "",
                    payment_response.verified_at.isoformat() if payment_response.verified_at else "",
                    payment_response.created_at.isoformat(),
                ]
            )
        return buffer.getvalue()

    def get_payment(self, db: Session, *, payment_id: str, current_user: User) -> Payment:
        payment = self._payment_query(db).filter(Payment.id == payment_id).first()
        if payment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
        self._assert_payment_access(payment, current_user=current_user, patient_phone=None)
        return payment

    def initiate_shurjopay_payment(
        self,
        db: Session,
        *,
        booking_id: str,
        requested_amount: Decimal,
        currency: str,
        current_user: User | None,
        patient_phone: str | None,
        client_ip: str,
        backend_base_url: str,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        customer_email: str | None = None,
        customer_address: str | None = None,
        customer_city: str | None = None,
        customer_post_code: str | None = None,
        service_type: str | None = None,
        service_details: dict[str, Any] | None = None,
        value1: str | None = None,
        value2: str | None = None,
        value3: str | None = None,
        value4: str | None = None,
    ) -> Payment:
        booking = self._booking_query(db).filter(Booking.id == booking_id).first()
        if booking is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

        self._assert_booking_payment_access(booking, current_user=current_user, patient_phone=patient_phone)

        payment = self._payment_query(db).filter(Payment.booking_id == booking.id).first()
        if payment is not None and payment.status == PaymentStatus.COMPLETED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment already completed for this booking")
        if payment is not None and payment.status not in self.RETRYABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment cannot be retried from its current state")

        amount = self._resolve_amount(booking, requested_amount, existing_payment=payment)
        if amount <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A positive payment amount is required")

        payer_snapshot = self._build_payer_snapshot(booking)

        # Override snapshot with explicit customer fields supplied by the payment form
        if customer_name and customer_name.strip():
            payer_snapshot["payer_name"] = customer_name.strip()
        if customer_phone and customer_phone.strip():
            normalized_cp = self._normalize_phone(customer_phone)
            if normalized_cp:
                payer_snapshot["payer_phone"] = normalized_cp
        if customer_email and customer_email.strip():
            payer_snapshot["payer_email"] = customer_email.strip()
        if customer_address and customer_address.strip():
            payer_snapshot["customer_address"] = customer_address.strip()
        if customer_city and customer_city.strip():
            payer_snapshot["customer_city"] = customer_city.strip()
        if customer_post_code and customer_post_code.strip():
            payer_snapshot["customer_post_code"] = customer_post_code.strip()

        customer_order_id = self._build_customer_order_id(booking)
        normalized_currency = str(currency or settings.SHURJOPAY_DEFAULT_CURRENCY).strip().upper() or settings.SHURJOPAY_DEFAULT_CURRENCY
        normalized_service_type = str(service_type or (payment.service_type if payment else "") or "doctor_booking").strip() or "doctor_booking"
        merged_service_details = self._build_service_details(
            booking,
            normalized_service_type=normalized_service_type,
            service_details=service_details,
            value1=value1,
            value2=value2,
            value3=value3,
            value4=value4,
        )
        return_url = settings.SHURJOPAY_RETURN_URL or f"{backend_base_url}{settings.API_V1_STR}/payments/callback"
        cancel_url = settings.SHURJOPAY_CANCEL_URL or f"{backend_base_url}{settings.API_V1_STR}/payments/cancel"
        checkout_payload = {
            # Sent as multipart/form-data — all values must be strings
            "amount": str(float(amount)),
            "discount_amount": "0",
            "disc_percent": "0",
            "order_id": customer_order_id,
            "currency": normalized_currency,
            "customer_name": payer_snapshot["payer_name"],
            "customer_address": payer_snapshot["customer_address"],
            "customer_city": payer_snapshot["customer_city"],
            "customer_state": payer_snapshot["customer_city"],
            "customer_post_code": payer_snapshot["customer_post_code"],   # docs field name
            "customer_postcode": payer_snapshot["customer_post_code"],    # legacy alias some versions expect
            "customer_phone": payer_snapshot["payer_phone"],
            "customer_email": payer_snapshot["payer_email"],
            "client_ip": str(client_ip or "127.0.0.1").strip() or "127.0.0.1",
            "customer_country": "BD",
        }
        for key, value in {
            "value1": value1,
            "value2": value2,
            "value3": value3,
            "value4": value4,
        }.items():
            text = str(value or "").strip()
            if text:
                checkout_payload[key] = text

        if payment is None:
            payment = Payment(
                booking_id=booking.id,
                user_id=booking.user_id,
                amount=amount,
                payable_amount=amount,
                discount_amount=Decimal("0.00"),
                received_amount=None,
                currency=normalized_currency,
                payment_method="",
                payment_gateway="shurjopay",
                status=PaymentStatus.PENDING,
            )

        payment.user_id = booking.user_id
        payment.amount = amount
        payment.payable_amount = amount
        payment.discount_amount = Decimal("0.00")
        payment.received_amount = None
        payment.currency = normalized_currency
        payment.payment_method = ""
        payment.payment_gateway = "shurjopay"
        payment.status = PaymentStatus.PENDING
        payment.customer_order_id = customer_order_id
        payment.gateway_transaction_id = None
        payment.transaction_id = None
        payment.bank_transaction_id = None
        payment.bank_status = None
        payment.sp_code = None
        payment.sp_message = None
        payment.checkout_url = None
        payment.payer_name = payer_snapshot["payer_name"]
        payment.payer_phone = payer_snapshot["payer_phone"]
        payment.payer_email = payer_snapshot["payer_email"]
        payment.customer_address = payer_snapshot["customer_address"]
        payment.customer_city = payer_snapshot["customer_city"]
        payment.service_type = normalized_service_type
        payment.service_details = merged_service_details
        payment.status_message = None
        payment.raw_init_payload = checkout_payload
        payment.raw_init_response = None
        payment.raw_verify_response = None
        payment.raw_ipn_payload = None
        payment.transaction_date = None
        payment.verified_at = None
        payment.paid_at = None

        client = self._create_client()
        logger.info(
            "ShurjoPay /secret-pay payload for booking %s: amount=%s currency=%s customer_name=%r customer_phone=%r customer_email=%r customer_address=%r customer_city=%r",
            booking.id,
            checkout_payload.get("amount"),
            checkout_payload.get("currency"),
            checkout_payload.get("customer_name"),
            checkout_payload.get("customer_phone"),
            checkout_payload.get("customer_email"),
            checkout_payload.get("customer_address"),
            checkout_payload.get("customer_city"),
        )
        try:
            init_response = client.initiate_payment(
                checkout_payload,
                return_url=return_url,
                cancel_url=cancel_url,
            )
            logger.info(
                "ShurjoPay /secret-pay response for booking %s: checkout_url=%r sp_code=%r sp_message=%r",
                booking.id,
                init_response.get("checkout_url") if isinstance(init_response, dict) else None,
                init_response.get("sp_code") if isinstance(init_response, dict) else None,
                init_response.get("sp_message") if isinstance(init_response, dict) else None,
            )
        except ShurjoPayError as exc:
            logger.warning("shurjoPay initiate failed for booking %s: %s", booking.id, exc)
            payment.status = PaymentStatus.FAILED
            payment.status_message = str(exc)
            payment.sp_message = str(exc)
            payment.raw_init_response = self._coerce_json_value(exc.payload)
            db.add(payment)
            self._record_payment_event(
                db,
                payment=payment,
                event_type="initiate_failed",
                event_source="shurjopay",
                payload={"error": str(exc), "response": self._coerce_json_value(exc.payload)},
            )
            db.commit()
            db.refresh(payment)
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        checkout_url = self._extract_checkout_url(init_response)
        if not checkout_url:
            payment.status = PaymentStatus.FAILED
            payment.status_message = "ShurjoPay did not return a checkout URL"
            payment.sp_message = payment.status_message
            payment.raw_init_response = self._coerce_json_value(init_response)
            db.add(payment)
            self._record_payment_event(
                db,
                payment=payment,
                event_type="initiate_failed_no_checkout_url",
                event_source="shurjopay",
                payload={"response": self._coerce_json_value(init_response)},
            )
            db.commit()
            db.refresh(payment)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=payment.status_message)

        gateway_transaction_id = self._extract_first_text(init_response, "sp_order_id", "spOrderId", "transaction_id")
        payment.checkout_url = checkout_url
        payment.gateway_transaction_id = gateway_transaction_id
        payment.transaction_id = gateway_transaction_id
        payment.sp_message = self._extract_first_text(init_response, "message", "transactionStatus", "status")
        payment.status_message = payment.sp_message
        payment.raw_init_response = self._coerce_json_value(init_response)

        db.add(payment)
        self._record_payment_event(
            db,
            payment=payment,
            event_type="initiated",
            event_source="shurjopay",
            payload={
                "customer_order_id": payment.customer_order_id,
                "gateway_transaction_id": payment.gateway_transaction_id,
                "status": payment.status.value,
            },
        )
        db.commit()
        db.refresh(payment)
        return self.get_payment_for_reference(db, payment_id=payment.id)

    def verify_payment(
        self,
        db: Session,
        *,
        payment_id: str,
        current_user: User | None,
        patient_phone: str | None,
    ) -> Payment:
        payment = self._payment_query(db).filter(Payment.id == payment_id).first()
        if payment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
        self._assert_payment_access(payment, current_user=current_user, patient_phone=patient_phone)
        return self._verify_and_update_payment(db, payment=payment, ipn_payload=None)

    def verify_payment_by_reference(
        self,
        db: Session,
        *,
        order_reference: str,
        ipn_payload: dict[str, Any] | None = None,
        prefer_gateway: bool = False,
    ) -> Payment:
        payment = self._find_payment_by_reference(db, order_reference, prefer_gateway=prefer_gateway)
        if payment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
        return self._verify_and_update_payment(db, payment=payment, ipn_payload=ipn_payload)

    def cancel_payment_by_reference(
        self,
        db: Session,
        *,
        order_reference: str,
        message: str = "Cancelled by customer",
        prefer_gateway: bool = False,
    ) -> Payment | None:
        payment = self._find_payment_by_reference(db, order_reference, prefer_gateway=prefer_gateway)
        if payment is None:
            return None
        if payment.status == PaymentStatus.COMPLETED:
            return payment
        if payment.status != PaymentStatus.CANCELLED or payment.status_message != message:
            payment.status = PaymentStatus.CANCELLED
            payment.bank_status = "cancelled"
            payment.sp_code = payment.sp_code or 1002
            payment.sp_message = message
            payment.status_message = message
            payment.verified_at = payment.verified_at or datetime.now(timezone.utc)
            db.add(payment)
            self._record_payment_event(
                db,
                payment=payment,
                event_type="cancelled",
                event_source="app",
                payload={"message": message, "status": payment.status.value},
            )
            db.commit()
            db.refresh(payment)
        return payment

    def get_payment_for_reference(self, db: Session, *, payment_id: str) -> Payment:
        payment = self._payment_query(db).filter(Payment.id == payment_id).first()
        if payment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
        return payment

    def find_payment_by_reference(
        self,
        db: Session,
        *,
        order_reference: str,
        prefer_gateway: bool = False,
    ) -> Payment | None:
        return self._find_payment_by_reference(db, order_reference, prefer_gateway=prefer_gateway)

    def build_payment_response(self, payment: Payment) -> PaymentResponse:
        booking = payment.booking
        provider_name = None
        appointment_date = None
        appointment_time = None
        if booking is not None:
            provider_name = booking.provider_name
            if not provider_name and booking.doctor is not None:
                provider_name = (
                    booking.doctor.user.name
                    if booking.doctor.user and booking.doctor.user.name
                    else booking.doctor.display_name
                )
            appointment_date = booking.appointment_date
            appointment_time = booking.appointment_time

        return PaymentResponse(
            id=payment.id,
            booking_id=payment.booking_id,
            user_id=payment.user_id,
            amount=payment.amount,
            payable_amount=payment.payable_amount,
            discount_amount=payment.discount_amount,
            received_amount=payment.received_amount,
            currency=payment.currency,
            payment_method=(payment.payment_method or None),
            payment_gateway=payment.payment_gateway,
            status=payment.status,
            transaction_id=payment.transaction_id,
            customer_order_id=payment.customer_order_id,
            order_id=payment.customer_order_id,
            gateway_transaction_id=payment.gateway_transaction_id,
            sp_order_id=payment.gateway_transaction_id,
            bank_transaction_id=payment.bank_transaction_id,
            checkout_url=payment.checkout_url,
            payer_name=payment.payer_name,
            payer_phone=payment.payer_phone,
            payer_email=payment.payer_email,
            customer_name=payment.payer_name,
            customer_phone=payment.payer_phone,
            customer_email=payment.payer_email,
            customer_address=payment.customer_address,
            customer_city=payment.customer_city,
            service_type=payment.service_type,
            service_details=payment.service_details,
            bank_status=payment.bank_status,
            sp_code=payment.sp_code,
            sp_message=payment.sp_message,
            status_message=payment.status_message,
            provider_name=provider_name,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            transaction_date=payment.transaction_date,
            verified_at=payment.verified_at,
            paid_at=payment.paid_at,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
            raw_init_payload=payment.raw_init_payload,
            raw_init_response=payment.raw_init_response,
            raw_verify_response=payment.raw_verify_response,
            raw_ipn_payload=payment.raw_ipn_payload,
            raw_response=payment.raw_verify_response,
        )

    def _verify_and_update_payment(
        self,
        db: Session,
        *,
        payment: Payment,
        ipn_payload: dict[str, Any] | None,
    ) -> Payment:
        client = self._create_client()
        references = self._unique_references(
            payment.gateway_transaction_id,
            payment.transaction_id,
            payment.customer_order_id,
        )
        if not references:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment does not have a verifiable reference")

        verify_response = None
        last_error: ShurjoPayError | None = None
        for reference in references:
            try:
                verify_response = client.verify_payment(reference)
                if verify_response:
                    break
            except ShurjoPayError as exc:
                last_error = exc

        if verify_response is None:
            if payment.status != PaymentStatus.COMPLETED:
                payment.status = PaymentStatus.FAILED
            payment.status_message = str(last_error or "Unable to verify payment")
            payment.sp_message = payment.status_message
            payment.verified_at = datetime.now(timezone.utc)
            if ipn_payload is not None:
                payment.raw_ipn_payload = self._coerce_json_value(ipn_payload)
            db.add(payment)
            self._record_payment_event(
                db,
                payment=payment,
                event_type="verify_failed",
                event_source=("ipn" if ipn_payload is not None else "verify_api"),
                payload={"error": payment.status_message},
            )
            db.commit()
            db.refresh(payment)
            raise HTTPException(
                status_code=(last_error.status_code if last_error else status.HTTP_502_BAD_GATEWAY),
                detail=payment.status_message,
            )

        record = self._extract_verification_record(verify_response)
        sp_code = self._extract_first_int(verify_response, "sp_code") or self._extract_first_int(record, "sp_code")
        normalized_status = self._normalize_status(
            record.get("transaction_status")
            or record.get("transactionStatus")
            or record.get("status")
            or record.get("bank_status"),
            sp_code=sp_code,
        )
        payable_amount = self._coerce_decimal(record.get("payable_amount") or record.get("amount") or payment.amount)
        discount_amount = self._coerce_decimal(record.get("discount_amount") or payment.discount_amount)
        received_amount = self._coerce_decimal(
            record.get("received_amount")
            or record.get("recived_amount")
            or payable_amount
            or payment.amount
        )
        date_time_value = self._parse_datetime(record.get("date_time") or record.get("dateTime"))
        gateway_transaction_id = self._extract_first_text(record, "sp_order_id", "spOrderId") or payment.gateway_transaction_id
        bank_transaction_id = self._extract_first_text(record, "bank_trx_id", "bank_trnx_id", "bankTrxId")
        payment_method = self._extract_first_text(record, "method", "payment_method", "paymentMethod")
        bank_status = self._extract_first_text(record, "bank_status", "bankStatus")
        sp_message = (
            self._extract_first_text(record, "sp_message", "sp_massage", "message", "status")
            or self._extract_first_text(verify_response, "message")
            or bank_status
        )
        customer_name = self._extract_first_text(record, "name") or payment.payer_name
        customer_email = self._extract_first_text(record, "email") or payment.payer_email
        customer_address = self._extract_first_text(record, "address") or payment.customer_address
        customer_city = self._extract_first_text(record, "city") or payment.customer_city

        payment.status = normalized_status
        payment.payment_gateway = "shurjopay"
        payment.amount = payment.amount if payment.amount > 0 else payable_amount
        payment.payable_amount = payable_amount if payable_amount > 0 else payment.amount
        payment.discount_amount = discount_amount if discount_amount >= 0 else Decimal("0.00")
        payment.received_amount = received_amount if received_amount > 0 else payment.received_amount
        payment.currency = self._extract_first_text(record, "currency") or payment.currency or settings.SHURJOPAY_DEFAULT_CURRENCY
        payment.payment_method = (payment_method or "").strip()
        payment.gateway_transaction_id = gateway_transaction_id
        payment.transaction_id = gateway_transaction_id
        payment.bank_transaction_id = bank_transaction_id
        payment.bank_status = bank_status
        payment.sp_code = sp_code
        payment.sp_message = sp_message
        payment.status_message = sp_message
        payment.payer_name = customer_name
        payment.payer_email = customer_email
        payment.customer_address = customer_address
        payment.customer_city = customer_city
        payment.raw_verify_response = self._coerce_json_value(verify_response)
        if ipn_payload is not None:
            payment.raw_ipn_payload = self._coerce_json_value(ipn_payload)
        payment.transaction_date = date_time_value or payment.transaction_date
        payment.verified_at = datetime.now(timezone.utc)
        if normalized_status == PaymentStatus.COMPLETED:
            payment.paid_at = payment.paid_at or date_time_value or payment.verified_at
        elif payment.status != PaymentStatus.COMPLETED:
            payment.paid_at = None

        db.add(payment)
        self._record_payment_event(
            db,
            payment=payment,
            event_type="verified",
            event_source=("ipn" if ipn_payload is not None else "verify_api"),
            payload={
                "status": payment.status.value,
                "gateway_transaction_id": payment.gateway_transaction_id,
                "bank_transaction_id": payment.bank_transaction_id,
                "sp_code": payment.sp_code,
            },
        )
        db.commit()
        db.refresh(payment)
        return self.get_payment_for_reference(db, payment_id=payment.id)

    def _payment_query(self, db: Session):
        return db.query(Payment).options(
            joinedload(Payment.booking).joinedload(Booking.doctor).joinedload(Doctor.user),
            joinedload(Payment.booking).joinedload(Booking.user).joinedload(User.profile),
            joinedload(Payment.user).joinedload(User.profile),
        )

    def _booking_query(self, db: Session):
        return db.query(Booking).options(
            joinedload(Booking.user).joinedload(User.profile),
            joinedload(Booking.doctor).joinedload(Doctor.user),
            joinedload(Booking.hospital),
        )

    def _apply_role_scope(self, payment_query, current_user: User):
        if current_user.role == UserRole.ADMIN:
            return payment_query
        if current_user.role == UserRole.DOCTOR:
            doctor_profile = current_user.doctor_profile
            if doctor_profile is None:
                return payment_query.filter(false())
            return payment_query.join(Payment.booking).filter(Booking.doctor_id == doctor_profile.id)
        return payment_query.filter(Payment.user_id == current_user.id)

    def _apply_payment_filters(
        self,
        payment_query,
        *,
        status_filter: PaymentStatus | None = None,
        method: str | None = None,
        query: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        booking_id: str | None = None,
        user_id: str | None = None,
    ):
        payment_timestamp = self._payment_timestamp_expression()
        if status_filter:
            payment_query = payment_query.filter(Payment.status == status_filter)
        if method:
            payment_query = payment_query.filter(func.lower(func.coalesce(Payment.payment_method, "")) == method.strip().lower())
        if booking_id:
            payment_query = payment_query.filter(Payment.booking_id == booking_id.strip())
        if user_id:
            payment_query = payment_query.filter(Payment.user_id == user_id.strip())
        if date_from:
            start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            payment_query = payment_query.filter(payment_timestamp >= start)
        if date_to:
            end = datetime.combine(date_to, time.max, tzinfo=timezone.utc)
            payment_query = payment_query.filter(payment_timestamp <= end)
        if query:
            normalized = f"%{query.strip().lower()}%"
            payment_query = payment_query.filter(
                or_(
                    func.lower(func.coalesce(Payment.payer_name, "")).like(normalized),
                    func.lower(func.coalesce(Payment.payer_phone, "")).like(normalized),
                    func.lower(func.coalesce(Payment.payer_email, "")).like(normalized),
                    func.lower(func.coalesce(Payment.customer_order_id, "")).like(normalized),
                    func.lower(func.coalesce(Payment.gateway_transaction_id, "")).like(normalized),
                    func.lower(func.coalesce(Payment.bank_transaction_id, "")).like(normalized),
                    func.lower(func.coalesce(Payment.booking_id, "")).like(normalized),
                    func.lower(func.coalesce(Payment.service_type, "")).like(normalized),
                    func.lower(func.coalesce(Payment.sp_message, "")).like(normalized),
                    func.lower(func.coalesce(Payment.status_message, "")).like(normalized),
                )
            )
        return payment_query

    def _apply_sorting(self, payment_query, *, sort_by: str | None, sort_order: str | None):
        sort_key = str(sort_by or "created_at").strip().lower()
        sort_direction = str(sort_order or "desc").strip().lower()
        sort_mapping = {
            "created_at": Payment.created_at,
            "updated_at": Payment.updated_at,
            "amount": Payment.amount,
            "status": Payment.status,
            "transaction_date": Payment.transaction_date,
            "verified_at": Payment.verified_at,
            "received_amount": Payment.received_amount,
        }
        sort_column = sort_mapping.get(sort_key, Payment.created_at)
        return payment_query.order_by(sort_column.asc() if sort_direction == "asc" else sort_column.desc())

    def _paginate_query(self, payment_query, *, page: int, page_size: int) -> tuple[list[Payment], int, int, int]:
        safe_page = max(1, page)
        safe_page_size = max(1, min(page_size, self.MAX_PAGE_SIZE))
        total = payment_query.order_by(None).count()
        items = (
            payment_query
            .limit(safe_page_size)
            .offset((safe_page - 1) * safe_page_size)
            .all()
        )
        return items, total, safe_page, safe_page_size

    def _payment_timestamp_expression(self):
        return func.coalesce(Payment.transaction_date, Payment.verified_at, Payment.paid_at, Payment.created_at)

    def _assert_admin(self, current_user: User) -> None:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

    def _assert_booking_payment_access(
        self,
        booking: Booking,
        *,
        current_user: User | None,
        patient_phone: str | None,
    ) -> None:
        if current_user is not None:
            if current_user.role == UserRole.ADMIN:
                return
            if booking.user_id != current_user.id:
                booking_user = booking.user
                booking_phone_norm = self._normalize_phone(booking.patient_phone)
                request_phone_norm = self._normalize_phone(patient_phone)
                if (
                    booking_user is not None
                    and booking_user.username == self.GUEST_BOOKING_USERNAME
                    and booking_phone_norm == request_phone_norm
                ):
                    return
                logger.warning(
                    "Payment 403 (auth): booking.user_id=%s current_user.id=%s booking_user.username=%s "
                    "booking_phone_norm=%s request_phone_norm=%s",
                    booking.user_id,
                    current_user.id,
                    getattr(booking_user, "username", None),
                    booking_phone_norm,
                    request_phone_norm,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Booking belongs to a different user. "
                        f"booking_user_id={booking.user_id} current_user_id={current_user.id}"
                    ),
                )
            return

        booking_user = booking.user
        if booking_user is None or booking_user.username != self.GUEST_BOOKING_USERNAME:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        booking_phone_norm = self._normalize_phone(booking.patient_phone)
        request_phone_norm = self._normalize_phone(patient_phone)
        if booking_phone_norm != request_phone_norm:
            logger.warning(
                "Payment 403 (guest): booking_phone=%r request_phone=%r booking_phone_raw=%r",
                booking_phone_norm,
                request_phone_norm,
                booking.patient_phone,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Guest payment phone verification failed. "
                    f"booking_phone={booking_phone_norm!r} request_phone={request_phone_norm!r}"
                ),
            )

    def _assert_payment_access(
        self,
        payment: Payment,
        *,
        current_user: User | None,
        patient_phone: str | None,
    ) -> None:
        if current_user is not None:
            if current_user.role == UserRole.ADMIN:
                return
            if current_user.role == UserRole.DOCTOR:
                doctor_profile = current_user.doctor_profile
                if doctor_profile and payment.booking and payment.booking.doctor_id == doctor_profile.id:
                    return
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
            if payment.user_id != current_user.id:
                booking_user = payment.booking.user if payment.booking is not None else None
                if (
                    booking_user is not None
                    and booking_user.username == self.GUEST_BOOKING_USERNAME
                    and self._normalize_phone(payment.payer_phone or payment.booking.patient_phone) == self._normalize_phone(patient_phone)
                ):
                    return
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
            return

        if payment.booking is None or payment.booking.user is None or payment.booking.user.username != self.GUEST_BOOKING_USERNAME:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        if self._normalize_phone(payment.payer_phone or payment.booking.patient_phone) != self._normalize_phone(patient_phone):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guest payment verification failed")

    def _find_payment_by_reference(
        self,
        db: Session,
        order_reference: str,
        *,
        prefer_gateway: bool = False,
    ) -> Payment | None:
        reference = str(order_reference or "").strip()
        if not reference:
            return None
        candidates = (
            [Payment.gateway_transaction_id, Payment.transaction_id, Payment.customer_order_id]
            if prefer_gateway
            else [Payment.customer_order_id, Payment.gateway_transaction_id, Payment.transaction_id]
        )
        for column in candidates:
            payment = self._payment_query(db).filter(column == reference).first()
            if payment is not None:
                return payment
        return None

    def _resolve_amount(self, booking: Booking, requested_amount: Decimal, *, existing_payment: Payment | None) -> Decimal:
        doctor_fee = None
        if booking.doctor and booking.doctor.consultation_fee is not None:
            doctor_fee = self._coerce_decimal(booking.doctor.consultation_fee)
        amount_candidates = [
            doctor_fee,
            self._coerce_decimal(requested_amount),
            self._coerce_decimal(existing_payment.payable_amount if existing_payment else None),
            self._coerce_decimal(existing_payment.amount if existing_payment else None),
        ]
        for candidate in amount_candidates:
            if candidate > 0:
                return candidate.quantize(Decimal("0.01"))
        return Decimal("0.00")

    def _build_customer_order_id(self, booking: Booking) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        user_fragment = (booking.user_id or "user")[:8]
        return f"{settings.SHURJOPAY_ORDER_PREFIX}-{timestamp}-{user_fragment}"

    def _build_payer_snapshot(self, booking: Booking) -> dict[str, str]:
        user = booking.user
        profile: Profile | None = user.profile if user is not None else None
        payer_name = (
            str(booking.patient_name or "").strip()
            or str(profile.full_name if profile else "").strip()
            or str(user.name if user else "").strip()
            or "HealthSynch Patient"
        )
        payer_phone = self._normalize_phone(booking.patient_phone) or self._normalize_phone(profile.phone if profile else None) or "01700000000"
        payer_email = str(user.email if user else "").strip() or "guest-booking@healthsync.example.com"
        customer_address = (
            str(profile.address if profile else "").strip()
            or str(booking.location_address or "").strip()
            or "Dhaka"
        )
        customer_city = str(profile.city if profile else "").strip() or settings.SHURJOPAY_DEFAULT_CITY
        customer_post_code = settings.SHURJOPAY_DEFAULT_POST_CODE

        return {
            "payer_name": payer_name,
            "payer_phone": payer_phone,
            "payer_email": payer_email,
            "customer_address": customer_address,
            "customer_city": customer_city,
            "customer_post_code": customer_post_code,
        }

    def _build_service_details(
        self,
        booking: Booking,
        *,
        normalized_service_type: str,
        service_details: dict[str, Any] | None,
        value1: str | None,
        value2: str | None,
        value3: str | None,
        value4: str | None,
    ) -> dict[str, Any]:
        base_details: dict[str, Any] = {
            "service_type": normalized_service_type,
            "booking_id": booking.id,
            "doctor_id": booking.doctor_id,
            "provider_name": booking.provider_name,
            "provider_external_id": booking.provider_external_id,
            "location_name": booking.location_name,
            "location_address": booking.location_address,
            "appointment_date": booking.appointment_date.isoformat() if booking.appointment_date else None,
            "appointment_time": booking.appointment_time.isoformat() if booking.appointment_time else None,
            "booking_type": booking.booking_type.value if booking.booking_type else None,
        }
        if service_details:
            base_details.update(service_details)
        gateway_values = {
            key: value
            for key, value in {
                "value1": value1,
                "value2": value2,
                "value3": value3,
                "value4": value4,
            }.items()
            if str(value or "").strip()
        }
        if gateway_values:
            base_details["gateway_values"] = gateway_values
        return base_details

    def _effective_revenue_amount(self, payment: Payment) -> Decimal:
        for value in (payment.received_amount, payment.payable_amount, payment.amount):
            coerced = self._coerce_decimal(value)
            if coerced > 0:
                return coerced
        return Decimal("0.00")

    def _payment_activity_datetime(self, payment: Payment) -> datetime | None:
        return payment.transaction_date or payment.verified_at or payment.paid_at or payment.created_at

    def _extract_checkout_url(self, payload: dict[str, Any]) -> str | None:
        for key in ("checkout_url", "checkout_url_mobile", "checkout_url_iframe", "gateway_url"):
            value = self._extract_first_text(payload, key)
            if value:
                return value
        return None

    def _extract_verification_record(self, verify_response: Any) -> dict[str, Any]:
        if isinstance(verify_response, list) and verify_response:
            first = verify_response[0]
            return first if isinstance(first, dict) else {}
        if isinstance(verify_response, dict):
            data = verify_response.get("data")
            if isinstance(data, list) and data:
                first = data[0]
                return first if isinstance(first, dict) else {}
            return verify_response
        return {}

    def _normalize_status(self, raw_status: Any, *, sp_code: int | None = None) -> PaymentStatus:
        if sp_code == 1002:
            return PaymentStatus.CANCELLED
        if sp_code == 1001:
            return PaymentStatus.FAILED
        if sp_code in {1000, 200} and not str(raw_status or "").strip():
            return PaymentStatus.COMPLETED

        normalized = str(raw_status or "").strip().lower()
        if normalized in {"completed", "complete", "successful", "success", "succeeded", "paid"}:
            return PaymentStatus.COMPLETED
        if normalized in {"refunded", "refund"}:
            return PaymentStatus.REFUNDED
        if normalized in {"pending", "processing", "initiated", "created"}:
            return PaymentStatus.PENDING
        if normalized in {"cancelled", "canceled"}:
            return PaymentStatus.CANCELLED
        if normalized in {"failed", "declined", "rejected", "unsuccessful"}:
            return PaymentStatus.FAILED
        return PaymentStatus.PENDING

    def _coerce_json_value(self, payload: Any) -> Any:
        if payload is None:
            return None
        if isinstance(payload, (dict, list, str, int, float, bool)):
            return payload
        return {"raw": str(payload)}

    def _coerce_decimal(self, value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if value in {None, ""}:
            return Decimal("0.00")
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0.00")

    def _format_decimal(self, value: Decimal | None) -> str:
        coerced = self._coerce_decimal(value)
        return format(coerced.quantize(Decimal("0.01")), "f")

    def _parse_datetime(self, raw_value: Any) -> datetime | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, datetime):
            return raw_value if raw_value.tzinfo else raw_value.replace(tzinfo=timezone.utc)

        text = str(raw_value).strip()
        if not text:
            return None

        iso_candidate = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso_candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %I:%M:%S%p",
            "%Y-%m-%d %I:%M:%S %p",
            "%Y-%m-%d %H:%M:%S%z",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def _normalize_phone(self, value: Any) -> str:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if digits.startswith("8801") and len(digits) == 13:
            return f"0{digits[3:]}"
        return digits

    def _unique_references(self, *values: str | None) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _extract_first_text(self, payload: Any, *keys: str) -> str | None:
        if not isinstance(payload, dict):
            return None
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _extract_first_int(self, payload: Any, *keys: str) -> int | None:
        text = self._extract_first_text(payload, *keys)
        if text is None:
            return None
        try:
            return int(text)
        except ValueError:
            return None
