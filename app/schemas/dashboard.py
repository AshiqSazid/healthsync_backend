from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import Field

from app.models.enums import BookingStatus, BookingType, UserRole
from app.schemas.common import ORMModel


class DashboardUserSummary(ORMModel):
    id: str
    name: str
    email: str
    username: str
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime


class DashboardDoctorSummary(ORMModel):
    id: str
    user_id: str
    display_name: str
    email: str | None = None
    license_number: str
    specialization: list[str] = Field(default_factory=list)
    experience_years: int = 0
    consultation_fee: Decimal = Decimal("0")
    hospital_id: str | None = None
    hospital_name: str | None = None
    average_rating: float = 0.0
    created_at: datetime


class DashboardHospitalSummary(ORMModel):
    id: str
    name: str
    address: str
    city: str
    country: str
    phone: str | None = None
    email: str | None = None


class DashboardBookingSummary(ORMModel):
    id: str
    user_id: str | None = None
    doctor_id: str | None = None
    hospital_id: str | None = None
    patient_name: str | None = None
    doctor_name: str | None = None
    hospital_name: str | None = None
    linked_assessment_id: str | None = None
    provider_name: str | None = None
    location_name: str | None = None
    appointment_date: date
    appointment_time: time
    status: BookingStatus
    booking_type: BookingType
    symptoms_summary: str | None = None
    created_at: datetime


class DashboardProfileSummary(ORMModel):
    id: str
    user_id: str
    full_name: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    blood_group: str | None = None
    created_at: datetime
    updated_at: datetime


class DashboardDiagnosticSummary(ORMModel):
    id: str
    user_id: str
    doctor_id: str
    doctor_name: str | None = None
    diagnosis: str | None = None
    follow_up_date: date | None = None
    created_at: datetime


class AdminDashboardCounts(ORMModel):
    total_users: int = 0
    total_doctors: int = 0
    total_hospitals: int = 0
    total_bookings: int = 0
    pending_bookings: int = 0
    confirmed_bookings: int = 0
    completed_bookings: int = 0
    cancelled_bookings: int = 0


class AdminDashboardOverview(ORMModel):
    counts: AdminDashboardCounts
    recent_users: list[DashboardUserSummary] = Field(default_factory=list)
    recent_doctors: list[DashboardDoctorSummary] = Field(default_factory=list)
    recent_bookings: list[DashboardBookingSummary] = Field(default_factory=list)


class DoctorDashboardCounts(ORMModel):
    total_bookings: int = 0
    pending_bookings: int = 0
    confirmed_bookings: int = 0
    completed_bookings: int = 0
    cancelled_bookings: int = 0
    today_bookings: int = 0


class DoctorDashboardOverview(ORMModel):
    doctor_profile: DashboardDoctorSummary | None = None
    hospital: DashboardHospitalSummary | None = None
    booking_counts: DoctorDashboardCounts = Field(default_factory=DoctorDashboardCounts)
    upcoming_bookings: list[DashboardBookingSummary] = Field(default_factory=list)
    recent_bookings: list[DashboardBookingSummary] = Field(default_factory=list)


class UserDashboardCounts(ORMModel):
    total_bookings: int = 0
    pending_bookings: int = 0
    confirmed_bookings: int = 0
    completed_bookings: int = 0
    cancelled_bookings: int = 0
    total_diagnostics: int = 0


class UserDashboardOverview(ORMModel):
    profile: DashboardProfileSummary | None = None
    has_profile: bool = False
    booking_counts: UserDashboardCounts = Field(default_factory=UserDashboardCounts)
    upcoming_bookings: list[DashboardBookingSummary] = Field(default_factory=list)
    recent_bookings: list[DashboardBookingSummary] = Field(default_factory=list)
    recent_diagnostics: list[DashboardDiagnosticSummary] = Field(default_factory=list)


class DashboardContextResponse(ORMModel):
    user: DashboardUserSummary
    role: UserRole
    available_interfaces: list[UserRole] = Field(default_factory=list)
    admin: AdminDashboardOverview | None = None
    doctor: DoctorDashboardOverview | None = None
    user_dashboard: UserDashboardOverview | None = None
