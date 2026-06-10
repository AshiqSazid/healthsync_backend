from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.utils.file_validators import (
    validate_upload_content_type,
    validate_upload_extension,
    validate_upload_size,
)


@dataclass(frozen=True)
class StoredFile:
    file_name: str
    file_path: str
    storage_reference: str


@dataclass(frozen=True)
class ResolvedDoctorImage:
    storage_reference: str
    media_type: str | None
    is_local_file: bool = False


class StorageService:
    _cloudinary_module: Any | None = None
    _cloudinary_uploader: Any | None = None

    def __init__(self) -> None:
        self.backend = settings.STORAGE_BACKEND
        if (
            settings.ENVIRONMENT == "production"
            and settings.REQUIRE_REMOTE_STORAGE_IN_PRODUCTION
            and self.backend == "local"
        ):
            raise RuntimeError(
                "STORAGE_BACKEND=local is disabled in production. "
                "Use STORAGE_BACKEND=s3, STORAGE_BACKEND=minio, or STORAGE_BACKEND=cloudinary."
            )
        self.upload_dir = self._resolve_upload_dir(settings.UPLOAD_DIR)
        if self.backend == "local":
            self.upload_dir = self._ensure_upload_dir(self.upload_dir)
        elif self.backend == "cloudinary":
            self._configure_cloudinary()

    @staticmethod
    def _resolve_upload_dir(upload_dir: str) -> Path:
        path = Path(upload_dir).expanduser()
        if path.is_absolute():
            return path
        # Keep relative UPLOAD_DIR stable regardless of process cwd.
        backend_root = Path(__file__).resolve().parents[2]
        return (backend_root / path).resolve()

    @staticmethod
    def _ensure_upload_dir(path: Path) -> Path:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            fallback = Path("/tmp/healthsynch/uploads")
            fallback.mkdir(parents=True, exist_ok=True)
            logging.getLogger(__name__).warning(
                "UPLOAD_DIR '%s' is not writable. Falling back to '%s'.",
                path,
                fallback,
            )
            return fallback

    @classmethod
    def _get_cloudinary_modules(cls) -> tuple[Any, Any]:
        if cls._cloudinary_module is not None and cls._cloudinary_uploader is not None:
            return cls._cloudinary_module, cls._cloudinary_uploader

        try:
            cloudinary_module = import_module("cloudinary")
            cloudinary_uploader_module = import_module("cloudinary.uploader")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "cloudinary is required when STORAGE_BACKEND is 'cloudinary'. "
                "Install it with: pip install cloudinary"
            ) from exc

        cls._cloudinary_module = cloudinary_module
        cls._cloudinary_uploader = cloudinary_uploader_module
        return cloudinary_module, cloudinary_uploader_module

    @staticmethod
    def _configure_cloudinary() -> None:
        if not settings.CLOUDINARY_CLOUD_NAME:
            raise RuntimeError("CLOUDINARY_CLOUD_NAME must be set when STORAGE_BACKEND is 'cloudinary'.")
        if not settings.CLOUDINARY_API_KEY:
            raise RuntimeError("CLOUDINARY_API_KEY must be set when STORAGE_BACKEND is 'cloudinary'.")
        if not settings.CLOUDINARY_API_SECRET:
            raise RuntimeError("CLOUDINARY_API_SECRET must be set when STORAGE_BACKEND is 'cloudinary'.")

        cloudinary, _ = StorageService._get_cloudinary_modules()
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )

    def _get_s3_client(self):
        try:
            boto3 = import_module("boto3")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "boto3 is required when STORAGE_BACKEND is 's3' or 'minio'. "
                "Install it with: pip install boto3"
            ) from exc

        return boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )

    @staticmethod
    def _get_required_bucket() -> str:
        bucket = settings.S3_BUCKET
        if not bucket:
            raise RuntimeError("S3_BUCKET must be set when STORAGE_BACKEND is 's3' or 'minio'.")
        return bucket

    @staticmethod
    def _build_date_path(current_time: datetime | None = None) -> str:
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        elif current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        else:
            current_time = current_time.astimezone(timezone.utc)

        return f"{current_time:%Y}/{current_time.strftime('%B')}/{current_time:%d}"

    @staticmethod
    def _parse_cloudinary_reference(file_path: str) -> tuple[str, str] | None:
        parsed = urlparse(str(file_path or ""))
        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return None

        try:
            upload_index = path_parts.index("upload")
        except ValueError:
            return None

        if upload_index < 1:
            return None

        resource_type = path_parts[upload_index - 1]
        public_id_parts = path_parts[upload_index + 1 :]
        if public_id_parts and public_id_parts[0].startswith("v") and public_id_parts[0][1:].isdigit():
            public_id_parts = public_id_parts[1:]
        if not public_id_parts:
            return None

        public_id_parts[-1] = Path(public_id_parts[-1]).stem
        public_id = "/".join(public_id_parts)
        if not public_id:
            return None

        return public_id, resource_type

    def _verify_remote_upload(self, object_path: str) -> dict[str, Any]:
        s3_client = self._get_s3_client()
        return s3_client.head_object(Bucket=self._get_required_bucket(), Key=object_path)

    @staticmethod
    def _build_record_file_path(filename: str, current_time: datetime | None = None) -> str:
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        elif current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        else:
            current_time = current_time.astimezone(timezone.utc)
        return f"{current_time:%Y/%m/%d}/{filename}"

    @staticmethod
    def _doctor_image_object_key(doctor_id: str) -> str:
        return f"doctor-images/{doctor_id}/current"

    @staticmethod
    def _detect_image_media_type(content: bytes) -> str | None:
        sample = content[:16]
        if sample.startswith(b"\xFF\xD8\xFF"):
            return "image/jpeg"
        if sample.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"WEBP":
            return "image/webp"
        return None

    async def upsert_doctor_image(self, file: UploadFile, doctor_id: str) -> None:
        normalized_doctor_id = str(doctor_id or "").strip()
        if not normalized_doctor_id:
            return

        content = await file.read()
        await file.seek(0)
        if not content:
            return

        detected_media_type = self._detect_image_media_type(content)
        if detected_media_type is None:
            return

        object_key = self._doctor_image_object_key(normalized_doctor_id)

        if self.backend == "local":
            destination = self.upload_dir / object_key
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            return

        if self.backend == "cloudinary":
            _, cloudinary_uploader = self._get_cloudinary_modules()
            folder = f"{settings.CLOUDINARY_UPLOAD_FOLDER}/doctor-images/{normalized_doctor_id}"
            cloudinary_uploader.upload(
                content,
                folder=folder,
                public_id="current",
                resource_type="image",
                format="jpg",
                overwrite=True,
                invalidate=True,
            )
            return

        s3_client = self._get_s3_client()
        s3_client.upload_fileobj(
            BytesIO(content),
            self._get_required_bucket(),
            object_key,
            ExtraArgs={"ContentType": detected_media_type},
        )

    async def get_doctor_image(self, doctor_id: str) -> ResolvedDoctorImage | None:
        normalized_doctor_id = str(doctor_id or "").strip()
        if not normalized_doctor_id:
            return None

        object_key = self._doctor_image_object_key(normalized_doctor_id)

        if self.backend == "local":
            path = self.upload_dir / object_key
            if not path.exists():
                return None
            media_type = self._detect_image_media_type(path.read_bytes())
            return ResolvedDoctorImage(
                storage_reference=str(path),
                media_type=media_type or "application/octet-stream",
                is_local_file=True,
            )

        if self.backend == "cloudinary":
            try:
                cloudinary_utils = import_module("cloudinary.utils")
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "cloudinary is required when STORAGE_BACKEND is 'cloudinary'. "
                    "Install it with: pip install cloudinary"
                ) from exc

            public_id = f"{settings.CLOUDINARY_UPLOAD_FOLDER}/doctor-images/{normalized_doctor_id}/current"
            url, _ = cloudinary_utils.cloudinary_url(
                public_id,
                resource_type="image",
                secure=True,
                format="jpg",
            )
            return ResolvedDoctorImage(
                storage_reference=str(url),
                media_type=None,
                is_local_file=False,
            )

        s3_client = self._get_s3_client()
        try:
            metadata = s3_client.head_object(Bucket=self._get_required_bucket(), Key=object_key)
        except Exception:
            return None
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._get_required_bucket(), "Key": object_key},
            ExpiresIn=3600,
        )
        return ResolvedDoctorImage(
            storage_reference=url,
            media_type=metadata.get("ContentType"),
            is_local_file=False,
        )

    async def store_file(self, file: UploadFile, user_id: str) -> StoredFile:
        validate_upload_extension(file.filename or "")
        validate_upload_content_type(file.content_type, file.filename)
        await validate_upload_size(file)

        suffix = Path(file.filename or "").suffix.lower()
        current_time = datetime.now(timezone.utc)
        date_path = current_time.strftime("%Y/%m/%d")
        filename = f"{uuid4()}{suffix}"
        record_file_path = self._build_record_file_path(filename, current_time)

        if self.backend == "local":
            object_path = f"users/{user_id}/{date_path}/{filename}"
            destination = self.upload_dir / object_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as out:
                out.write(await file.read())
            await file.seek(0)
            return StoredFile(
                file_name=filename,
                file_path=record_file_path,
                storage_reference=str(destination),
            )

        if self.backend == "cloudinary":
            # Read file content for Cloudinary upload
            file_content = await file.read()
            await file.seek(0)

            # Keep folder and public_id separate to avoid duplicated path segments in URL.
            cloudinary_date_path = self._build_date_path(current_time)
            folder = f"{settings.CLOUDINARY_UPLOAD_FOLDER}/users/{user_id}/{cloudinary_date_path}"
            public_id = filename.split(".")[0]

            # Upload to Cloudinary
            _, cloudinary_uploader = self._get_cloudinary_modules()
            upload_result = cloudinary_uploader.upload(
                file_content,
                public_id=public_id,
                folder=folder,
                resource_type="auto",
            )
            return StoredFile(
                file_name=filename,
                file_path=record_file_path,
                storage_reference=upload_result["secure_url"],
            )

        # S3/MinIO upload
        object_path = f"users/{user_id}/{date_path}/{filename}"
        s3_client = self._get_s3_client()
        s3_client.upload_fileobj(file.file, self._get_required_bucket(), object_path)
        if settings.VERIFY_REMOTE_UPLOAD:
            self._verify_remote_upload(object_path)
        await file.seek(0)
        return StoredFile(
            file_name=filename,
            file_path=record_file_path,
            storage_reference=object_path,
        )

    async def upload_file(self, file: UploadFile, user_id: str) -> str:
        stored_file = await self.store_file(file, user_id)
        return stored_file.storage_reference

    @staticmethod
    def _processing_dir() -> Path:
        tmp_dir = Path("/tmp/healthsynch/processing")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir

    @classmethod
    def _write_processing_bytes(cls, content: bytes, suffix: str) -> str:
        local_path = cls._processing_dir() / f"{uuid4()}{suffix or '.tmp'}"
        local_path.write_bytes(content)
        return str(local_path)

    @classmethod
    async def materialize_upload_for_processing(cls, file: UploadFile) -> tuple[str, bool]:
        suffix = Path(file.filename or "").suffix.lower() or ".tmp"
        content = await file.read()
        await file.seek(0)
        if not content:
            raise RuntimeError("Uploaded file is empty and cannot be processed.")
        local_path = cls._write_processing_bytes(content, suffix)
        return local_path, True

    async def materialize_for_processing(self, file_path: str) -> tuple[str, bool]:
        if self.backend == "local":
            return file_path, False

        if self.backend == "cloudinary":
            # For Cloudinary, download from URL to temp file
            import httpx

            suffix = Path(file_path).suffix.lower() or ".tmp"

            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(file_path)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Unable to download Cloudinary file for processing (HTTP {response.status_code})."
                )
            content = response.content or b""
            if not content:
                raise RuntimeError("Downloaded Cloudinary file is empty and cannot be processed.")
            if suffix == ".pdf" and not content.lstrip().startswith(b"%PDF"):
                raise RuntimeError("Downloaded Cloudinary content is not a valid PDF stream.")
            local_path = self._write_processing_bytes(content, suffix)
            return local_path, True

        # S3/MinIO download
        suffix = Path(file_path).suffix.lower()
        local_path = self._processing_dir() / f"{uuid4()}{suffix or '.tmp'}"

        s3_client = self._get_s3_client()
        s3_client.download_file(self._get_required_bucket(), file_path, str(local_path))
        return str(local_path), True

    @staticmethod
    async def cleanup_processing_file(local_path: str, should_cleanup: bool) -> None:
        if not should_cleanup:
            return
        Path(local_path).unlink(missing_ok=True)

    async def get_file_url(self, file_path: str, expiry: int = 3600) -> str:
        if self.backend == "local":
            return file_path

        if self.backend == "cloudinary":
            # For Cloudinary, file_path is already the secure URL
            # We can generate transformations if needed
            return file_path

        s3_client = self._get_s3_client()
        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._get_required_bucket(), "Key": file_path},
            ExpiresIn=expiry,
        )

    async def delete_file(self, file_path: str) -> bool:
        if self.backend == "local":
            path = Path(file_path)
            if path.exists():
                path.unlink()
            return True

        if self.backend == "cloudinary":
            # Extract public_id from Cloudinary URL
            if "cloudinary.com" in file_path:
                try:
                    reference = self._parse_cloudinary_reference(file_path)
                    if reference is None:
                        raise ValueError("Unable to parse Cloudinary public_id from URL.")
                    public_id, resource_type = reference
                    _, cloudinary_uploader = self._get_cloudinary_modules()
                    cloudinary_uploader.destroy(public_id, resource_type=resource_type)
                except Exception as e:
                    logging.getLogger(__name__).warning("Failed to delete from Cloudinary: %s", e)
            return True

        s3_client = self._get_s3_client()
        s3_client.delete_object(Bucket=self._get_required_bucket(), Key=file_path)
        return True
