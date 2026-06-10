from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_current_user_optional
from app.core.config import settings
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.profile import Profile
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    AuthUserResponse,
    ForgotPasswordRequest,
    GoogleAuthorizationUrlResponse,
    LoginRequest,
    MeResponse,
    MessageResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    ResetPasswordRequest,
    SessionCodeExchangeRequest,
    SignupRequest,
)
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserResponse
from app.services.auth_service import (
    AuthService,
    TokenExpiredError,
    TokenValidationError,
    get_auth_service,
)
from app.services.email_service import EmailService, get_email_service
from app.services.google_auth_service import (
    GoogleAuthService,
    GoogleOAuthError,
    GoogleOAuthNotConfiguredError,
    get_google_auth_service,
)
from app.services.rate_limit_service import RateLimitService, get_rate_limit_service
from app.utils.helpers import (
    build_unique_username,
    enforce_identifier_rate_limit,
    normalize_email,
    verify_token_hash,
)

logger = logging.getLogger(__name__)

router = APIRouter()

SIGNUP_DUPLICATE_EMAIL_DETAIL = "Email is already registered"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_auth_user_response(user: User) -> AuthUserResponse:
    doctor_profile_id: str | None = None
    try:
        doctor_profile = user.doctor_profile
        doctor_profile_id = str(doctor_profile.id) if doctor_profile else None
    except SQLAlchemyError:
        logger.exception("Failed to resolve doctor_profile for user_id=%s; returning null profile id", user.id)

    return AuthUserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        username=user.username,
        role=user.role,
        doctor_profile_id=doctor_profile_id,
    )


def _build_auth_response(user: User, access_token: str, refresh_token: str) -> AuthResponse:
    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_build_auth_user_response(user),
    )


def _store_refresh_token(
    *,
    db: Session,
    user: User,
    auth_service: AuthService,
    refresh_token: str,
) -> None:
    user.refresh_token = auth_service.hash_stored_token(refresh_token)
    db.add(user)
    db.commit()
    db.refresh(user)


def _issue_token_pair(
    *,
    db: Session,
    user: User,
    auth_service: AuthService,
) -> tuple[str, str]:
    token_pair = auth_service.build_token_pair(user)
    _store_refresh_token(db=db, user=user, auth_service=auth_service, refresh_token=token_pair.refresh_token)
    return token_pair.access_token, token_pair.refresh_token


def _invalid_refresh_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _normalize_next_path(next_path: str | None) -> str:
    value = str(next_path or "").strip()
    return value if value.startswith("/") else "/"


def _build_google_callback_url(request: Request) -> str:
    if settings.BACKEND_PUBLIC_URL:
        return f"{settings.BACKEND_PUBLIC_URL}{settings.API_V1_STR}/auth/google/callback"
    return str(request.url_for("google_auth_callback"))


def _build_google_frontend_callback_url(
    *, next_path: str, error: str | None = None, session_code: str | None = None
) -> str:
    query: dict[str, str] = {"next": _normalize_next_path(next_path)}
    if error:
        query["error"] = error
    if session_code:
        query["session_code"] = session_code
    return f"{settings.FRONTEND_URL}/auth/google/callback?{urlencode(query)}"


def _redirect_google_callback(
    *, next_path: str, error: str | None = None, session_code: str | None = None
) -> RedirectResponse:
    return RedirectResponse(
        url=_build_google_frontend_callback_url(next_path=next_path, error=error, session_code=session_code),
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    payload: SignupRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    email = normalize_email(payload.email)
    existing_user = db.query(User.id).filter(User.email == email).first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SIGNUP_DUPLICATE_EMAIL_DETAIL,
        )

    user = User(
        name=payload.name,
        email=email,
        username=build_unique_username(db, name=payload.name, email=email),
        password_hash=auth_service.hash_password(payload.password),
        role=UserRole.USER,
        is_active=True,
        is_verified=False,
    )
    db.add(user)

    try:
        db.flush()
        db.add(
            Profile(
                user_id=user.id,
                full_name=payload.name,
                phone=payload.phone,
            )
        )
        db.flush()
        access_token, refresh_token = _issue_token_pair(db=db, user=user, auth_service=auth_service)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SIGNUP_DUPLICATE_EMAIL_DETAIL,
        ) from exc

    auth_service.set_refresh_cookie(response, refresh_token)
    return _build_auth_response(user, access_token, refresh_token)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    rate_limit_service: Annotated[RateLimitService, Depends(get_rate_limit_service)],
) -> AuthResponse:
    identifier = str(payload.identifier or payload.email or "").strip()
    email = normalize_email(identifier) if "@" in identifier else None
    rate_limit_identifier = email or identifier.lower()
    enforce_identifier_rate_limit(
        rate_limit_service=rate_limit_service,
        identifier=rate_limit_identifier,
        endpoint="auth:login",
        max_requests=settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        message="Too many login attempts. Please try again later.",
    )

    if email:
        user = db.query(User).filter(User.email == email).first()
    else:
        user = db.query(User).filter(User.username == identifier).first()
    if not user or not auth_service.verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credentials")

    access_token, refresh_token = _issue_token_pair(db=db, user=user, auth_service=auth_service)
    rate_limit_service.reset_limit(rate_limit_identifier, endpoint="auth:login")
    auth_service.set_refresh_cookie(response, refresh_token)
    return _build_auth_response(user, access_token, refresh_token)


