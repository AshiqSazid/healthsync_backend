from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

SUPPORTED_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
SUPPORTED_FALLBACK_BINARY_CONTENT_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
MEDICAL_UPLOAD_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MEDICAL_UPLOAD_EXTENSIONS = {
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
    ".pdf": {"application/pdf"},
}
CONTENT_TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "application/x-pdf": "application/pdf",
}


@dataclass(frozen=True)
class ValidatedUploadFile:
    filename: str
    content: bytes
    size: int
    mime_type: str
    extension: str
    is_pdf: bool


def normalize_upload_content_type(content_type: str | None) -> str:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_ALIASES.get(normalized, normalized)


def has_allowed_upload_extension(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in settings.ALLOWED_UPLOAD_EXTENSIONS


def validate_upload_extension(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension: {suffix}",
        )


async def validate_upload_size(file: UploadFile) -> int:
    content = await file.read()
    size = len(content)
    await file.seek(0)
    if size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File size exceeds limit")
    return size


def validate_upload_content_type(content_type: str | None, filename: str | None = None) -> None:
    normalized = normalize_upload_content_type(content_type)
    if normalized.startswith("image/") or normalized in SUPPORTED_PDF_CONTENT_TYPES:
        return

    if normalized in SUPPORTED_FALLBACK_BINARY_CONTENT_TYPES and has_allowed_upload_extension(filename or ""):
        return

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported content type")


def detect_magic_mime_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_medical_upload_bytes(
    *,
    filename: str,
    content_type: str | None,
    content: bytes,
    max_size_bytes: int | None = None,
) -> ValidatedUploadFile:
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    extension = Path(filename).suffix.lower()
    if extension not in MEDICAL_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file extension")

    size = len(content)
    effective_max_size = max_size_bytes or settings.MAX_UPLOAD_MB * 1024 * 1024
    if size > effective_max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds {settings.MAX_UPLOAD_MB}MB limit",
        )

    detected_mime_type = detect_magic_mime_type(content)
    if detected_mime_type not in MEDICAL_UPLOAD_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")

    header_mime_type = normalize_upload_content_type(content_type)
    if header_mime_type and header_mime_type not in SUPPORTED_FALLBACK_BINARY_CONTENT_TYPES:
        if header_mime_type != detected_mime_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content does not match declared content type",
            )

    if detected_mime_type not in MEDICAL_UPLOAD_EXTENSIONS[extension]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension does not match file content",
        )

    return ValidatedUploadFile(
        filename=filename,
        content=content,
        size=size,
        mime_type=detected_mime_type,
        extension=extension,
        is_pdf=detected_mime_type == "application/pdf",
    )


async def validate_medical_upload(file: UploadFile, max_size_bytes: int | None = None) -> ValidatedUploadFile:
    content = await file.read()
    await file.seek(0)
    return validate_medical_upload_bytes(
        filename=file.filename or "",
        content_type=file.content_type,
        content=content,
        max_size_bytes=max_size_bytes,
    )
