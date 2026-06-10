from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, require_roles
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.profile import Profile
from app.models.user import User
from app.schemas.profile import ProfileResponse, ProfileUpdate

router = APIRouter()


@router.get("/me", response_model=ProfileResponse)
def get_my_profile(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Profile:
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.put("/me", response_model=ProfileResponse)
def upsert_my_profile(
    payload: ProfileUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Profile:
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if not profile:
        profile = Profile(user_id=current_user.id)

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)

    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/", response_model=list[ProfileResponse])
def list_profiles(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.DOCTOR))],
) -> list[Profile]:
    return db.query(Profile).all()


@router.get("/{user_id}", response_model=ProfileResponse)
def get_profile_by_user(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.DOCTOR))],
) -> Profile:
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile
