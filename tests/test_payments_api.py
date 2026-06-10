from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.booking import Booking
from app.models.doctor import Doctor
from app.models.enums import BookingStatus, BookingType, PaymentStatus, UserRole
from app.models.hospital import Hospital
from app.models.payment import Payment
from app.models.profile import Profile
from app.models.user import User
from app.services.auth_service import get_auth_service
from app.services.payment_service import PaymentService


class _StubShurjoPayClient:
    def __init__(self) -> None:
        self.initiate_calls: list[dict] = []
        self.verify_calls: list[str] = []
        self.initiate_queue: list[dict] = []
        self.verify_responses: dict[str, object] = {}

    def initiate_payment(self, checkout_payload: dict, *, return_url: str, cancel_url: str) -> dict:
        self.initiate_calls.append(
            {
                "checkout_payload": checkout_payload,
                "return_url": return_url,
                "cancel_url": cancel_url,
            }
        )
        if not self.initiate_queue:
            raise AssertionError("No queued ShurjoPay initiate response")
        return self.initiate_queue.pop(0)

    def verify_payment(self, reference: str):
        self.verify_calls.append(reference)
        if reference not in self.verify_responses:
            raise AssertionError(f"No queued ShurjoPay verify response for {reference}")
        return self.verify_responses[reference]


@pytest.fixture
def client_and_session(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker, _StubShurjoPayClient], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    testing_session_local = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    stub_client = _StubShurjoPayClient()
    monkeypatch.setattr(PaymentService, "_create_client", lambda self: stub_client)

    original_admin_bootstrap = settings.ADMIN_BOOTSTRAP_ENABLED
    original_order_prefix = settings.SHURJOPAY_ORDER_PREFIX
    original_frontend_url = settings.FRONTEND_URL
    settings.ADMIN_BOOTSTRAP_ENABLED = False
    settings.SHURJOPAY_ORDER_PREFIX = "HES"
    settings.FRONTEND_URL = "http://localhost:3000"
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client, testing_session_local, stub_client

    settings.ADMIN_BOOTSTRAP_ENABLED = original_admin_bootstrap
    settings.SHURJOPAY_ORDER_PREFIX = original_order_prefix
    settings.FRONTEND_URL = original_frontend_url
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _create_user(
    db: Session,
    *,
    name: str,
    email: str,
    username: str,
    password: str,
    role: UserRole,
    verified: bool = True,
) -> User:
    user = User(
        name=name,
        email=email,
        username=username,
        password_hash=get_auth_service().hash_password(password),
        role=role,
        is_active=True,
        is_verified=verified,
    )
    db.add(user)
    db.flush()
    return user


