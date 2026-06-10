from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints.files import get_storage_service
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.file_record import FileRecord
from app.services.storage_service import ResolvedDoctorImage, StoredFile


class _StubStorageService:
    def __init__(self) -> None:
        self.upload_calls: list[tuple[str, str]] = []
        self.counter = 0
        self.doctor_images: dict[str, ResolvedDoctorImage] = {}

    async def store_file(self, file, user_id: str) -> StoredFile:
        self.counter += 1
        suffix = Path(file.filename or "").suffix.lower() or ".bin"
        generated_name = f"stored-{self.counter}{suffix}"
        self.upload_calls.append((file.filename or "", user_id))
        return StoredFile(
            file_name=generated_name,
            file_path=f"2026/03/12/{generated_name}",
            storage_reference=(
                "https://res.cloudinary.com/demo/image/upload/"
                f"v1/healthsynch/users/{user_id}/2026/March/12/{generated_name}"
            ),
        )

    async def upsert_doctor_image(self, file, doctor_id: str) -> None:
        self.doctor_images[doctor_id] = ResolvedDoctorImage(
            storage_reference=f"https://cdn.example.com/doctor-images/{doctor_id}/current",
            media_type="image/png",
            is_local_file=False,
        )

    async def get_doctor_image(self, doctor_id: str) -> ResolvedDoctorImage | None:
        return self.doctor_images.get(doctor_id)

    async def get_file_url(self, file_path: str, expiry: int = 3600) -> str:
        return file_path


@pytest.fixture
def client() -> Generator[tuple[TestClient, _StubStorageService, sessionmaker], None, None]:
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

    storage_service = _StubStorageService()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage_service] = lambda: storage_service

    with TestClient(app) as test_client:
        yield test_client, storage_service, TestingSessionLocal

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_upload_file_persists_doctor_id_and_returns_wrapped_payload(
    client: tuple[TestClient, _StubStorageService, sessionmaker],
) -> None:
    test_client, storage_service, TestingSessionLocal = client

    response = test_client.post(
        f"{settings.API_V1_STR}/files/upload",
        params={"userid": "doctor_123"},
        files={"file": ("dr-khan-photo.png", b"doctor-image-bytes", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["success"] is True
    assert payload["message"] == "File uploaded successfully"
    assert payload["errorCode"] is None
    assert payload["data"]["fileName"] == "stored-1.png"
    assert payload["data"]["originalFileName"] == "dr-khan-photo.png"
    assert payload["data"]["filePath"] == "2026/03/12/stored-1.png"
    assert payload["data"]["fileType"] == "image/png"
    assert payload["data"]["userId"] == "doctor_123"
    assert payload["data"]["status"] == "CLEAN"
    assert payload["data"]["virusScanned"] is True
    assert payload["data"]["virusFound"] is False
    assert storage_service.upload_calls == [("dr-khan-photo.png", "doctor_123")]
    assert storage_service.doctor_images["doctor_123"].storage_reference == (
        "https://cdn.example.com/doctor-images/doctor_123/current"
    )

    with TestingSessionLocal() as db:
        record = db.query(FileRecord).filter(FileRecord.user_id == "doctor_123").one()
        assert record.file_name == "stored-1.png"
        assert record.storage_reference.startswith("https://res.cloudinary.com/demo/image/upload/")


def test_get_doctor_image_redirects_to_stable_storage_image(
    client: tuple[TestClient, _StubStorageService, sessionmaker],
) -> None:
    test_client, _, _ = client

    upload_response = test_client.post(
        f"{settings.API_V1_STR}/files/upload",
        params={"userid": "doctor_123"},
        files={"file": ("latest-photo.png", b"latest-image-bytes", "image/png")},
    )

    assert upload_response.status_code == 200

    response = test_client.get(
        f"{settings.API_V1_STR}/files/doctor/doctor_123",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://cdn.example.com/doctor-images/doctor_123/current"


def test_get_doctor_image_still_works_without_database_record_when_storage_alias_exists(
    client: tuple[TestClient, _StubStorageService, sessionmaker],
) -> None:
    test_client, storage_service, _ = client

    storage_service.doctor_images["doctor_123"] = ResolvedDoctorImage(
        storage_reference="https://cdn.example.com/doctor-images/doctor_123/current",
        media_type="image/png",
        is_local_file=False,
    )

    response = test_client.get(
        f"{settings.API_V1_STR}/files/doctor/doctor_123",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://cdn.example.com/doctor-images/doctor_123/current"


def test_get_doctor_image_returns_json_for_fetch_clients(
    client: tuple[TestClient, _StubStorageService, sessionmaker],
) -> None:
    test_client, _, _ = client

    upload_response = test_client.post(
        f"{settings.API_V1_STR}/files/upload",
        params={"userid": "doctor_123"},
        files={"file": ("latest-photo.png", b"latest-image-bytes", "image/png")},
    )

    assert upload_response.status_code == 200

    response = test_client.get(
        f"{settings.API_V1_STR}/files/doctor/doctor_123",
        headers={"sec-fetch-dest": "empty"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["message"] == "Doctor image resolved successfully"
    assert payload["data"]["doctorId"] == "doctor_123"
    assert payload["data"]["fileUrl"] == "https://cdn.example.com/doctor-images/doctor_123/current"
    assert payload["data"]["originalFileName"] == "latest-photo.png"


def test_get_doctor_image_returns_json_when_redirect_disabled_explicitly(
    client: tuple[TestClient, _StubStorageService, sessionmaker],
) -> None:
    test_client, _, _ = client

    upload_response = test_client.post(
        f"{settings.API_V1_STR}/files/upload",
        params={"userid": "doctor_123"},
        files={"file": ("latest-photo.png", b"latest-image-bytes", "image/png")},
    )

    assert upload_response.status_code == 200

    response = test_client.get(
        f"{settings.API_V1_STR}/files/doctor/doctor_123",
        params={"redirect": "false"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["fileUrl"] == "https://cdn.example.com/doctor-images/doctor_123/current"


def test_get_doctor_image_returns_wrapped_404_when_missing(
    client: tuple[TestClient, _StubStorageService, sessionmaker],
) -> None:
    test_client, _, _ = client

    response = test_client.get(
        f"{settings.API_V1_STR}/files/doctor/missing-doctor",
        follow_redirects=False,
    )

    assert response.status_code == 404
    payload = response.json()

    assert payload == {
        "success": False,
        "message": "No image found for doctor ID: missing-doctor",
        "data": None,
        "timestamp": payload["timestamp"],
        "metadata": None,
        "errorCode": "DOCTOR_IMAGE_NOT_FOUND",
    }
