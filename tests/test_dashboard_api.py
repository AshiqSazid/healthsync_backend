from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, time, timedelta, timezone
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
from app.models.assessment_document import AssessmentDocument
from app.models.booking import Booking
from app.models.diagnostic import Diagnostic
from app.models.doctor import Doctor
from app.models.enums import BookingStatus, BookingType, UserRole
from app.models.hospital import Hospital
from app.models.profile import Profile
from app.models.user import User
from app.services.auth_service import get_auth_service


@pytest.fixture
def client_and_session() -> Generator[tuple[TestClient, sessionmaker], None, None]:
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

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client, testing_session_local

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
) -> User:
    user = User(
        name=name,
        email=email,
        username=username,
        password_hash=get_auth_service().hash_password(password),
        role=role,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()
    return user


def _seed_dashboard_data(db: Session) -> dict[str, object]:
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
        name="Dr. Ayesha Rahman",
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

    hospital = Hospital(
        name="HealthSync General Hospital",
        address="123 Main Street",
        city="Dhaka",
        country="Bangladesh",
        phone="+8801700000000",
        email="contact@hospital.test",
    )
    db.add(hospital)
    db.flush()

    doctor = Doctor(
        user_id=doctor_user.id,
        license_number="BMDC-12345",
        specialization=["Cardiology"],
        experience_years=12,
        consultation_fee=Decimal("1200.00"),
        hospital_id=hospital.id,
        average_rating=4.8,
        available_slots=[{"day": "Monday", "time": "10:00"}],
    )
    db.add(doctor)
    db.flush()

    today = datetime.now(timezone.utc).date()
    booking_one = Booking(
        user_id=patient_user.id,
        doctor_id=doctor.id,
        hospital_id=hospital.id,
        appointment_date=today,
        appointment_time=time(10, 0),
        status=BookingStatus.PENDING,
        booking_type=BookingType.ONLINE,
        symptoms_summary="Chest discomfort",
        prescription_ids=[],
    )
    booking_two = Booking(
        user_id=patient_user.id,
        doctor_id=doctor.id,
        hospital_id=hospital.id,
        appointment_date=today + timedelta(days=1),
        appointment_time=time(14, 0),
        status=BookingStatus.CONFIRMED,
        booking_type=BookingType.IN_PERSON,
        symptoms_summary="Follow-up review",
        prescription_ids=[],
    )
    profile = Profile(
        user_id=patient_user.id,
        full_name="Patient User",
        phone="+8801711111111",
        city="Dhaka",
        country="Bangladesh",
        blood_group="B+",
    )
    diagnostic = Diagnostic(
        user_id=patient_user.id,
        doctor_id=doctor.id,
        diagnosis="Stable angina",
        follow_up_date=today + timedelta(days=7),
        notes="Continue medication and review symptoms",
    )
    db.add_all([booking_one, booking_two, profile, diagnostic])
    db.commit()

    return {
        "admin_user": admin_user,
        "doctor_user": doctor_user,
        "patient_user": patient_user,
        "doctor": doctor,
        "hospital": hospital,
    }


def _login_headers(test_client: TestClient, identifier: str, password: str) -> dict[str, str]:
    login_response = test_client.post(
        f"{settings.API_V1_STR}/auth/login/access-token",
        data={"username": identifier, "password": password},
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def test_dashboard_me_returns_admin_context(client_and_session: tuple[TestClient, sessionmaker]) -> None:
    test_client, testing_session_local = client_and_session
    with testing_session_local() as db:
        seeded = _seed_dashboard_data(db)
        admin_user = seeded["admin_user"]
        doctor = seeded["doctor"]

    login_response = test_client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"email": admin_user.email, "password": "StrongPass1"},
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]

    dashboard_response = test_client.get(
        f"{settings.API_V1_STR}/dashboard/context",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert dashboard_response.status_code == 200
    payload = dashboard_response.json()
    assert payload["role"] == "admin"
    assert payload["available_interfaces"] == ["admin"]
    assert payload["user"]["role"] == "admin"
    assert payload["doctor"] is None
    assert payload["admin"]["counts"] == {
        "total_users": 3,
        "total_doctors": 1,
        "total_hospitals": 1,
        "total_bookings": 2,
        "pending_bookings": 1,
        "confirmed_bookings": 1,
        "completed_bookings": 0,
        "cancelled_bookings": 0,
    }
    assert payload["admin"]["recent_users"][0]["email"] == "patient@example.com"
    assert payload["admin"]["recent_doctors"][0]["id"] == doctor.id
    assert payload["admin"]["recent_doctors"][0]["display_name"] == "Dr. Ayesha Rahman"
    assert payload["admin"]["recent_bookings"][0]["patient_name"] == "Patient User"


def test_dashboard_me_returns_doctor_context(client_and_session: tuple[TestClient, sessionmaker]) -> None:
    test_client, testing_session_local = client_and_session
    with testing_session_local() as db:
        seeded = _seed_dashboard_data(db)
        doctor_user = seeded["doctor_user"]
        doctor = seeded["doctor"]
        hospital = seeded["hospital"]

    login_response = test_client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"identifier": doctor_user.username, "password": "StrongPass1"},
    )
    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["user"]["role"] == "doctor"
    assert payload["user"]["doctor_profile_id"] == doctor.id

    dashboard_response = test_client.get(
        f"{settings.API_V1_STR}/dashboard/context",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )

    assert dashboard_response.status_code == 200
    dashboard_payload = dashboard_response.json()
    assert dashboard_payload["role"] == "doctor"
    assert dashboard_payload["available_interfaces"] == ["doctor"]
    assert dashboard_payload["admin"] is None
    assert dashboard_payload["doctor"]["doctor_profile"]["id"] == doctor.id
    assert dashboard_payload["doctor"]["doctor_profile"]["display_name"] == "Dr. Ayesha Rahman"
    assert dashboard_payload["doctor"]["hospital"]["id"] == hospital.id
    assert dashboard_payload["doctor"]["hospital"]["name"] == "HealthSync General Hospital"
    assert dashboard_payload["doctor"]["booking_counts"] == {
        "total_bookings": 2,
        "pending_bookings": 1,
        "confirmed_bookings": 1,
        "completed_bookings": 0,
        "cancelled_bookings": 0,
        "today_bookings": 1,
    }
    assert len(dashboard_payload["doctor"]["upcoming_bookings"]) == 2
    assert len(dashboard_payload["doctor"]["recent_bookings"]) == 2
    assert dashboard_payload["doctor"]["upcoming_bookings"][0]["doctor_name"] == "Dr. Ayesha Rahman"
    assert dashboard_payload["doctor"]["upcoming_bookings"][0]["hospital_name"] == "HealthSync General Hospital"


def test_dashboard_me_returns_user_context(client_and_session: tuple[TestClient, sessionmaker]) -> None:
    test_client, testing_session_local = client_and_session
    with testing_session_local() as db:
        seeded = _seed_dashboard_data(db)
        patient_user = seeded["patient_user"]

    login_response = test_client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"identifier": patient_user.username, "password": "StrongPass1"},
    )
    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["user"]["role"] == "user"
    assert payload["user"]["doctor_profile_id"] is None

    dashboard_response = test_client.get(
        f"{settings.API_V1_STR}/dashboard/context",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )

    assert dashboard_response.status_code == 200
    dashboard_payload = dashboard_response.json()
    assert dashboard_payload["role"] == "user"
    assert dashboard_payload["available_interfaces"] == ["user"]
    assert dashboard_payload["admin"] is None
    assert dashboard_payload["doctor"] is None
    assert dashboard_payload["user_dashboard"]["has_profile"] is True
    assert dashboard_payload["user_dashboard"]["profile"]["full_name"] == "Patient User"
    assert dashboard_payload["user_dashboard"]["profile"]["city"] == "Dhaka"
    assert dashboard_payload["user_dashboard"]["booking_counts"] == {
        "total_bookings": 2,
        "pending_bookings": 1,
        "confirmed_bookings": 1,
        "completed_bookings": 0,
        "cancelled_bookings": 0,
        "total_diagnostics": 1,
    }
    assert len(dashboard_payload["user_dashboard"]["upcoming_bookings"]) == 2
    assert len(dashboard_payload["user_dashboard"]["recent_bookings"]) == 2
    assert len(dashboard_payload["user_dashboard"]["recent_diagnostics"]) == 1
    assert dashboard_payload["user_dashboard"]["recent_diagnostics"][0]["doctor_name"] == "Dr. Ayesha Rahman"
    assert dashboard_payload["user_dashboard"]["recent_diagnostics"][0]["diagnosis"] == "Stable angina"