def _seed_payment_data(db: Session) -> dict[str, object]:
    admin_user = _create_user(
        db,
        name="Admin User",
        email="admin@example.com",
        username="admin-user",
        password="StrongPass1",
        role=UserRole.ADMIN,
    )
    doctor_user = _create_user(
        db,
        name="Dr. Samiha Rahman",
        email="doctor@example.com",
        username="doctor-user",
        password="StrongPass1",
        role=UserRole.DOCTOR,
    )
    patient_user = _create_user(
        db,
        name="Patient User",
        email="patient@example.com",
        username="patient-user",
        password="StrongPass1",
        role=UserRole.USER,
    )
    guest_user = _create_user(
        db,
        name="Guest Booking User",
        email="guest-booking@example.com",
        username=PaymentService.GUEST_BOOKING_USERNAME,
        password="StrongPass1",
        role=UserRole.USER,
        verified=False,
    )

    patient_profile = Profile(
        user_id=patient_user.id,
        full_name="Patient User",
        phone="01711111111",
        address="123 Patient Road",
        city="Dhaka",
        country="Bangladesh",
    )
    db.add(patient_profile)
    db.flush()

    hospital = Hospital(
        name="HealthSync General Hospital",
        address="123 Main Street",
        city="Dhaka",
        country="Bangladesh",
        phone="+8801710000000",
        email="care@example.com",
    )
    db.add(hospital)
    db.flush()

    doctor = Doctor(
        user_id=doctor_user.id,
        license_number="BMDC-77777",
        specialization=["Cardiology"],
        experience_years=8,
        consultation_fee=Decimal("1200.00"),
        hospital_id=hospital.id,
        average_rating=4.9,
        available_slots=[{"day": "Monday", "time": "10:00"}],
    )
    db.add(doctor)
    db.flush()

    auth_booking = Booking(
        user_id=patient_user.id,
        doctor_id=doctor.id,
        hospital_id=hospital.id,
        provider_name="Dr. Samiha Rahman",
        location_name=hospital.name,
        location_address=hospital.address,
        appointment_date=date(2026, 5, 20),
        appointment_time=time(10, 30),
        status=BookingStatus.PENDING,
        booking_type=BookingType.ONLINE,
        symptoms_summary="Chest discomfort",
        prescription_ids=[],
    )
    guest_booking = Booking(
        user_id=guest_user.id,
        doctor_id=doctor.id,
        hospital_id=hospital.id,
        provider_name="Dr. Samiha Rahman",
        location_name=hospital.name,
        location_address=hospital.address,
        patient_name_snapshot="Guest Patient",
        patient_phone_snapshot="01722222222",
        patient_sex_snapshot="female",
        appointment_date=date(2026, 5, 22),
        appointment_time=time(14, 0),
        status=BookingStatus.PENDING,
        booking_type=BookingType.IN_PERSON,
        symptoms_summary="Guest booking",
        prescription_ids=[],
    )
    db.add_all([auth_booking, guest_booking])
    db.commit()
    db.refresh(auth_booking)
    db.refresh(guest_booking)

    return {
        "admin_user": admin_user,
        "doctor_user": doctor_user,
        "patient_user": patient_user,
        "guest_user": guest_user,
        "doctor": doctor,
        "auth_booking": auth_booking,
        "guest_booking": guest_booking,
    }


