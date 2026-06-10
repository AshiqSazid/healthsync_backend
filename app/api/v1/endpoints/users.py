from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, require_roles
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate

router = APIRouter()


@router.get("/", response_model=list[UserResponse])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> list[User]:
    return db.query(User).all()


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user_by_admin(
    user_id: str,
    payload: UserUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        user.password_hash = get_password_hash(data.pop("password"))

    for key, value in data.items():
        setattr(user, key, value)

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    data = payload.model_dump(exclude_unset=True)

    if "password" in data and data["password"]:
        current_user.password_hash = get_password_hash(data.pop("password"))

    for key, value in data.items():
        setattr(current_user, key, value)

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user
