from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.auth_service import get_auth_service
from app.services.email_service import EmailService, get_email_service
from app.services.google_auth_service import GoogleUserIdentity, get_google_auth_service
from app.services.rate_limit_service import RateLimitService, get_rate_limit_service


class _StubEmailService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def send_password_reset_email(self, *, recipient: str, user_name: str, reset_token: str) -> None:
        self.calls.append((recipient, user_name, reset_token))


class _StubGoogleAuthService:
    def __init__(self) -> None:
        self.last_redirect_uri: str | None = None
        self.last_state: str | None = None
        self.identity = GoogleUserIdentity(
            subject="google-user-123",
            email="google-user@example.com",
            email_verified=True,
            name="Google User",
        )

    def build_authorization_url(self, *, redirect_uri: str, state: str) -> str:
        self.last_redirect_uri = redirect_uri
        self.last_state = state
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"

    def authenticate_authorization_code(self, *, code: str, redirect_uri: str) -> GoogleUserIdentity:
        assert code == "google-auth-code"
        self.last_redirect_uri = redirect_uri
        return self.identity


@pytest.fixture
def client() -> Generator[tuple[TestClient, _StubEmailService], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    stub_email_service = _StubEmailService()
    rate_limit_service = RateLimitService()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_service] = lambda: stub_email_service
    app.dependency_overrides[get_rate_limit_service] = lambda: rate_limit_service

    with TestClient(app) as test_client:
        yield test_client, stub_email_service

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_signup_me_refresh_and_logout_flow(client: tuple[TestClient, _StubEmailService]) -> None:
    test_client, _ = client

    signup_response = test_client.post(
        f"{settings.API_V1_STR}/auth/signup",
        json={
            "name": "Abir Islam",
            "email": "abirs25ultra@gmail.com",
            "password": "StrongPass1",
        },
    )

    assert signup_response.status_code == 201
    signup_payload = signup_response.json()
    access_token = signup_payload["access_token"]
    refresh_token = signup_payload["refresh_token"]

    assert signup_payload["user"]["name"] == "Abir Islam"
    assert signup_payload["user"]["email"] == "abirs25ultra@gmail.com"
    assert signup_payload["user"]["role"] == "user"
    assert signup_payload["user"]["username"]
    assert signup_payload["user"]["doctor_profile_id"] is None
    assert signup_response.cookies.get(settings.JWT_REFRESH_COOKIE_NAME) == refresh_token

    me_response = test_client.get(
        f"{settings.API_V1_STR}/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "abirs25ultra@gmail.com"
    assert me_response.json()["role"] == "user"
    assert me_response.json()["username"]
    assert me_response.json()["doctor_profile_id"] is None

    refresh_response = test_client.post(
        f"{settings.API_V1_STR}/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert refresh_response.status_code == 200
    refresh_payload = refresh_response.json()
    assert refresh_payload["access_token"] != access_token
    assert refresh_payload["refresh_token"] != refresh_token

    logout_response = test_client.post(
        f"{settings.API_V1_STR}/auth/logout",
        json={"refresh_token": refresh_payload["refresh_token"]},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {"message": "Logged out"}


def test_signup_rejects_duplicate_email_with_clear_error(
    client: tuple[TestClient, _StubEmailService],
) -> None:
    test_client, _ = client

    first_response = test_client.post(
        f"{settings.API_V1_STR}/auth/signup",
        json={
            "name": "Duplicate User",
            "email": "duplicate@example.com",
            "password": "StrongPass1",
        },
    )
    assert first_response.status_code == 201

    second_response = test_client.post(
        f"{settings.API_V1_STR}/auth/signup",
        json={
            "name": "Duplicate User",
            "email": "duplicate@example.com",
            "password": "StrongPass1",
        },
    )

    assert second_response.status_code == 400
    assert second_response.json() == {"detail": "Email is already registered"}


def test_password_reset_url_prefers_backend_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://https://health-synch-backend.vercel.app.app")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://myhealthsynch.com")

    assert EmailService.build_password_reset_url("abc123") == (
        "https://https://health-synch-backend.vercel.app.app/reset-password?token=abc123"
    )


def test_reset_password_page_handles_validation_errors(client: tuple[TestClient, _StubEmailService]) -> None:
    test_client, _ = client

    response = test_client.get("/reset-password", params={"token": "abc123"})

    assert response.status_code == 200
    html = response.text
    assert "passwordComplexityPattern" in html
    assert "formatErrorDetail" in html
    assert "Password must be at least 8 characters and include 1 uppercase letter and 1 number." in html
    assert 'fetch("/api/v1/auth/reset-password"' in html


def test_forgot_and_reset_password_flow(client: tuple[TestClient, _StubEmailService]) -> None:
    test_client, email_service = client

    signup_response = test_client.post(
        f"{settings.API_V1_STR}/auth/signup",
        json={
            "name": "Reset User",
            "email": "reset@example.com",
            "password": "StrongPass1",
        },
    )
    assert signup_response.status_code == 201

    forgot_response = test_client.post(
        f"{settings.API_V1_STR}/auth/forgot-password",
        json={"email": "reset@example.com"},
    )

    assert forgot_response.status_code == 200
    assert forgot_response.json() == {"message": "If an account exists, a reset link has been sent"}
    assert len(email_service.calls) == 1
    recipient, user_name, reset_token = email_service.calls[0]
    assert recipient == "reset@example.com"
    assert user_name == "Reset User"

    reset_response = test_client.post(
        f"{settings.API_V1_STR}/auth/reset-password",
        json={
            "token": reset_token,
            "new_password": "NewStrongPass1",
        },
    )

    assert reset_response.status_code == 200
    assert reset_response.json() == {"message": "Password reset successful"}

    old_login = test_client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"email": "reset@example.com", "password": "StrongPass1"},
    )
    assert old_login.status_code == 400
    assert old_login.json()["detail"] == "Invalid credentials"

    new_login = test_client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"email": "reset@example.com", "password": "NewStrongPass1"},
    )
    assert new_login.status_code == 200
    assert new_login.json()["user"]["email"] == "reset@example.com"