def _login_headers(test_client: TestClient, identifier: str, password: str) -> dict[str, str]:
    response = test_client.post(
        f"{settings.API_V1_STR}/auth/login/access-token",
        data={"username": identifier, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _queue_initiate_response(
    stub_client: _StubShurjoPayClient,
    *,
    checkout_url: str,
    sp_order_id: str,
    customer_order_id: str | None = None,
    message: str = "Initiated",
) -> None:
    stub_client.initiate_queue.append(
        {
            "checkout_url": checkout_url,
            "sp_order_id": sp_order_id,
            "customer_order_id": customer_order_id,
            "message": message,
            "transactionStatus": "Initiated",
        }
    )


def _queue_verify_response(
    stub_client: _StubShurjoPayClient,
    *,
    reference: str,
    transaction_status: str,
    sp_code: int = 1000,
    method: str = "bkash",
    message: str = "Verified",
    bank_status: str | None = None,
) -> None:
    stub_client.verify_responses[reference] = [
        {
            "sp_order_id": reference,
            "transaction_status": transaction_status,
            "sp_code": sp_code,
            "bank_status": bank_status or transaction_status,
            "amount": "1200.00",
            "payable_amount": "1200.00",
            "discount_amount": "0.00",
            "received_amount": "1200.00",
            "method": method,
            "date_time": datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc).isoformat(),
            "message": message,
            "currency": "BDT",
            "bank_trx_id": f"BANK-{reference[-4:]}",
            "name": "Patient User",
            "email": "patient@example.com",
            "address": "123 Patient Road",
            "city": "Dhaka",
        }
    ]


@pytest.mark.parametrize(
    "endpoint",
    [
        f"{settings.API_V1_STR}/payments/initiate",
        f"{settings.API_V1_STR}/payments/shurjopay/initiate",
        "/api/payments/initiate",
    ],
)
def test_authenticated_user_can_initiate_payment_via_primary_and_compat_routes(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
    endpoint: str,
) -> None:
    test_client, testing_session_local, stub_client = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        patient_user = seeded["patient_user"]
        auth_booking = seeded["auth_booking"]

    headers = _login_headers(test_client, patient_user.username, "StrongPass1")
    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/auth-1",
        sp_order_id="SP-AUTH-001",
    )

    response = test_client.post(
        endpoint,
        headers=headers,
        json={
            "booking_id": auth_booking.id,
            "amount": "1200.00",
            "currency": "BDT",
            "service_type": "doctor_booking",
            "service_details": {"source": "doctor-page"},
            "value1": auth_booking.id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["booking_id"] == auth_booking.id
    assert payload["checkout_url"] == "https://engine.shurjopayment.com/checkout/auth-1"
    assert payload["status"] == "pending"
    assert payload["order_id"] == payload["customer_order_id"]
    assert payload["order_id"].startswith("HES-")

    with testing_session_local() as db:
        payment = db.query(Payment).filter(Payment.id == payload["payment_id"]).first()
        assert payment is not None
        assert payment.user_id == patient_user.id
        assert payment.gateway_transaction_id == "SP-AUTH-001"
        assert payment.status == PaymentStatus.PENDING
        assert payment.service_type == "doctor_booking"
        assert payment.service_details["source"] == "doctor-page"
        assert payment.service_details["gateway_values"]["value1"] == auth_booking.id
        assert payment.customer_address == "123 Patient Road"
        assert payment.customer_city == "Dhaka"


def test_guest_booking_can_initiate_payment_when_phone_matches(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
) -> None:
    test_client, testing_session_local, stub_client = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        guest_booking = seeded["guest_booking"]

    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/guest-1",
        sp_order_id="SP-GUEST-001",
    )
    response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        json={
            "booking_id": guest_booking.id,
            "amount": "1200.00",
            "currency": "BDT",
            "patient_phone": "01722222222",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checkout_url"] == "https://engine.shurjopayment.com/checkout/guest-1"

    with testing_session_local() as db:
        payment = db.query(Payment).filter(Payment.id == payload["payment_id"]).first()
        assert payment is not None
        assert payment.payer_name == "Guest Patient"
        assert payment.payer_phone == "01722222222"
        assert payment.gateway_transaction_id == "SP-GUEST-001"


def test_guest_booking_can_initiate_payment_with_authenticated_token_when_phone_matches(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
) -> None:
    test_client, testing_session_local, stub_client = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        patient_user = seeded["patient_user"]
        guest_booking = seeded["guest_booking"]

    headers = _login_headers(test_client, patient_user.username, "StrongPass1")
    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/guest-auth-1",
        sp_order_id="SP-GUEST-AUTH-001",
    )
    response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={
            "booking_id": guest_booking.id,
            "amount": "1200.00",
            "currency": "BDT",
            "patient_phone": "01722222222",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checkout_url"] == "https://engine.shurjopayment.com/checkout/guest-auth-1"

    with testing_session_local() as db:
        payment = db.query(Payment).filter(Payment.id == payload["payment_id"]).first()
        assert payment is not None
        assert payment.booking_id == guest_booking.id
        assert payment.gateway_transaction_id == "SP-GUEST-AUTH-001"


def test_guest_payment_rejects_phone_mismatch(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
) -> None:
    test_client, testing_session_local, stub_client = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        guest_booking = seeded["guest_booking"]

    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/guest-2",
        sp_order_id="SP-GUEST-002",
    )
    response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        json={
            "booking_id": guest_booking.id,
            "amount": "1200.00",
            "currency": "BDT",
            "patient_phone": "01799999999",
        },
    )

    assert response.status_code == 403
    assert "Guest payment" in response.json()["detail"]


