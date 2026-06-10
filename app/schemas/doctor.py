from datetime import datetime
from decimal import Decimal

from pydantic import field_validator

from app.schemas.common import ORMModel


def _coerce_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    return [str(value)]


def _coerce_dict_list(value: object) -> list[dict]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


class DoctorBase(ORMModel):
    specialization: list[str] = []
    sub_specializations: list[str] = []
    license_number: str | None = None
    experience_years: int = 0
    consultation_fee: Decimal = Decimal("0")
    hospital_id: str | None = None
    average_rating: float = 0.0
    available_slots: list[dict] = []
    languages_spoken: list[str] = []
    conditions_treated: list[str] = []
    education: list[dict] = []
    certifications: list[dict] = []
    photo_url: str | None = None
    photo_filename: str | None = None

    @field_validator("specialization", "sub_specializations", "languages_spoken", "conditions_treated", mode="before")
    @classmethod
    def _normalize_str_lists(cls, value: object) -> list[str]:
        return _coerce_str_list(value)

    @field_validator("available_slots", "education", "certifications", mode="before")
    @classmethod
    def _normalize_dict_lists(cls, value: object) -> list[dict]:
        return _coerce_dict_list(value)

    @field_validator("experience_years", mode="before")
    @classmethod
    def _normalize_experience_years(cls, value: object) -> int:
        if value is None or value == "":
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @field_validator("consultation_fee", mode="before")
    @classmethod
    def _normalize_consultation_fee(cls, value: object) -> Decimal:
        if value is None or value == "":
            return Decimal("0")
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")

    @field_validator("average_rating", mode="before")
    @classmethod
    def _normalize_average_rating(cls, value: object) -> float:
        if value is None or value == "":
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


class DoctorCreate(DoctorBase):
    user_id: str


class DoctorUpdate(ORMModel):
    specialization: list[str] | None = None
    sub_specializations: list[str] | None = None
    license_number: str | None = None
    experience_years: int | None = None
    consultation_fee: Decimal | None = None
    hospital_id: str | None = None
    average_rating: float | None = None
    available_slots: list[dict] | None = None
    languages_spoken: list[str] | None = None
    conditions_treated: list[str] | None = None
    education: list[dict] | None = None
    certifications: list[dict] | None = None
    photo_url: str | None = None
    photo_filename: str | None = None


class DoctorResponse(DoctorBase):
    id: str
    user_id: str | None = None
    display_name: str | None = None
    image_url: str | None = None
    imageUrl: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_id(cls, value: object) -> str:
        return "" if value is None else str(value)