def test_login_accepts_identifier_and_returns_role_aware_user(client: tuple[TestClient, _StubEmailService]) -> None:
    test_client, _ = client

    signup_response = test_client.post(
        f"{settings.API_V1_STR}/auth/signup",
        json={
            "name": "Doctor Login",
            "email": "doctor-login@example.com",
            "password": "StrongPass1",
        },
    )
    assert signup_response.status_code == 201
    username = signup_response.json()["user"]["username"]

    login_response = test_client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"identifier": username, "password": "StrongPass1"},
    )

    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["user"]["email"] == "doctor-login@example.com"
    assert payload["user"]["username"] == username
    assert payload["user"]["role"] == "user"
    assert payload["refresh_token"]


def test_login_accepts_username_field_for_backward_compatibility(
    client: tuple[TestClient, _StubEmailService],
) -> None:
    test_client, _ = client

    signup_response = test_client.post(
        f"{settings.API_V1_STR}/auth/signup",
        json={
            "name": "Legacy Username Login",
            "email": "legacy-username-login@example.com",
            "password": "StrongPass1",
        },
    )
    assert signup_response.status_code == 201
    username = signup_response.json()["user"]["username"]

    login_response = test_client.post(
        f"{settings.API_V1_STR}/auth/login",
        json={"username": username, "password": "StrongPass1"},
    )

    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["user"]["email"] == "legacy-username-login@example.com"
    assert payload["user"]["username"] == username
    assert payload["refresh_token"]


def test_google_login_url_and_callback_flow(client: tuple[TestClient, _StubEmailService]) -> None:
    test_client, _ = client
    google_auth_service = _StubGoogleAuthService()
    test_client.app.dependency_overrides[get_google_auth_service] = lambda: google_auth_service

    try:
        login_url_response = test_client.get(
            f"{settings.API_V1_STR}/auth/google/login-url",
            params={"next": "/dashboard"},
        )
        assert login_url_response.status_code == 200
        assert login_url_response.json()["authorization_url"].startswith(
            "https://accounts.google.com/o/oauth2/v2/auth?state="
        )
        assert google_auth_service.last_state

        state = get_auth_service().create_oauth_state_token(next_path="/dashboard")
        callback_response = test_client.get(
            f"{settings.API_V1_STR}/auth/google/callback",
            params={"code": "google-auth-code", "state": state},
            follow_redirects=False,
        )

        assert callback_response.status_code == 302
        assert callback_response.headers["location"] == (
            f"{settings.FRONTEND_URL}/auth/google/callback?next=%2Fdashboard"
        )
        assert callback_response.cookies.get(settings.JWT_REFRESH_COOKIE_NAME)

        refresh_response = test_client.post(f"{settings.API_V1_STR}/auth/refresh")
        assert refresh_response.status_code == 200
        refresh_payload = refresh_response.json()
        assert refresh_payload["access_token"]
        assert refresh_payload["refresh_token"]

        me_response = test_client.get(
            f"{settings.API_V1_STR}/auth/me",
            headers={"Authorization": f"Bearer {refresh_payload['access_token']}"},
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "google-user@example.com"
    finally:
        test_client.app.dependency_overrides.pop(get_google_auth_service, None)
