from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from pydantic_settings import NoDecode
except ImportError:
    NoDecode = None

FallbackModelsType = Annotated[list[str], NoDecode] if NoDecode is not None else list[str]
CorsOriginsType = Annotated[list[str], NoDecode] if NoDecode is not None else list[str]

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
LOCAL_ENV_FILE = Path(__file__).resolve().parents[2] / ".env.local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ENV_FILE), str(LOCAL_ENV_FILE)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "HealthSynch"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_PUBLIC_URL: str | None = None
    PUBLIC_DOCTOR_API_BASE_URL: str = "https://apihealthsync.vercel.app"
    PUBLIC_DOCTOR_API_PATH: str = "/api/doctors"
    PUBLIC_DOCTOR_API_TIMEOUT_SECONDS: float = 15.0
    PUBLIC_DOCTOR_API_CACHE_TTL_SECONDS: float = 300.0
    PUBLIC_DOCTOR_API_PAGE_SIZE: int = 100
    PUBLIC_DOCTOR_API_MAX_PAGES: int = 10
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_NAME: str = "HealthSynch"
    REQUIRE_REMOTE_STORAGE_IN_PRODUCTION: bool = True
    BACKEND_CORS_ORIGINS: CorsOriginsType = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://myhealthsynch.com",
        "https://apihealthsync.vercel.app",
        "https://ml.api.myhealthsynch.com",
        "https://hfrontend.vercel.app",
    ]
    BACKEND_CORS_ORIGIN_REGEX: str | None = r"^https://([a-zA-Z0-9-]+\.)?myhealthsynch\.com$"
    BACKEND_CORS_ADDITIONAL_ORIGIN_REGEX: str | None = (
        r"^https://hfrontend(?:-[a-zA-Z0-9-]+)?\.vercel\.app$"
    )
    SECRET_KEY: str = "change-me"
    JWT_SECRET: str = "change-me-jwt-secret"
    JWT_REFRESH_SECRET: str = "change-me-jwt-refresh-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_RESET_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_COOKIE_NAME: str = "refresh_token"
    JWT_REFRESH_COOKIE_DOMAIN: str | None = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    DATABASE_URL: str | None = None
    DATABASE_URL_UNPOOLED: str | None = None
    SQLALCHEMY_DATABASE_URI: str | None = None
    LOCAL_DB_MODE: Literal["neon", "sqlite"] = "neon"
    DB_EXPECTED_BACKEND: Literal["postgresql", "sqlite", "any"] = "postgresql"
    DB_ALLOW_SQLITE_FALLBACK: bool = False
    SQL_ECHO: bool = False

    STORAGE_BACKEND: Literal["local", "s3", "minio", "cloudinary"] = "local"
    VERIFY_REMOTE_UPLOAD: bool = True
    UPLOAD_DIR: str = "./uploads"
    DELETE_PUBLIC_PREVIEW_UPLOADS: bool = False
    MAX_UPLOAD_MB: int = 4
    ALLOWED_UPLOAD_EXTENSIONS: list[str] = [
        ".jpg",
        ".jpeg",
        ".jpe",
        ".jfif",
        ".png",
        ".webp",
        ".bmp",
        ".gif",
        ".tif",
        ".tiff",
        ".heic",
        ".heif",
        ".avif",
        ".pdf",
    ]

    OPENAI_API_KEY: str | None = None
    OPENAI_API_BASE: str = "https://api.openai.com/v1"
    OPENAI_TEXT_MODEL: str = "gpt-4o-mini"
    OPENAI_TEXT_FALLBACK_MODELS: FallbackModelsType = ["gpt-4o-mini", "gpt-4o-mini-mini"]
    OPENAI_VISION_MODEL: str = "gpt-4o-mini"
    OPENAI_VISION_FALLBACK_MODELS: FallbackModelsType = ["gpt-4o"]
    OPENAI_MAX_CONCURRENT_REQUESTS: int = 5
    OPENAI_VISION_MAX_TOKENS: int = 3200
    OPENAI_VISION_PROMPT_VERSION: str = "v2"
    DOCUMENT_ANALYSIS_CACHE_TTL_DAYS: int = 30
    VISION_PDF_MAX_PAGES: int = 5
    VISION_PDF_RENDER_DPI: int = 180
    VISION_IMAGE_MAX_SIDE: int = 1024
    VISION_IMAGE_DETAIL: Literal["low", "high", "auto"] = "auto"
    VISION_IMAGE_OUTPUT_FORMAT: Literal["jpeg", "png"] = "jpeg"
    VISION_IMAGE_JPEG_QUALITY: int = 85
    GOOGLE_VISION_API_KEY: str | None = None
    GOOGLE_OAUTH_CLIENT_ID: str | None = None
    GOOGLE_OAUTH_CLIENT_SECRET: str | None = None
    GOOGLE_OAUTH_STATE_EXPIRE_MINUTES: int = 10

    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str | None = None
    S3_ENDPOINT_URL: str | None = None

    # Cloudinary Settings
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None
    CLOUDINARY_UPLOAD_FOLDER: str = "healthsynch"
    CLOUDINARY_FETCH_URL: bool = True

    # Redis Settings (for rate limiting)
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = False

    # Rate Limiting Settings
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_FREE_TIER_REQUESTS: int = 2
    RATE_LIMIT_WINDOW_SECONDS: int = 86400  # 24 hours
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900
    FORGOT_PASSWORD_RATE_LIMIT_ATTEMPTS: int = 3
    FORGOT_PASSWORD_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    ADMIN_BOOTSTRAP_ENABLED: bool = True
    ADMIN_BOOTSTRAP_NAME: str = "HealthSynch Admin"
    ADMIN_BOOTSTRAP_EMAIL: str = "healthsynch_admin007@example.com"
    ADMIN_BOOTSTRAP_USERNAME: str = "healthsynch_admin007"
    ADMIN_BOOTSTRAP_PASSWORD: str = ")(*&Hs0191."
    ADMIN_BOOTSTRAP_FORCE_PASSWORD_SYNC: bool = False
    SHURJOPAY_API_ROOT: str | None = None
    SHURJOPAY_API_URL: str = "https://engine.shurjopayment.com"
    SHURJOPAY_BASE_URL: str | None = None
    SHURJOPAY_USERNAME: str | None = None
    SHURJOPAY_PASSWORD: str | None = None
    SHURJOPAY_ORDER_PREFIX: str = "HES"
    SHURJOPAY_PREFIX: str | None = None
    SHURJOPAY_RETURN_URL: str | None = None
    SHURJOPAY_CANCEL_URL: str | None = None
    SHURJOPAY_DEFAULT_CURRENCY: str = "BDT"
    SHURJOPAY_DEFAULT_CITY: str = "Dhaka"
    SHURJOPAY_DEFAULT_POST_CODE: str = "1207"

    @field_validator("*", mode="before")
    @classmethod
    def strip_string_settings(cls, v: object) -> object:
        return cls._strip_env_string(v)

    @staticmethod
    def _strip_env_string(value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            # Some managed env providers inject escaped newlines as trailing "\n".
            cleaned = cleaned.replace("\\r", "").replace("\\n", "")
            return cleaned.strip()
        return value

    @staticmethod
    def _parse_boolish(value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
        return value

    @field_validator("ENVIRONMENT", "STORAGE_BACKEND", mode="before")
    @classmethod
    def parse_literal_settings(cls, v: object) -> object:
        return cls._strip_env_string(v)

    @field_validator("VISION_IMAGE_DETAIL", "VISION_IMAGE_OUTPUT_FORMAT", mode="before")
    @classmethod
    def parse_vision_literal_settings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator(
        "REQUIRE_REMOTE_STORAGE_IN_PRODUCTION",
        "VERIFY_REMOTE_UPLOAD",
        "DELETE_PUBLIC_PREVIEW_UPLOADS",
        "REDIS_ENABLED",
        "RATE_LIMIT_ENABLED",
        "CLOUDINARY_FETCH_URL",
        "ADMIN_BOOTSTRAP_ENABLED",
        "ADMIN_BOOTSTRAP_FORCE_PASSWORD_SYNC",
        "DB_ALLOW_SQLITE_FALLBACK",
        mode="before",
    )
    @classmethod
    def parse_bool_settings(cls, v: object) -> object:
        return cls._parse_boolish(v)

    @field_validator("ALLOWED_UPLOAD_EXTENSIONS", mode="before")
    @classmethod
    def parse_upload_extensions(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [part.strip().lower() for part in v.split(",") if part.strip()]
        return [part.lower() for part in v]

    @field_validator("OPENAI_TEXT_FALLBACK_MODELS", "OPENAI_VISION_FALLBACK_MODELS", mode="before")
    @classmethod
    def parse_openai_fallback_models(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            cleaned = v.strip()
            if cleaned.startswith("[") and cleaned.endswith("]"):
                cleaned = cleaned[1:-1]
            return [part.strip().strip("\"'") for part in cleaned.split(",") if part.strip()]
        return [str(part).strip() for part in v if str(part).strip()]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            cleaned = v.strip()
            if cleaned.startswith("[") and cleaned.endswith("]"):
                cleaned = cleaned[1:-1]
            return [part.strip().strip("\"'") for part in cleaned.split(",") if part.strip()]
        return [part.strip() for part in v if str(part).strip()]

    @field_validator("BACKEND_CORS_ORIGIN_REGEX", mode="before")
    @classmethod
    def parse_cors_origin_regex(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = str(v).strip()
        return cleaned or None

    @field_validator("BACKEND_CORS_ADDITIONAL_ORIGIN_REGEX", mode="before")
    @classmethod
    def parse_additional_cors_origin_regex(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = str(v).strip()
        return cleaned or None

    @model_validator(mode="after")
    def apply_derived_settings(self) -> "Settings":
        self.DATABASE_URL = self._normalize_postgres_scheme(self.DATABASE_URL)
        self.DATABASE_URL_UNPOOLED = self._normalize_postgres_scheme(self.DATABASE_URL_UNPOOLED)
        self.SQLALCHEMY_DATABASE_URI = self._normalize_postgres_scheme(self.SQLALCHEMY_DATABASE_URI)

        default_neon_pooled = (
            "postgresql://neondb_owner:npg_AkpiGy2QCzX4@ep-square-butterfly-amy3rqym-pooler.c-5.us-east-1.aws.neon.tech/"
            "neondb?channel_binding=require&sslmode=require"
        )
        default_neon_unpooled = (
            "postgresql://neondb_owner:npg_AkpiGy2QCzX4@ep-square-butterfly-amy3rqym.c-5.us-east-1.aws.neon.tech/"
            "neondb?sslmode=require"
        )

        if not self.DATABASE_URL or self._looks_like_placeholder_database_url(self.DATABASE_URL):
            self.DATABASE_URL = default_neon_pooled
        if not self.DATABASE_URL_UNPOOLED or self._looks_like_placeholder_database_url(self.DATABASE_URL_UNPOOLED):
            self.DATABASE_URL_UNPOOLED = default_neon_unpooled

        if not self.SQLALCHEMY_DATABASE_URI:
            self.SQLALCHEMY_DATABASE_URI = self.DATABASE_URL or "sqlite:///./healthsynch.db"
        elif self.LOCAL_DB_MODE == "neon" and self._is_default_sqlite_uri(self.SQLALCHEMY_DATABASE_URI):
            self.SQLALCHEMY_DATABASE_URI = self.DATABASE_URL
        elif self.LOCAL_DB_MODE == "sqlite" and not self._is_default_sqlite_uri(self.SQLALCHEMY_DATABASE_URI):
            self.SQLALCHEMY_DATABASE_URI = "sqlite:///./healthsynch.db"

        if self.LOCAL_DB_MODE == "sqlite":
            self.DB_EXPECTED_BACKEND = "sqlite"
        elif self.DB_EXPECTED_BACKEND == "any":
            self.DB_EXPECTED_BACKEND = "postgresql"

        self.FRONTEND_URL = self.FRONTEND_URL.rstrip("/")
        if self.BACKEND_PUBLIC_URL:
            self.BACKEND_PUBLIC_URL = self.BACKEND_PUBLIC_URL.rstrip("/")
        normalized_api_url = str(self.SHURJOPAY_API_URL or "https://engine.shurjopayment.com").rstrip("/")
        normalized_base_url = str(self.SHURJOPAY_BASE_URL or "").strip().rstrip("/")
        normalized_api_root = str(self.SHURJOPAY_API_ROOT or "").strip().rstrip("/")
        if normalized_base_url:
            normalized_api_root = normalized_base_url
        if normalized_api_root:
            self.SHURJOPAY_API_ROOT = normalized_api_root
        else:
            self.SHURJOPAY_API_ROOT = (
                normalized_api_url
                if normalized_api_url.endswith("/api")
                else f"{normalized_api_url}/api"
            )
        self.SHURJOPAY_BASE_URL = self.SHURJOPAY_API_ROOT
        self.SHURJOPAY_API_URL = normalized_api_url
        self.SHURJOPAY_PREFIX = (self.SHURJOPAY_PREFIX or self.SHURJOPAY_ORDER_PREFIX or "HES").strip() or "HES"
        self.SHURJOPAY_ORDER_PREFIX = self.SHURJOPAY_PREFIX
        if self.SHURJOPAY_RETURN_URL:
            self.SHURJOPAY_RETURN_URL = self.SHURJOPAY_RETURN_URL.rstrip("/")
        if self.SHURJOPAY_CANCEL_URL:
            self.SHURJOPAY_CANCEL_URL = self.SHURJOPAY_CANCEL_URL.rstrip("/")
        self.SHURJOPAY_DEFAULT_CURRENCY = (
            str(self.SHURJOPAY_DEFAULT_CURRENCY or "BDT").strip().upper() or "BDT"
        )
        self.SHURJOPAY_DEFAULT_CITY = str(self.SHURJOPAY_DEFAULT_CITY or "Dhaka").strip() or "Dhaka"
        self.SHURJOPAY_DEFAULT_POST_CODE = (
            str(self.SHURJOPAY_DEFAULT_POST_CODE or "1207").strip() or "1207"
        )
        self.PUBLIC_DOCTOR_API_BASE_URL = self.PUBLIC_DOCTOR_API_BASE_URL.rstrip("/")
        self.PUBLIC_DOCTOR_API_PATH = (
            self.PUBLIC_DOCTOR_API_PATH
            if self.PUBLIC_DOCTOR_API_PATH.startswith("/")
            else f"/{self.PUBLIC_DOCTOR_API_PATH}"
        )
        self.VISION_IMAGE_MAX_SIDE = max(512, min(int(self.VISION_IMAGE_MAX_SIDE or 1024), 2048))
        self.VISION_PDF_MAX_PAGES = max(1, min(int(self.VISION_PDF_MAX_PAGES or 5), 10))
        self.VISION_PDF_RENDER_DPI = max(100, min(int(self.VISION_PDF_RENDER_DPI or 180), 300))
        self.VISION_IMAGE_JPEG_QUALITY = max(40, min(int(self.VISION_IMAGE_JPEG_QUALITY or 85), 95))
        self.OPENAI_VISION_MAX_TOKENS = max(800, min(int(self.OPENAI_VISION_MAX_TOKENS or 3200), 8192))
        self.OPENAI_MAX_CONCURRENT_REQUESTS = max(1, min(int(self.OPENAI_MAX_CONCURRENT_REQUESTS or 5), 100))
        self.DOCUMENT_ANALYSIS_CACHE_TTL_DAYS = max(1, min(int(self.DOCUMENT_ANALYSIS_CACHE_TTL_DAYS or 30), 365))

        if self.ENVIRONMENT == "production":
            merged_origins = {
                str(origin).strip().rstrip("/")
                for origin in (self.BACKEND_CORS_ORIGINS or [])
                if str(origin).strip()
            }
            if self.FRONTEND_URL:
                merged_origins.add(self.FRONTEND_URL.rstrip("/"))
            if self.BACKEND_PUBLIC_URL:
                merged_origins.add(self.BACKEND_PUBLIC_URL.rstrip("/"))
            merged_origins.add("https://myhealthsynch.com")

            self.BACKEND_CORS_ORIGINS = sorted(merged_origins)
            if not self.BACKEND_CORS_ORIGIN_REGEX:
                self.BACKEND_CORS_ORIGIN_REGEX = r"^https://([a-zA-Z0-9-]+\.)?myhealthsynch\.com$"
            if not self.BACKEND_CORS_ADDITIONAL_ORIGIN_REGEX:
                self.BACKEND_CORS_ADDITIONAL_ORIGIN_REGEX = (
                    r"^https://hfrontend(?:-[a-zA-Z0-9-]+)?\.vercel\.app$"
                )

        return self

    @staticmethod
    def _normalize_postgres_scheme(value: str | None) -> str | None:
        if not value:
            return value
        cleaned = str(value).strip()
        if cleaned.startswith("postgres://"):
            return "postgresql://" + cleaned[len("postgres://") :]
        return cleaned

    @staticmethod
    def _is_default_sqlite_uri(value: str | None) -> bool:
        return str(value or "").strip() == "sqlite:///./healthsynch.db"

    @staticmethod
    def _looks_like_placeholder_database_url(value: str | None) -> bool:
        text = str(value or "").strip().lower()
        if not text:
            return True
        return any(token in text for token in ("username:password", "ep-xxxxx", "region.aws.neon.tech"))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
