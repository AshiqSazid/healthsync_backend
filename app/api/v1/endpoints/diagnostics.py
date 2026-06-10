from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, require_roles
from app.db.session import get_db
from app.models.diagnostic import Diagnostic
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.diagnostic import DiagnosticCreate, DiagnosticResponse, DiagnosticUpdate

router = APIRouter()


@router.post("/", response_model=DiagnosticResponse)
def create_diagnostic(
    payload: DiagnosticCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.DOCTOR, UserRole.ADMIN))],
) -> Diagnostic:
    diagnostic = Diagnostic(**payload.model_dump())
    db.add(diagnostic)
    db.commit()
    db.refresh(diagnostic)
    return diagnostic


@router.get("/", response_model=list[DiagnosticResponse])
def list_diagnostics(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[Diagnostic]:
    query = db.query(Diagnostic)
    if current_user.role == UserRole.USER:
        query = query.filter(Diagnostic.user_id == current_user.id)
    elif current_user.role == UserRole.DOCTOR and current_user.doctor_profile:
        query = query.filter(Diagnostic.doctor_id == current_user.doctor_profile.id)

    return query.order_by(Diagnostic.created_at.desc()).all()


@router.get("/{diagnostic_id}", response_model=DiagnosticResponse)
def get_diagnostic(
    diagnostic_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Diagnostic:
    diagnostic = db.query(Diagnostic).filter(Diagnostic.id == diagnostic_id).first()
    if not diagnostic:
        raise HTTPException(status_code=404, detail="Diagnostic not found")

    if current_user.role == UserRole.USER and diagnostic.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    if current_user.role == UserRole.DOCTOR and current_user.doctor_profile and diagnostic.doctor_id != current_user.doctor_profile.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return diagnostic


@router.put("/{diagnostic_id}", response_model=DiagnosticResponse)
def update_diagnostic(
    diagnostic_id: str,
    payload: DiagnosticUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.DOCTOR, UserRole.ADMIN))],
) -> Diagnostic:
    diagnostic = db.query(Diagnostic).filter(Diagnostic.id == diagnostic_id).first()
    if not diagnostic:
        raise HTTPException(status_code=404, detail="Diagnostic not found")

    if current_user.role == UserRole.DOCTOR:
        if not current_user.doctor_profile or diagnostic.doctor_id != current_user.doctor_profile.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(diagnostic, key, value)

    db.add(diagnostic)
    db.commit()
    db.refresh(diagnostic)
    return diagnostic
