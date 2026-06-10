from datetime import date, datetime

from app.schemas.common import ORMModel


class ProfileBase(ORMModel):
    full_name: str | None = None
    phone: str | None = None
    bio: str | None = None
    timezone: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    blood_group: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    emergency_contact: str | None = None
    medical_history: dict = {}
    chronic_conditions: list[str] = []
    allergies: list[str] = []


class ProfileCreate(ProfileBase):
    user_id: str


class ProfileUpdate(ORMModel):
    full_name: str | None = None
    phone: str | None = None
    bio: str | None = None
    timezone: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    blood_group: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    emergency_contact: str | None = None
    medical_history: dict | None = None
    chronic_conditions: list[str] | None = None
    allergies: list[str] | None = None


class ProfileResponse(ProfileBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