def test_pending_failed_and_cancelled_payments_can_retry_but_completed_cannot(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
) -> None:
    test_client, testing_session_local, stub_client = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        patient_user = seeded["patient_user"]
        auth_booking = seeded["auth_booking"]

    headers = _login_headers(test_client, patient_user.username, "StrongPass1")
    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/retry-1",
        sp_order_id="SP-RETRY-001",
    )
    first_response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={"booking_id": auth_booking.id, "amount": "1200.00", "currency": "BDT"},
    )
    assert first_response.status_code == 200
    first_payment_id = first_response.json()["payment_id"]
    first_customer_order = first_response.json()["customer_order_id"]

    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/retry-2",
        sp_order_id="SP-RETRY-002",
    )
    second_response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={"booking_id": auth_booking.id, "amount": "1200.00", "currency": "BDT"},
    )
    assert second_response.status_code == 200
    assert second_response.json()["payment_id"] == first_payment_id
    assert second_response.json()["customer_order_id"] != first_customer_order

    with testing_session_local() as db:
        payment = db.query(Payment).filter(Payment.id == first_payment_id).first()
        assert payment is not None
        payment.status = PaymentStatus.FAILED
        db.add(payment)
        db.commit()

    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/retry-3",
        sp_order_id="SP-RETRY-003",
    )
    third_response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={"booking_id": auth_booking.id, "amount": "1200.00", "currency": "BDT"},
    )
    assert third_response.status_code == 200

    with testing_session_local() as db:
        payment = db.query(Payment).filter(Payment.id == first_payment_id).first()
        assert payment is not None
        payment.status = PaymentStatus.CANCELLED
        db.add(payment)
        db.commit()

    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/retry-4",
        sp_order_id="SP-RETRY-004",
    )
    cancelled_retry = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={"booking_id": auth_booking.id, "amount": "1200.00", "currency": "BDT"},
    )
    assert cancelled_retry.status_code == 200

    with testing_session_local() as db:
        payment = db.query(Payment).filter(Payment.id == first_payment_id).first()
        assert payment is not None
        payment.status = PaymentStatus.COMPLETED
        db.add(payment)
        db.commit()

    rejected_response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={"booking_id": auth_booking.id, "amount": "1200.00", "currency": "BDT"},
    )
    assert rejected_response.status_code == 400
    assert rejected_response.json()["detail"] == "Payment already completed for this booking"


@pytest.mark.parametrize(
    ("remote_status", "sp_code", "expected_status"),
    [
        ("Completed", 1000, "completed"),
        ("Failed", 1001, "failed"),
        ("Cancelled", 1002, "cancelled"),
        ("Pending", 1000, "pending"),
    ],
)
def test_verify_endpoint_updates_payment_statuses(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
    remote_status: str,
    sp_code: int,
    expected_status: str,
) -> None:
    test_client, testing_session_local, stub_client = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        patient_user = seeded["patient_user"]
        auth_booking = seeded["auth_booking"]

    headers = _login_headers(test_client, patient_user.username, "StrongPass1")
    gateway_reference = f"SP-VERIFY-{expected_status.upper()}"
    _queue_initiate_response(
        stub_client,
        checkout_url=f"https://engine.shurjopayment.com/checkout/{expected_status}",
        sp_order_id=gateway_reference,
    )
    initiate_response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={"booking_id": auth_booking.id, "amount": "1200.00", "currency": "BDT"},
    )
    assert initiate_response.status_code == 200
    payment_id = initiate_response.json()["payment_id"]

    _queue_verify_response(
        stub_client,
        reference=gateway_reference,
        transaction_status=remote_status,
        sp_code=sp_code,
        method="nagad",
        message=f"{remote_status} verification",
    )
    verify_response = test_client.post(
        f"{settings.API_V1_STR}/payments/{payment_id}/verify",
        headers=headers,
        json={},
    )

    assert verify_response.status_code == 200
    payload = verify_response.json()
    assert payload["status"] == expected_status
    assert payload["payment_method"] == "nagad"
    assert payload["sp_code"] == sp_code
    assert payload["customer_name"] == "Patient User"
    assert payload["customer_city"] == "Dhaka"
    if expected_status == "completed":
        assert payload["paid_at"] is not None
    else:
        assert payload["verified_at"] is not None


