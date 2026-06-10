from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt
from jwt import InvalidTokenError, PyJWKClient

from app.core.config import settings
from app.utils.helpers import normalize_email


class GoogleOAuthError(Exception):
    pass


class GoogleOAuthNotConfiguredError(GoogleOAuthError):
    pass


class GoogleOAuthTokenExchangeError(GoogleOAuthError):
    pass


class GoogleOAuthValidationError(GoogleOAuthError):
    pass


@dataclass(frozen=True)
class GoogleUserIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None


@lru_cache(maxsize=1)
def _get_google_jwk_client() -> PyJWKClient:
    return PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")


class GoogleAuthService:
    AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    ISSUERS = ("https://accounts.google.com", "accounts.google.com")

    def ensure_configured(self) -> None:
        if settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET:
            return
        raise GoogleOAuthNotConfiguredError("Google sign-in is not configured")

    def build_authorization_url(self, *, redirect_uri: str, state: str) -> str:
        self.ensure_configured()
        query = urlencode(
            {
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "select_account",
                "state": state,
            }
        )
        return f"{self.AUTHORIZATION_ENDPOINT}?{query}"

    def authenticate_authorization_code(self, *, code: str, redirect_uri: str) -> GoogleUserIdentity:
        tokens = self._exchange_authorization_code(code=code, redirect_uri=redirect_uri)
        id_token = str(tokens.get("id_token") or "").strip()
        if not id_token:
            raise GoogleOAuthTokenExchangeError("Google did not return an ID token")
        return self.verify_id_token(id_token)

    def _exchange_authorization_code(self, *, code: str, redirect_uri: str) -> dict[str, object]:
        self.ensure_configured()
        try:
            response = httpx.post(
                self.TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
                timeout=10.0,
            )
        except httpx.RequestError as exc:
            raise GoogleOAuthTokenExchangeError("Unable to reach Google token endpoint") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleOAuthTokenExchangeError("Google token endpoint returned an invalid response") from exc

        if response.status_code >= 400:
            if isinstance(payload, dict):
                detail = payload.get("error_description") or payload.get("error")
            else:
                detail = None
            raise GoogleOAuthTokenExchangeError(str(detail or "Google token exchange failed"))

        if not isinstance(payload, dict):
            raise GoogleOAuthTokenExchangeError("Google token endpoint returned an invalid payload")

        return payload

    def verify_id_token(self, id_token: str) -> GoogleUserIdentity:
        self.ensure_configured()
        try:
            signing_key = _get_google_jwk_client().get_signing_key_from_jwt(id_token)
            payload = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.GOOGLE_OAUTH_CLIENT_ID,
                issuer=self.ISSUERS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except InvalidTokenError as exc:
            raise GoogleOAuthValidationError("Google identity token is invalid") from exc
        except Exception as exc:
            raise GoogleOAuthValidationError("Unable to verify Google identity token") from exc

        email = normalize_email(str(payload.get("email") or ""))
        if not email:
            raise GoogleOAuthValidationError("Google account email is unavailable")

        email_verified = bool(payload.get("email_verified"))
        if not email_verified:
            raise GoogleOAuthValidationError("Google account email is not verified")

        name = str(payload.get("name") or payload.get("given_name") or email.split("@", 1)[0]).strip()
        if not name:
            name = email.split("@", 1)[0]

        subject = str(payload.get("sub") or "").strip()
        if not subject:
            raise GoogleOAuthValidationError("Google account subject is unavailable")

        return GoogleUserIdentity(
            subject=subject,
            email=email,
            email_verified=email_verified,
            name=name,
            given_name=str(payload.get("given_name")).strip() if payload.get("given_name") else None,
            family_name=str(payload.get("family_name")).strip() if payload.get("family_name") else None,
            picture=str(payload.get("picture")).strip() if payload.get("picture") else None,
        )


@lru_cache
def get_google_auth_service() -> GoogleAuthService:
    return GoogleAuthService()
