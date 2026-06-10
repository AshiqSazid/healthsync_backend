from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.enums import UploadFileType
from app.services.cloudinary_service import CloudinaryUploadResult, get_cloudinary_service
from app.services.rate_limit_service import RateLimitService, get_rate_limit_service


class _StubCloudinaryService:
    def __init__(self) -> None:
        self.upload_calls: list[tuple[str, UploadFileType]] = []
        self.deleted_public_ids: list[str] = []
        self.counter = 0

    def upload_user_file(self, *, validated_file, user_email: str, file_type: UploadFileType):
        self.counter += 1
        folder_type = "prescriptions" if file_type == UploadFileType.PRESCRIPTION else "reports"
        folder_path = f"healthsynch/users/test_at_example_dot_com/{folder_type}/2026/03/13"
        public_id = f"{file_type.value}_{self.counter:02d}"
        self.upload_calls.append((validated_file.filename, file_type))
        return CloudinaryUploadResult(
            public_id=public_id,
            url=f"http://cdn.example.com/{public_id}",
            secure_url=f"https://cdn.example.com/{public_id}",
            folder_path=folder_path,
            uploaded_at=datetime(2026, 3, 13, tzinfo=timezone.utc),
        )

    def delete_file(self, *, public_id: str, mime_type: str) -> None:
        self.deleted_public_ids.append(public_id)


@pytest.fixture
def client() -> Generator[tuple[TestClient, _StubCloudinaryService], None, None]:
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

    stub_cloudinary_service = _StubCloudinaryService()
    rate_limit_service = RateLimitService()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_cloudinary_service] = lambda: stub_cloudinary_service
    app.dependency_overrides[get_rate_limit_service] = lambda: rate_limit_service

    with TestClient(app) as test_client:
        yield test_client, stub_cloudinary_service

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _signup_and_get_token(client: TestClient) -> str:
    response = client.post(
        f"{settings.API_V1_STR}/auth/signup",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "StrongPass1",
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def test_prescription_and_report_upload_flow(client: tuple[TestClient, _StubCloudinaryService]) -> None:
    test_client, cloudinary_service = client
    access_token = _signup_and_get_token(test_client)
    headers = {"Authorization": f"Bearer {access_token}"}

    prescription_response = test_client.post(
        f"{settings.API_V1_STR}/uploads/prescription",
        headers=headers,
        files={"file": ("prescription.jpg", b"\xff\xd8\xffmockjpegbytes", "image/jpeg")},
    )

    assert prescription_response.status_code == 201
    prescription_payload = prescription_response.json()
    assert prescription_payload["file_type"] == "prescription"
    assert prescription_payload["folder_path"].endswith("/prescriptions/2026/03/13")

    reports_response = test_client.post(
        f"{settings.API_V1_STR}/uploads/report",
        headers=headers,
        files=[
            ("files", ("blood-test.pdf", b"%PDF-1.4 mock pdf", "application/pdf")),
            ("files", ("xray.png", b"\x89PNG\r\n\x1a\nmockpng", "image/png")),
        ],
    )

    assert reports_response.status_code == 201
    reports_payload = reports_response.json()
    assert len(reports_payload) == 2
    assert reports_payload[0]["file_type"] == "report"

    list_response = test_client.get(
        f"{settings.API_V1_STR}/uploads/my-uploads?type=report&page=1&limit=10",
        headers=headers,
    )

    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 2
    assert len(list_payload["uploads"]) == 2
    first_upload_id = list_payload["uploads"][0]["id"]

    detail_response = test_client.get(
        f"{settings.API_V1_STR}/uploads/{first_upload_id}",
        headers=headers,
    )

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["id"] == first_upload_id
    assert detail_payload["file_type"] == "report"

    delete_response = test_client.delete(
        f"{settings.API_V1_STR}/uploads/{first_upload_id}",
        headers=headers,
    )

    assert delete_response.status_code == 200
    assert delete_response.json() == {"message": "File deleted"}
    assert cloudinary_service.deleted_public_ids