def test_callback_and_legacy_return_are_idempotent_and_redirect_to_result_pages(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
) -> None:
    test_client, testing_session_local, stub_client = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        patient_user = seeded["patient_user"]
        auth_booking = seeded["auth_booking"]

    headers = _login_headers(test_client, patient_user.username, "StrongPass1")
    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/ipn",
        sp_order_id="SP-IPN-001",
    )
    initiate_response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={"booking_id": auth_booking.id, "amount": "1200.00", "currency": "BDT"},
    )
    assert initiate_response.status_code == 200
    payment_id = initiate_response.json()["payment_id"]

    _queue_verify_response(
        stub_client,
        reference="SP-IPN-001",
        transaction_status="Completed",
        method="bkash",
        message="Paid successfully",
    )
    first_ipn = test_client.post(
        f"{settings.API_V1_STR}/payments/shurjopay/ipn?sp_order_id=SP-IPN-001",
        json={"sp_order_id": "SP-IPN-001"},
    )
    second_ipn = test_client.post(
        f"{settings.API_V1_STR}/payments/shurjopay/ipn?sp_order_id=SP-IPN-001",
        json={"sp_order_id": "SP-IPN-001"},
    )
    assert first_ipn.status_code == 200
    assert second_ipn.status_code == 200

    callback_response = test_client.get(
        f"{settings.API_V1_STR}/payments/callback?sp_order_id=SP-IPN-001",
        follow_redirects=False,
    )
    legacy_response = test_client.get(
        f"{settings.API_V1_STR}/payments/shurjopay/return?sp_order_id=SP-IPN-001",
        follow_redirects=False,
    )
    assert callback_response.status_code == 303
    assert legacy_response.status_code == 303
    assert "/payment/success" in callback_response.headers["location"]
    assert "status=completed" in callback_response.headers["location"]
    assert payment_id in callback_response.headers["location"]
    assert "/payment/success" in legacy_response.headers["location"]

    with testing_session_local() as db:
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        assert payment is not None
        assert payment.status == PaymentStatus.COMPLETED
        assert db.query(Payment).count() == 1


def test_cancel_route_marks_payment_cancelled_and_redirects(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
) -> None:
    test_client, testing_session_local, stub_client = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        patient_user = seeded["patient_user"]
        auth_booking = seeded["auth_booking"]

    headers = _login_headers(test_client, patient_user.username, "StrongPass1")
    _queue_initiate_response(
        stub_client,
        checkout_url="https://engine.shurjopayment.com/checkout/cancel",
        sp_order_id="SP-CANCEL-001",
    )
    initiate_response = test_client.post(
        f"{settings.API_V1_STR}/payments/initiate",
        headers=headers,
        json={"booking_id": auth_booking.id, "amount": "1200.00", "currency": "BDT"},
    )
    assert initiate_response.status_code == 200
    payment_id = initiate_response.json()["payment_id"]

    cancel_response = test_client.get(
        f"{settings.API_V1_STR}/payments/cancel?sp_order_id=SP-CANCEL-001",
        follow_redirects=False,
    )
    assert cancel_response.status_code == 303
    assert "/payment/cancelled" in cancel_response.headers["location"]
    assert "status=cancelled" in cancel_response.headers["location"]

    with testing_session_local() as db:
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        assert payment is not None
        assert payment.status == PaymentStatus.CANCELLED
        assert payment.sp_code == 1002