def test_dashboard_documents_are_scoped_and_patchable(
    client_and_session: tuple[TestClient, sessionmaker],
) -> None:
    test_client, testing_session_local = client_and_session
    with testing_session_local() as db:
        seeded = _seed_dashboard_data(db)
        patient_user = seeded["patient_user"]
        other_user = _create_user(
            db,
            name="Other Patient",
            email="other@example.com",
            username="other-user",
            password="StrongPass1",
            role=UserRole.USER,
        )
        db.commit()

    patient_headers = _login_headers(test_client, patient_user.username, "StrongPass1")
    other_headers = _login_headers(test_client, other_user.username, "StrongPass1")

    create_response = test_client.post(
        f"{settings.API_V1_STR}/dashboard/documents",
        headers=patient_headers,
        json={
            "session_id": "session-001",
            "title": "Symptom Assessment - Chest Pain",
            "symptom_name": "Chest Pain",
            "source_route": "/symptom/general-assessment",
            "intake_payload": {"symptoms": ["Chest pain", "Fatigue"]},
            "conversation_log": [{"role": "user", "message": "Chest pain for 2 days"}],
            "status": "draft",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["user_id"] == patient_user.id
    assert created["status"] == "draft"

    patch_response = test_client.patch(
        f"{settings.API_V1_STR}/dashboard/documents/{created['id']}",
        headers=patient_headers,
        json={
            "ai_output": {
                "symptom_analysis": {
                    "urgency": "moderate",
                    "recommended_specializations": ["Cardiology"],
                }
            },
            "status": "completed",
        },
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["status"] == "completed"
    assert patched["ai_output"]["symptom_analysis"]["urgency"] == "moderate"

    list_response = test_client.get(
        f"{settings.API_V1_STR}/dashboard/documents",
        headers=patient_headers,
    )
    assert list_response.status_code == 200
    documents = list_response.json()
    assert len(documents) == 1
    assert documents[0]["id"] == created["id"]
    assert "Urgency: Moderate" in documents[0]["summary"]

    other_list_response = test_client.get(
        f"{settings.API_V1_STR}/dashboard/documents",
        headers=other_headers,
    )
    assert other_list_response.status_code == 200
    assert other_list_response.json() == []


def test_authenticated_booking_can_link_assessment_without_guest_persistence(
    client_and_session: tuple[TestClient, sessionmaker],
) -> None:
    test_client, testing_session_local = client_and_session
    with testing_session_local() as db:
        seeded = _seed_dashboard_data(db)
        patient_user = seeded["patient_user"]
        assessment = AssessmentDocument(
            user_id=patient_user.id,
            session_id="session-linked-booking",
            title="Symptom Assessment - Cough",
            symptom_name="Cough",
            source_route="/symptom/general-assessment",
            intake_payload={"symptoms": ["Cough"]},
            ai_output={},
            conversation_log=[{"role": "user", "message": "Persistent cough"}],
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)

    patient_headers = _login_headers(test_client, patient_user.username, "StrongPass1")

    booking_response = test_client.post(
        f"{settings.API_V1_STR}/bookings/",
        headers=patient_headers,
        json={
            "provider_name": "Dr. External Provider",
            "provider_external_id": "4545",
            "location_name": "Remote Consultation",
            "location_address": "Telehealth",
            "appointment_date": "2026-04-30",
            "appointment_time": "10:30:00",
            "booking_type": "online",
            "symptoms_summary": "Booked from symptom assessment",
            "linked_assessment_id": assessment.id,
        },
    )
    assert booking_response.status_code == 200
    booking_payload = booking_response.json()
    assert booking_payload["user_id"] == patient_user.id
    assert booking_payload["linked_assessment_id"] == assessment.id
    assert booking_payload["provider_name"] == "Dr. External Provider"
    assert booking_payload["doctor_id"] is None
    assert booking_payload["hospital_id"] is None

    unauthenticated_response = test_client.post(
        f"{settings.API_V1_STR}/bookings/",
        json={
            "provider_name": "Guest Provider",
            "appointment_date": "2026-04-30",
            "appointment_time": "11:00:00",
        },
    )
    assert unauthenticated_response.status_code == 401
