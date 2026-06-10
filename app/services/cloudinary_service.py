from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from importlib import import_module
from uuid import uuid4

from app.core.config import settings
from app.models.enums import UploadFileType
from app.utils.file_validators import ValidatedUploadFile
from app.utils.helpers import sanitize_email_for_path


class CloudinaryServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudinaryUploadResult:
    public_id: str
    url: str
    secure_url: str
    folder_path: str
    uploaded_at: datetime


class CloudinaryService:
    _configured = False

    def __init__(self) -> None:
        self._configure()

    @classmethod
    def _configure(cls) -> None:
        if cls._configured:
            return
        if not settings.CLOUDINARY_CLOUD_NAME:
            raise CloudinaryServiceError("CLOUDINARY_CLOUD_NAME is not configured.")
        if not settings.CLOUDINARY_API_KEY:
            raise CloudinaryServiceError("CLOUDINARY_API_KEY is not configured.")
        if not settings.CLOUDINARY_API_SECRET:
            raise CloudinaryServiceError("CLOUDINARY_API_SECRET is not configured.")

        try:
            cloudinary = import_module("cloudinary")
        except ModuleNotFoundError as exc:
            raise CloudinaryServiceError("cloudinary is required for upload endpoints.") from exc

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )
        cls._configured = True

    @staticmethod
    def _uploader():
        try:
            return import_module("cloudinary.uploader")
        except ModuleNotFoundError as exc:
            raise CloudinaryServiceError("cloudinary is required for upload endpoints.") from exc

    @staticmethod
    def _normalize_now(now: datetime | None = None) -> datetime:
        if now is None:
            return datetime.now(timezone.utc)
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def build_folder_path(self, *, user_email: str, file_type: UploadFileType, now: datetime | None = None) -> str:
        timestamp = self._normalize_now(now)
        type_folder = "prescriptions" if file_type == UploadFileType.PRESCRIPTION else "reports"
        base_folder = (settings.CLOUDINARY_UPLOAD_FOLDER or "healthsynch").strip("/") or "healthsynch"
        sanitized_email = sanitize_email_for_path(user_email)
        return f"{base_folder}/users/{sanitized_email}/{type_folder}/{timestamp:%Y/%m/%d}"

    def upload_user_file(
        self,
        *,
        validated_file: ValidatedUploadFile,
        user_email: str,
        file_type: UploadFileType,
        now: datetime | None = None,
    ) -> CloudinaryUploadResult:
        timestamp = self._normalize_now(now)
        folder_path = self.build_folder_path(user_email=user_email, file_type=file_type, now=timestamp)
        public_id = f"{file_type.value}_{uuid4().hex[:8]}"

        options: dict[str, object] = {
            "folder": folder_path,
            "resource_type": "auto",
            "allowed_formats": ["jpg", "jpeg", "png", "webp", "pdf"],
            "public_id": public_id,
        }
        if not validated_file.is_pdf:
            options["transformation"] = [{"quality": "auto", "fetch_format": "auto"}]

        try:
            result = self._uploader().upload(validated_file.content, **options)
        except Exception as exc:
            raise CloudinaryServiceError("Cloudinary upload failed.") from exc

        return CloudinaryUploadResult(
            public_id=str(result["public_id"]),
            url=str(result["url"]),
            secure_url=str(result["secure_url"]),
            folder_path=folder_path,
            uploaded_at=timestamp,
        )

    def delete_file(self, *, public_id: str, mime_type: str) -> None:
        preferred_types = ["raw", "image"] if mime_type == "application/pdf" else ["image", "raw"]
        last_result: dict[str, object] | None = None

        for resource_type in preferred_types:
            try:
                result = self._uploader().destroy(public_id, resource_type=resource_type, invalidate=True)
            except Exception:
                continue

            last_result = dict(result or {})
            if str(last_result.get("result") or "").lower() in {"ok", "not found"}:
                return

        raise CloudinaryServiceError(f"Cloudinary delete failed for public_id '{public_id}': {last_result!r}")


@lru_cache
def get_cloudinary_service() -> CloudinaryService:
    return CloudinaryService()
