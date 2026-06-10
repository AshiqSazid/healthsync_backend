from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.symptom import Symptom
from app.models.user import User
from app.schemas.symptom import SymptomCreate, SymptomResponse, SymptomUpdate

router = APIRouter()


@router.post("/", response_model=SymptomResponse, status_code=status.HTTP_201_CREATED)
def create_symptom(
    payload: SymptomCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> Symptom:
    exists = db.query(Symptom).filter(Symptom.name == payload.name).first()
    if exists:
        raise HTTPException(status_code=400, detail="Symptom with this name already exists")

    symptom = Symptom(**payload.model_dump())
    db.add(symptom)
    db.commit()
    db.refresh(symptom)
    return symptom


@router.get("/", response_model=list[SymptomResponse])
def list_symptoms(
    db: Annotated[Session, Depends(get_db)],
    category: str | None = Query(default=None),
) -> list[Symptom]:
    query = db.query(Symptom)
    if category:
        query = query.filter(Symptom.category == category)
    return query.order_by(Symptom.created_at.desc()).all()


@router.get("/{symptom_id}", response_model=SymptomResponse)
def get_symptom(
    symptom_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Symptom:
    symptom = db.query(Symptom).filter(Symptom.id == symptom_id).first()
    if not symptom:
        raise HTTPException(status_code=404, detail="Symptom not found")
    return symptom


@router.put("/{symptom_id}", response_model=SymptomResponse)
def update_symptom(
    symptom_id: str,
    payload: SymptomUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> Symptom:
    symptom = db.query(Symptom).filter(Symptom.id == symptom_id).first()
    if not symptom:
        raise HTTPException(status_code=404, detail="Symptom not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(symptom, key, value)

    db.add(symptom)
    db.commit()
    db.refresh(symptom)
    return symptom


@router.delete("/{symptom_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_symptom(
    symptom_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> None:
    symptom = db.query(Symptom).filter(Symptom.id == symptom_id).first()
    if not symptom:
        raise HTTPException(status_code=404, detail="Symptom not found")

    db.delete(symptom)
    db.commit()
