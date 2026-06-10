from __future__ import annotations

from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.assessment_document import AssessmentDocument
from app.models.booking import Booking
from app.models.doctor import Doctor
from app.models.enums import UserRole
from app.models.hospital import Hospital
from app.models.recommendation import DoctorRecommendation
from app.models.user import User
from app.schemas.booking import BookingCreate, BookingFromRecommendation


class BookingService:
    GUEST_BOOKING_USERNAME = "guest_booking_user"
    GUEST_BOOKING_EMAIL = "guest-booking@example.com"
    EXTERNAL_PROVIDER_EMAIL_DOMAIN = "providers.healthsync.example.com"

    async def create_manual(self, db: Session, user_id: str, payload: BookingCreate) -> Booking:
        client_request_id = str(payload.client_request_id or "").strip() or None
        if client_request_id:
            existing_booking = (
                db.query(Booking)
                .filter(Booking.client_request_id == client_request_id, Booking.user_id == user_id)
                .first()
            )
            if existing_booking is not None:
                return existing_booking

        doctor = None
        hospital = None

        if payload.linked_assessment_id:
            linked_assessment = (
                db.query(AssessmentDocument)
                .filter(
                    AssessmentDocument.id == payload.linked_assessment_id,
                    AssessmentDocument.user_id == user_id,
                )
                .first()
            )
            if linked_assessment is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")

        if payload.doctor_id:
            doctor = db.query(Doctor).filter(Doctor.id == payload.doctor_id).first()
            if not doctor:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found")

        if payload.hospital_id:
            hospital = db.query(Hospital).filter(Hospital.id == payload.hospital_id).first()
            if not hospital:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hospital not found")
        elif doctor and doctor.hospital_id:
            hospital = db.query(Hospital).filter(Hospital.id == doctor.hospital_id).first()

        if not doctor and not str(payload.provider_name or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider information is required for external bookings",
            )

        booking = Booking(
            user_id=user_id,
            doctor_id=doctor.id if doctor else None,
            hospital_id=hospital.id if hospital else None,
            recommendation_id=payload.recommendation_id,
            linked_assessment_id=payload.linked_assessment_id,
            client_request_id=client_request_id,
            provider_name=payload.provider_name or (doctor.display_name if doctor else None),
            provider_external_id=payload.provider_external_id,
            location_name=payload.location_name or (hospital.name if hospital else None),
            location_address=payload.location_address or (hospital.address if hospital else None),
            patient_name_snapshot=str(payload.patient_name or "").strip() or None,
            patient_phone_snapshot=str(payload.patient_phone or "").strip() or None,
            patient_sex_snapshot=str(payload.patient_sex or "").strip() or None,
            appointment_date=payload.appointment_date,
            appointment_time=payload.appointment_time,
            booking_type=payload.booking_type,
            symptoms_summary=payload.symptoms_summary,
            prescription_ids=payload.prescription_ids,
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)
        return booking

    def get_or_create_guest_booking_user(self, db: Session) -> User:
        guest_user = db.query(User).filter(User.username == self.GUEST_BOOKING_USERNAME).first()
        if guest_user is None:
            guest_user = User(
                name="Guest Booking User",
                email=self.GUEST_BOOKING_EMAIL,
                username=self.GUEST_BOOKING_USERNAME,
                password_hash=get_password_hash(uuid4().hex),
                role=UserRole.USER,
                is_active=True,
                is_verified=False,
            )
            db.add(guest_user)
            db.commit()
            db.refresh(guest_user)
            return guest_user

        dirty = False
        if guest_user.email != self.GUEST_BOOKING_EMAIL:
            guest_user.email = self.GUEST_BOOKING_EMAIL
            dirty = True
        if guest_user.role != UserRole.USER:
            guest_user.role = UserRole.USER
            dirty = True
        if not guest_user.is_active:
            guest_user.is_active = True
            dirty = True

        if dirty:
            db.add(guest_user)
            db.commit()
            db.refresh(guest_user)

        return guest_user

    def _build_external_provider_key(self, payload: BookingCreate) -> str:
        return "|".join(
            [
                str(payload.provider_external_id or "").strip(),
                str(payload.provider_name or "").strip(),
                str(payload.location_name or "").strip(),
                str(payload.location_address or "").strip(),
            ]
        ).lower()

    def _get_or_create_external_hospital(self, db: Session, payload: BookingCreate) -> Hospital:
        hospital_name = str(payload.location_name or "").strip() or "External Consultation"
        hospital_address = str(payload.location_address or "").strip() or "External booking location"

        hospital = (
            db.query(Hospital)
            .filter(Hospital.name == hospital_name, Hospital.address == hospital_address)
            .first()
        )
        if hospital:
            return hospital

        hospital = Hospital(
            name=hospital_name,
            address=hospital_address,
            city="Unknown",
            country="Unknown",
        )
        db.add(hospital)
        db.commit()
        db.refresh(hospital)
        return hospital

    def _get_or_create_external_doctor(self, db: Session, payload: BookingCreate, hospital: Hospital) -> Doctor:
        provider_key = self._build_external_provider_key(payload)
        stable_id = uuid5(NAMESPACE_URL, provider_key or "healthsync-external-provider").hex
        license_number = f"EXT-{stable_id[:12].upper()}"

        doctor = db.query(Doctor).filter(Doctor.license_number == license_number).first()
        if doctor:
            if hospital.id and doctor.hospital_id != hospital.id:
                doctor.hospital_id = hospital.id
                db.add(doctor)
                db.commit()
                db.refresh(doctor)
            return doctor

        username = f"ext-{stable_id[:16]}"
        email = f"{username}@{self.EXTERNAL_PROVIDER_EMAIL_DOMAIN}"
        user = db.query(User).filter((User.username == username) | (User.email == email)).first()
        if user is None:
            user = User(
                name=str(payload.provider_name or "").strip() or "External Provider",
                email=email,
                username=username,
                password_hash=get_password_hash(stable_id),
                role=UserRole.DOCTOR,
                is_active=False,
                is_verified=False,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        doctor = Doctor(
            user_id=user.id,
            license_number=license_number,
            hospital_id=hospital.id,
            specialization=[],
            sub_specializations=[],
            available_slots=[],
        )
        db.add(doctor)
        db.commit()
        db.refresh(doctor)
        return doctor

    async def create_from_recommendation(
        self, db: Session, user_id: str, payload: BookingFromRecommendation
    ) -> Booking:
        recommendation = (
            db.query(DoctorRecommendation)
            .filter(DoctorRecommendation.id == payload.recommendation_id, DoctorRecommendation.user_id == user_id)
            .first()
        )
        if not recommendation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")

        doctor = db.query(Doctor).filter(Doctor.id == payload.doctor_id).first()
        if not doctor:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found")
        if not doctor.hospital_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Doctor does not have a hospital")

        booking = Booking(
            user_id=user_id,
            doctor_id=doctor.id,
            hospital_id=doctor.hospital_id,
            recommendation_id=recommendation.id,
            appointment_date=payload.preferred_date,
            appointment_time=payload.preferred_time,
            symptoms_summary=payload.symptoms_summary,
            prescription_ids=payload.prescription_ids,
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)
        return booking
