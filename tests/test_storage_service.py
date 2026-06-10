from datetime import datetime, timezone
from io import BytesIO

import pytest
from starlette.datastructures import Headers, UploadFile

from app.core.config import settings
from app.services.storage_service import StorageService


def test_build_date_path_uses_full_month_name() -> None:
    current_time = datetime(2026, 3, 7, 15, 30, tzinfo=timezone.utc)

    assert StorageService._build_date_path(current_time) == "2026/March/07"


def test_build_date_path_treats_naive_datetime_as_utc() -> None:
    current_time = datetime(2026, 2, 27, 8, 45)

    assert StorageService._build_date_path(current_time) == "2026/February/27"


@pytest.mark.asyncio
async def test_cloudinary_upload_uses_month_name_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class DummyUploader:
        @staticmethod
        def upload(file_content: bytes, **kwargs: str) -> dict[str, str]:
            captured["folder"] = kwargs["folder"]
            captured["public_id"] = kwargs["public_id"]
            return {"secure_url": "https://res.cloudinary.com/demo/image/upload/v1/test.jpg"}

    monkeypatch.setattr(settings, "STORAGE_BACKEND", "cloudinary")
    monkeypatch.setattr(settings, "CLOUDINARY_UPLOAD_FOLDER", "healthsynch")
    monkeypatch.setattr(StorageService, "_configure_cloudinary", staticmethod(lambda: None))
    monkeypatch.setattr(
        StorageService,
        "_get_cloudinary_modules",
        classmethod(lambda cls: (None, DummyUploader)),
    )
    monkeypatch.setattr(
        StorageService,
        "_build_date_path",
        staticmethod(lambda current_time=None: "2026/March/07"),
    )

    upload = UploadFile(
        file=BytesIO(b"mock-image-bytes"),
        filename="report.jpg",
        headers=Headers({"content-type": "image/jpeg"}),
    )

    service = StorageService()
    result = await service.upload_file(upload, "public-preview")

    assert captured["folder"] == "healthsynch/users/public-preview/2026/March/07"
    assert captured["public_id"]
    assert result == "https://res.cloudinary.com/demo/image/upload/v1/test.jpg"


@pytest.mark.asyncio
async def test_cloudinary_delete_parses_public_id_and_resource_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class DummyUploader:
        @staticmethod
        def destroy(public_id: str, *, resource_type: str) -> None:
            captured["public_id"] = public_id
            captured["resource_type"] = resource_type

    monkeypatch.setattr(settings, "STORAGE_BACKEND", "cloudinary")
    monkeypatch.setattr(StorageService, "_configure_cloudinary", staticmethod(lambda: None))
    monkeypatch.setattr(
        StorageService,
        "_get_cloudinary_modules",
        classmethod(lambda cls: (None, DummyUploader)),
    )

    service = StorageService()
    deleted = await service.delete_file(
        "https://res.cloudinary.com/demo/image/upload/v1773307534/healthsynch/users/public-preview/2026/March/12/demo-asset.png"
    )

    assert deleted is True
    assert captured["resource_type"] == "image"
    assert captured["public_id"] == "healthsynch/users/public-preview/2026/March/12/demo-asset"
