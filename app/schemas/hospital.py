from datetime import datetime

from app.schemas.common import ORMModel


class HospitalBase(ORMModel):
    name: str
    address: str
    city: str
    country: str
    pincode: str | None = None
    phone: str | None = None
    email: str | None = None
    facilities: list[str] = []
    operating_hours: dict = {}
    emergency_services: bool = False
    departments: list[str] = []


class HospitalCreate(HospitalBase):
    pass


class HospitalUpdate(ORMModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    pincode: str | None = None
    phone: str | None = None
    email: str | None = None
    facilities: list[str] | None = None
    operating_hours: dict | None = None
    emergency_services: bool | None = None
    departments: list[str] | None = None


class HospitalResponse(HospitalBase):
    id: str
    created_at: datetime
    updated_at: datetime
