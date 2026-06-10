from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.hospital import Hospital
from app.models.user import User
from app.schemas.hospital import HospitalCreate, HospitalResponse, HospitalUpdate

router = APIRouter()


@router.post("/", response_model=HospitalResponse, status_code=status.HTTP_201_CREATED)
def create_hospital(
    payload: HospitalCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> Hospital:
    hospital = Hospital(**payload.model_dump())
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return hospital


@router.get("/", response_model=list[HospitalResponse])
def list_hospitals(
    db: Annotated[Session, Depends(get_db)],
    city: str | None = Query(default=None),
) -> list[Hospital]:
    query = db.query(Hospital)
    if city:
        query = query.filter(Hospital.city.ilike(f"%{city}%"))
    return query.order_by(Hospital.created_at.desc()).all()


@router.get("/{hospital_id}", response_model=HospitalResponse)
def get_hospital(
    hospital_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Hospital:
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return hospital


@router.put("/{hospital_id}", response_model=HospitalResponse)
def update_hospital(
    hospital_id: str,
    payload: HospitalUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> Hospital:
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(hospital, key, value)

    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return hospital


@router.delete("/{hospital_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hospital(
    hospital_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> None:
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    db.delete(hospital)
    db.commit()