@router.get("/google/login-url", response_model=GoogleAuthorizationUrlResponse)
def get_google_login_url(
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    google_auth_service: Annotated[GoogleAuthService, Depends(get_google_auth_service)],
    next: Annotated[str | None, Query(alias="next")] = None,
) -> GoogleAuthorizationUrlResponse:
    next_path = _normalize_next_path(next)
    state = auth_service.create_oauth_state_token(next_path=next_path)
    try:
        authorization_url = google_auth_service.build_authorization_url(
            redirect_uri=_build_google_callback_url(request),
            state=state,
        )
    except GoogleOAuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        ) from exc
    return GoogleAuthorizationUrlResponse(authorization_url=authorization_url)


@router.get("/google/login", include_in_schema=False)
def start_google_login(
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    google_auth_service: Annotated[GoogleAuthService, Depends(get_google_auth_service)],
    next: Annotated[str | None, Query(alias="next")] = None,
) -> RedirectResponse:
    next_path = _normalize_next_path(next)
    state = auth_service.create_oauth_state_token(next_path=next_path)
    try:
        authorization_url = google_auth_service.build_authorization_url(
            redirect_uri=_build_google_callback_url(request),
            state=state,
        )
    except GoogleOAuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        ) from exc
    return RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)


@router.get("/google/callback", include_in_schema=False, name="google_auth_callback")
def google_auth_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    google_auth_service: Annotated[GoogleAuthService, Depends(get_google_auth_service)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    next_path = "/"

    if state:
        try:
            next_path = _normalize_next_path(auth_service.decode_oauth_state_token(state).next_path)
        except (TokenExpiredError, TokenValidationError):
            return _redirect_google_callback(next_path=next_path, error="invalid_google_state")

    if error:
        return _redirect_google_callback(next_path=next_path, error="google_sign_in_cancelled")

    if not code or not state:
        return _redirect_google_callback(next_path=next_path, error="missing_google_authorization_code")

    try:
        google_identity = google_auth_service.authenticate_authorization_code(
            code=code,
            redirect_uri=_build_google_callback_url(request),
        )
    except GoogleOAuthNotConfiguredError:
        return _redirect_google_callback(next_path=next_path, error="google_sign_in_not_configured")
    except GoogleOAuthError:
        logger.exception("Google sign-in failed during callback exchange")
        return _redirect_google_callback(next_path=next_path, error="google_sign_in_failed")

    email = normalize_email(google_identity.email)
    user = db.query(User).filter(User.email == email).first()

    if user is None:
        user = User(
            name=google_identity.name,
            email=email,
            username=build_unique_username(db, name=google_identity.name, email=email),
            password_hash=auth_service.hash_password(f"google-oauth::{google_identity.subject}"),
            role=UserRole.USER,
            is_active=True,
            is_verified=google_identity.email_verified,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return _redirect_google_callback(next_path=next_path, error="google_account_creation_failed")
    elif not user.is_active:
        return _redirect_google_callback(next_path=next_path, error="account_disabled")
    elif google_identity.email_verified and not user.is_verified:
        user.is_verified = True
        db.add(user)
        db.flush()

    try:
        _, refresh_token = _issue_token_pair(db=db, user=user, auth_service=auth_service)
    except IntegrityError:
        db.rollback()
        return _redirect_google_callback(next_path=next_path, error="google_sign_in_failed")

    session_code = auth_service.create_session_code(user)
    redirect_response = _redirect_google_callback(next_path=next_path, session_code=session_code)
    auth_service.set_refresh_cookie(redirect_response, refresh_token)
    return redirect_response


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    email_service: Annotated[EmailService, Depends(get_email_service)],
    rate_limit_service: Annotated[RateLimitService, Depends(get_rate_limit_service)],
) -> MessageResponse:
    email = normalize_email(payload.email)
    response_payload = MessageResponse(message="If an account exists, a reset link has been sent")

    enforce_identifier_rate_limit(
        rate_limit_service=rate_limit_service,
        identifier=email,
        endpoint="auth:forgot-password",
        max_requests=settings.FORGOT_PASSWORD_RATE_LIMIT_ATTEMPTS,
        window_seconds=settings.FORGOT_PASSWORD_RATE_LIMIT_WINDOW_SECONDS,
        message="Too many password reset requests. Please try again later.",
    )

    user = db.query(User).filter(User.email == email).first()
    if not user:
        return response_payload

    reset_token = auth_service.create_reset_token(user)
    user.reset_token = auth_service.hash_stored_token(reset_token)
    user.reset_token_expiry = _now() + timedelta(minutes=settings.JWT_RESET_TOKEN_EXPIRE_MINUTES)
    db.add(user)
    db.commit()

    try:
        email_service.send_password_reset_email(
            recipient=user.email,
            user_name=user.name,
            reset_token=reset_token,
        )
    except Exception:
        logger.exception("Password reset email delivery failed for user_id=%s", user.id)
        if settings.ENVIRONMENT == "production":
            user.reset_token = None
            user.reset_token_expiry = None
            db.add(user)
            db.commit()
        else:
            logger.warning(
                "Using development password reset fallback for user_id=%s reset_url=%s",
                user.id,
                email_service.build_password_reset_url(reset_token),
            )

    return response_payload


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    try:
        token_payload = auth_service.decode_reset_token(payload.token)
    except (TokenExpiredError, TokenValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token is invalid or expired",
        ) from exc

    user = db.query(User).filter(User.id == token_payload.user_id).first()
    if not user or not user.reset_token or not user.reset_token_expiry:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token is invalid or expired")

    expiry = user.reset_token_expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry < _now() or not verify_token_hash(payload.token, user.reset_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token is invalid or expired")

    user.password_hash = auth_service.hash_password(payload.new_password)
    user.reset_token = None
    user.reset_token_expiry = None
    user.refresh_token = None
    db.add(user)
    db.commit()

    auth_service.clear_refresh_cookie(response)
    return MessageResponse(message="Password reset successful")


@router.post("/refresh", response_model=RefreshTokenResponse)
def refresh_access_token(
    response: Response,
    payload: RefreshTokenRequest | None = Body(default=None),
    refresh_cookie: Annotated[str | None, Cookie(alias=settings.JWT_REFRESH_COOKIE_NAME)] = None,
    *,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> RefreshTokenResponse:
    refresh_token = (payload.refresh_token if payload else None) or refresh_cookie
    if not refresh_token:
        raise _invalid_refresh_credentials()

    try:
        token_payload = auth_service.decode_refresh_token(refresh_token)
    except (TokenExpiredError, TokenValidationError) as exc:
        raise _invalid_refresh_credentials() from exc

    user = db.query(User).filter(User.id == token_payload.user_id).first()
    if not user or not verify_token_hash(refresh_token, user.refresh_token):
        raise _invalid_refresh_credentials()

    access_token, rotated_refresh_token = _issue_token_pair(db=db, user=user, auth_service=auth_service)
    auth_service.set_refresh_cookie(response, rotated_refresh_token)
    return RefreshTokenResponse(access_token=access_token, refresh_token=rotated_refresh_token)


@router.post("/session-exchange", response_model=AuthResponse)
def session_exchange(
    payload: SessionCodeExchangeRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    try:
        token_payload = auth_service.decode_session_code(payload.session_code)
    except (TokenExpiredError, TokenValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session code is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.query(User).filter(User.id == token_payload.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session code is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, refresh_token = _issue_token_pair(db=db, user=user, auth_service=auth_service)
    auth_service.set_refresh_cookie(response, refresh_token)
    return _build_auth_response(user, access_token, refresh_token)


@router.post("/logout", response_model=MessageResponse)
def logout(
    response: Response,
    payload: RefreshTokenRequest | None = Body(default=None),
    refresh_cookie: Annotated[str | None, Cookie(alias=settings.JWT_REFRESH_COOKIE_NAME)] = None,
    *,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    db: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    target_user = current_user

    if target_user is None:
        refresh_token = (payload.refresh_token if payload else None) or refresh_cookie
        if refresh_token:
            try:
                token_payload = auth_service.decode_refresh_token(refresh_token)
            except (TokenExpiredError, TokenValidationError):
                token_payload = None
            if token_payload is not None:
                target_user = db.query(User).filter(User.id == token_payload.user_id).first()

    if target_user is not None:
        target_user.refresh_token = None
        db.add(target_user)
        db.commit()

    auth_service.clear_refresh_cookie(response)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=MeResponse)
def read_current_user(current_user: Annotated[User, Depends(get_current_active_user)]) -> MeResponse:
    auth_user = _build_auth_user_response(current_user)
    return MeResponse(
        id=auth_user.id,
        name=auth_user.name,
        email=auth_user.email,
        username=auth_user.username,
        role=auth_user.role,
        doctor_profile_id=auth_user.doctor_profile_id,
        created_at=current_user.created_at,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Annotated[Session, Depends(get_db)]) -> User:
    existing = db.query(User).filter((User.email == normalize_email(payload.email)) | (User.username == payload.username)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email or username already exists")

    user = User(
        name=payload.username,
        email=normalize_email(payload.email),
        username=payload.username,
        password_hash=get_auth_service().hash_password(payload.password),
        role=UserRole.USER,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login/access-token", response_model=Token)
def login_access_token(
    db: Annotated[Session, Depends(get_db)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    identifier = normalize_email(form_data.username)
    user = db.query(User).filter((User.username == form_data.username) | (User.email == identifier)).first()
    auth_service = get_auth_service()
    if not user or not auth_service.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect username/email or password")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token = auth_service.create_access_token(user)
    return Token(access_token=access_token, token_type="bearer")
