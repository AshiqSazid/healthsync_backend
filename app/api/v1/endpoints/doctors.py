import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, require_roles
from app.core.config import settings
from app.db.session import get_db
from app.local_doctors import get_doctor_by_id, get_doctors_by_specialization, get_doctors_with_urls
from app.models.doctor import Doctor
from app.models.enums import UserRole
from app.models.hospital import Hospital
from app.models.user import User
from app.schemas.doctor import DoctorCreate, DoctorResponse, DoctorUpdate

# Photos live in backend/data/ on local and on Vercel deployments.
_DATA_DIR = Path(__file__).resolve().parents[4] / "data"


router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_backend_base(request: Request) -> str:
    if settings.BACKEND_PUBLIC_URL:
        return settings.BACKEND_PUBLIC_URL
    forwarded_host = str(request.headers.get("x-forwarded-host") or "").strip()
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "https").strip() or "https"
    if forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}"
    base = str(request.base_url).rstrip("/")
    if "localhost" in base or "127.0.0.1" in base:
        return "https://health-synch-backend.vercel.app"
    return base


def _normalize_name(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _build_local_photo_lookup(base_url: str) -> dict[str, dict]:
    entries = get_doctors_with_urls(base_url)
    lookup: dict[str, dict] = {}
    for item in entries:
        names = {_normalize_name(item.get("name")), _normalize_name(item.get("display_name"))}
        for key in names:
            if key:
                lookup[key] = item
    return lookup


# ---------------------------------------------------------------------------
# Local (static config) doctor endpoints — no DB, no external API
# ---------------------------------------------------------------------------

@router.get("/local/specialization/{spec}")
def list_local_doctors_by_specialization(spec: str, request: Request) -> list[dict]:
    return get_doctors_by_specialization(spec, _resolve_backend_base(request))


@router.get("/local/{doctor_id}/photo")
def serve_local_doctor_photo(doctor_id: int) -> FileResponse:
    doc = get_doctor_by_id(doctor_id, "")
    if not doc or not doc.get("photo_filename"):
        raise HTTPException(status_code=404, detail="Photo not found")
    photo_path = _DATA_DIR / doc["photo_filename"]
    if not photo_path.exists():
        raise HTTPException(status_code=404, detail="Photo file not found")
    suffix = photo_path.suffix.lower()
    media_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    return FileResponse(str(photo_path), media_type=media_type)


@router.get("/local/{doctor_id}")
def get_local_doctor(doctor_id: int, request: Request) -> dict:
    doc = get_doctor_by_id(doctor_id, _resolve_backend_base(request))
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doc


@router.get("/local")
def list_local_doctors(request: Request) -> list[dict]:
    return get_doctors_with_urls(_resolve_backend_base(request))


@router.get("/search", response_model=list[DoctorResponse])
def search_doctors(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = Query(default=None),
    specialization: str | None = Query(default=None),
) -> list[Doctor]:
    try:
        query = db.query(Doctor)
        if q:
            query = query.join(User, Doctor.user_id == User.id).filter(User.username.ilike(f"%{q}%"))
        if specialization:
            query = query.filter(Doctor.specialization.isnot(None))
        return query.order_by(Doctor.created_at.desc()).all()
    except SQLAlchemyError:
        logger.exception("Doctor search failed due database error; returning empty result set")
        return []


@router.get("/", response_model=list[DoctorResponse])
def list_doctors(
    db: Annotated[Session, Depends(get_db)],
    hospital_id: str | None = Query(default=None),
) -> list[Doctor]:
    try:
        query = db.query(Doctor)
        if hospital_id:
            query = query.filter(Doctor.hospital_id == hospital_id)
        return query.order_by(Doctor.created_at.desc()).all()
    except SQLAlchemyError:
        logger.exception("Doctor listing failed due database error; returning empty result set")
        return []


@router.get("/{doctor_id}", response_model=DoctorResponse)
def get_doctor(
    doctor_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Doctor:
    try:
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    except SQLAlchemyError as exc:
        logger.exception("Doctor detail lookup failed due database error doctor_id=%s", doctor_id)
        raise HTTPException(status_code=503, detail="Doctor service temporarily unavailable") from exc
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


@router.get("/{doctor_id}/availability")
def get_doctor_availability(
    doctor_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    except SQLAlchemyError as exc:
        logger.exception("Doctor availability lookup failed due database error doctor_id=%s", doctor_id)
        raise HTTPException(status_code=503, detail="Doctor service temporarily unavailable") from exc
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return {"doctor_id": doctor.id, "available_slots": doctor.available_slots or []}


@router.post("/", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
def create_doctor(
    payload: DoctorCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> Doctor:
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.hospital_id:
        hospital = db.query(Hospital).filter(Hospital.id == payload.hospital_id).first()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found")

    exists = db.query(Doctor).filter((Doctor.user_id == payload.user_id) | (Doctor.license_number == payload.license_number)).first()
    if exists:
        raise HTTPException(status_code=400, detail="Doctor already exists for this user/license")

    doctor = Doctor(**payload.model_dump())
    db.add(doctor)
    user.role = UserRole.DOCTOR
    db.add(user)
    db.commit()
    db.refresh(doctor)
    return doctor


@router.put("/{doctor_id}", response_model=DoctorResponse)
def update_doctor(
    doctor_id: str,
    payload: DoctorUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Doctor:
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    if current_user.role not in {UserRole.ADMIN, UserRole.DOCTOR}:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    if current_user.role == UserRole.DOCTOR and doctor.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot edit another doctor profile")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(doctor, key, value)

    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor


@router.post("/sync-photos", status_code=status.HTTP_200_OK)
def sync_doctor_photos(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> dict:
    base_url = _resolve_backend_base(request)
    lookup = _build_local_photo_lookup(base_url)
    doctors = db.query(Doctor).join(User, Doctor.user_id == User.id).all()
    updated = 0
    for doctor in doctors:
        candidates = [_normalize_name(doctor.display_name), _normalize_name(doctor.user.name if doctor.user else None)]
        match = next((lookup.get(name) for name in candidates if name and lookup.get(name)), None)
        if not match:
            continue
        next_photo_url = str(match.get("photo_url") or "").strip() or None
        next_photo_filename = str(match.get("photo_filename") or "").strip() or None
        if doctor.photo_url != next_photo_url or doctor.photo_filename != next_photo_filename:
            doctor.photo_url = next_photo_url
            doctor.photo_filename = next_photo_filename
            db.add(doctor)
            updated += 1
    if updated:
        db.commit()
    return {"updated": updated, "total": len(doctors)}
