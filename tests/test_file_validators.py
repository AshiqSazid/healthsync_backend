import pytest
from fastapi import HTTPException

from app.utils.file_validators import validate_upload_content_type, validate_upload_extension


def test_validate_upload_extension_accepts_common_image_variants() -> None:
    validate_upload_extension("report.WEBP")
    validate_upload_extension("scan.tiff")
    validate_upload_extension("photo.heic")
    validate_upload_extension("document.avif")


def test_validate_upload_content_type_accepts_image_family_types() -> None:
    validate_upload_content_type("image/heic", "photo.heic")
    validate_upload_content_type("image/webp", "report.webp")


def test_validate_upload_content_type_accepts_binary_fallback_for_allowed_extension() -> None:
    validate_upload_content_type("application/octet-stream", "scan.tiff")


def test_validate_upload_content_type_rejects_unsupported_non_pdf_non_image_types() -> None:
    with pytest.raises(HTTPException):
        validate_upload_content_type("text/plain", "notes.txt")