def test_payment_history_admin_list_stats_detail_and_export_work(
    client_and_session: tuple[TestClient, sessionmaker, _StubShurjoPayClient],
) -> None:
    test_client, testing_session_local, _ = client_and_session
    with testing_session_local() as db:
        seeded = _seed_payment_data(db)
        admin_user = seeded["admin_user"]
        patient_user = seeded["patient_user"]
        guest_user = seeded["guest_user"]
        auth_booking = seeded["auth_booking"]
        guest_booking = seeded["guest_booking"]

        user_payment = Payment(
            booking_id=auth_booking.id,
            user_id=patient_user.id,
            amount=Decimal("1200.00"),
            payable_amount=Decimal("1200.00"),
            discount_amount=Decimal("0.00"),
            received_amount=Decimal("1200.00"),
            currency="BDT",
            payment_method="bkash",
            payment_gateway="shurjopay",
            status=PaymentStatus.COMPLETED,
            customer_order_id="HES-USER-001",
            gateway_transaction_id="SP-GATE-USER-001",
            transaction_id="SP-GATE-USER-001",
            bank_transaction_id="BANK-0001",
            bank_status="Completed",
            sp_code=1000,
            sp_message="Paid",
            payer_name="Patient User",
            payer_phone="01711111111",
            payer_email="patient@example.com",
            customer_address="123 Patient Road",
            customer_city="Dhaka",
            service_type="doctor_booking",
            service_details={"source": "seed"},
            status_message="Paid",
            transaction_date=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
            verified_at=datetime(2026, 5, 11, 12, 1, tzinfo=timezone.utc),
            paid_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
            raw_verify_response={"sp_code": 1000},
            created_at=datetime(2026, 5, 11, 11, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 11, 12, 1, tzinfo=timezone.utc),
        )
        guest_payment = Payment(
            booking_id=guest_booking.id,
            user_id=guest_user.id,
            amount=Decimal("1200.00"),
            payable_amount=Decimal("1200.00"),
            discount_amount=Decimal("0.00"),
            received_amount=None,
            currency="BDT",
            payment_method="nagad",
            payment_gateway="shurjopay",
            status=PaymentStatus.FAILED,
            customer_order_id="HES-GUEST-101",
            gateway_transaction_id="SP-GATE-GUEST-101",
            transaction_id="SP-GATE-GUEST-101",
            bank_transaction_id="BANK-0101",
            bank_status="Failed",
            sp_code=1001,
            sp_message="Failed",
            payer_name="Guest Patient",
            payer_phone="01722222222",
            payer_email="guest-booking@example.com",
            customer_address="Main Street",
            customer_city="Dhaka",
            service_type="doctor_booking",
            service_details={"source": "seed"},
            status_message="Failed",
            raw_verify_response={"sp_code": 1001},
            created_at=datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 10, 10, 15, tzinfo=timezone.utc),
        )
        db.add_all([user_payment, guest_payment])
        db.commit()

    admin_headers = _login_headers(test_client, admin_user.username, "StrongPass1")
    user_headers = _login_headers(test_client, patient_user.username, "StrongPass1")

    history_response = test_client.get(
        f"{settings.API_V1_STR}/payments/history?page=1&page_size=1",
        headers=user_headers,
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()
    assert history_payload["total"] == 1
    assert len(history_payload["items"]) == 1
    assert history_payload["items"][0]["user_id"] == patient_user.id

    admin_list_response = test_client.get(
        f"{settings.API_V1_STR}/admin/payments?page=1&page_size=10&status=completed&method=bkash&query=SP-GATE-USER-001",
        headers=admin_headers,
    )
    assert admin_list_response.status_code == 200
    admin_payload = admin_list_response.json()
    assert admin_payload["total"] == 1
    assert admin_payload["items"][0]["sp_order_id"] == "SP-GATE-USER-001"
    assert admin_payload["items"][0]["provider_name"] == "Dr. Samiha Rahman"

    detail_response = test_client.get(
        f"{settings.API_V1_STR}/admin/payments/{admin_payload['items'][0]['id']}",
        headers=admin_headers,
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["raw_response"] == {"sp_code": 1000}

    stats_response = test_client.get(
        f"{settings.API_V1_STR}/admin/payments/stats",
        headers=admin_headers,
    )
    assert stats_response.status_code == 200
    stats_payload = stats_response.json()
    assert stats_payload["total_transactions"] == 2
    assert stats_payload["completed_transactions"] == 1
    assert stats_payload["failed_transactions"] == 1
    assert stats_payload["cancelled_transactions"] == 0
    assert Decimal(stats_payload["total_revenue"]) == Decimal("1200.00")

    export_response = test_client.get(
        f"{settings.API_V1_STR}/admin/payments/export",
        headers=admin_headers,
    )
    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("text/csv")
    assert "payment_id" in export_response.text
    assert "SP-GATE-USER-001" in export_response.text
