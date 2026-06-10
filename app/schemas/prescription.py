from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import ORMModel
from app.core.config import settings
from app.utils.file_validators import normalize_upload_content_type, SUPPORTED_PDF_CONTENT_TYPES


class MedicationEntry(ORMModel):
    name: str
    dosage: str | None = None
    frequency: str | None = None
    duration: str | None = None


class PrescriptionParsedData(ORMModel):
    medications: list[MedicationEntry] = []
    diagnosis: str | None = None
    doctor_name: str | None = None
    doctor_specialization: str | None = None
    prescription_date: str | None = None
    instructions: str | None = None
    follow_up: str | None = None


class PrescriptionUploadMeta(ORMModel):
    filename: str
    content_type: str
    size_bytes: int = Field(ge=1)

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        normalized = normalize_upload_content_type(value)
        if not (normalized.startswith("image/") or normalized in SUPPORTED_PDF_CONTENT_TYPES):
            raise ValueError("Unsupported file type")
        return normalized

    @field_validator("size_bytes")
    @classmethod
    def validate_file_size(cls, value: int) -> int:
        if value > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise ValueError(f"File size exceeds {settings.MAX_UPLOAD_MB}MB")
        return value


class PrescriptionAnalysis(ORMModel):
    medications: list[MedicationEntry] = []
    diagnosis: str | None = None
    doctor_name: str | None = None
    doctor_specialization: str | None = None
    prescription_date: str | None = None
    instructions: str | None = None
    follow_up: str | None = None
    confidence_score: float = 0.0


class PrescriptionCreate(ORMModel):
    doctor_id: str | None = None
    image_url: str
    parsed_data: dict = {}
    ai_analysis: dict = {}
    confidence_score: float = 0.0


class PrescriptionUpdate(ORMModel):
    doctor_id: str | None = None
    parsed_data: dict | None = None
    ai_analysis: dict | None = None
    confidence_score: float | None = None
    is_verified: bool | None = None


class PrescriptionResponse(ORMModel):
    id: str
    user_id: str
    doctor_id: str | None = None
    image_url: str
    upload_date: datetime
    parsed_data: dict
    ai_analysis: dict
    confidence_score: float
    is_verified: bool
    verified_by_doctor_id: str | None = None
    created_at: datetime
    updated_at: datetime


class PrescriptionVerifyRequest(ORMModel):
    is_verified: bool = True
