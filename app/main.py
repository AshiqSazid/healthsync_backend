import logging
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.ai.http_client import close_openai_http_client
from app.api.v1.api import api_router
from app.api.v1.endpoints import payments as payment_endpoints
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.db_runtime_service import probe_database_runtime, runtime_probe_to_dict


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.PROJECT_NAME)

# Serve doctor photos as static files from the data/ directory.
# Vercel serverless: static files are unreliable, so the /local/{id}/photo
# streaming endpoint in doctors.py is the primary photo delivery mechanism.
_DOCTOR_PHOTOS_DIR = Path(__file__).resolve().parents[1] / "data"
if _DOCTOR_PHOTOS_DIR.is_dir():
    app.mount(
        "/static/doctors",
        StaticFiles(directory=str(_DOCTOR_PHOTOS_DIR)),
        name="doctor_photos",
    )

payment_alias_router = APIRouter()
payment_alias_router.include_router(payment_endpoints.router, prefix="/payments", tags=["payments"])
payment_alias_router.include_router(payment_endpoints.admin_router, prefix="/admin/payments", tags=["admin-payments"])


def _normalize_legacy_user_email(email: str) -> str:
    value = str(email or "").strip().lower()
    if not value or "@" not in value:
        return value

    local_part, domain = value.split("@", 1)
    domain = domain.strip().lower()
    if domain.endswith(".local"):
        return f"{local_part}@legacy.healthsync.example.com"
    if domain.endswith(".external"):
        return f"{local_part}@providers.healthsync.example.com"
    return value


def _normalize_legacy_special_use_user_emails() -> None:
    db = SessionLocal()
    try:
        users = db.query(User).all()
        seen_emails: set[str] = set()
        dirty = False

        for user in users:
            normalized_email = _normalize_legacy_user_email(user.email)
            if not normalized_email:
                continue

            if normalized_email in seen_emails:
                local_part, domain = normalized_email.split("@", 1)
                suffix = user.id[:8] if user.id else "user"
                normalized_email = f"{local_part}+{suffix}@{domain}"

            seen_emails.add(normalized_email)

            if user.email != normalized_email:
                user.email = normalized_email
                db.add(user)
                dirty = True

        if dirty:
            db.commit()
            logger.info("Normalized legacy special-use user email domains to valid addresses")
    finally:
        db.close()


def _ensure_bootstrap_admin_user() -> None:
    if not settings.ADMIN_BOOTSTRAP_ENABLED:
        return

    username = settings.ADMIN_BOOTSTRAP_USERNAME.strip()
    password = settings.ADMIN_BOOTSTRAP_PASSWORD
    email = settings.ADMIN_BOOTSTRAP_EMAIL.strip()
    if not username or not password:
        logger.warning("ADMIN_BOOTSTRAP is enabled but username/password are empty; skipping admin bootstrap")
        return

    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.username == username).first()
        if admin_user is None:
            admin_user = User(
                name=settings.ADMIN_BOOTSTRAP_NAME,
                email=email,
                username=username,
                password_hash=AuthService.hash_password(password),
                role=UserRole.ADMIN,
                is_active=True,
                is_verified=True,
            )
            db.add(admin_user)
            db.commit()
            logger.info("Bootstrapped admin user '%s'", username)
            return

        dirty = False
        if admin_user.role != UserRole.ADMIN:
            admin_user.role = UserRole.ADMIN
            dirty = True
        if admin_user.email != email:
            admin_user.email = email
            dirty = True
        if not admin_user.is_active:
            admin_user.is_active = True
            dirty = True
        if not admin_user.is_verified:
            admin_user.is_verified = True
            dirty = True
        if settings.ADMIN_BOOTSTRAP_FORCE_PASSWORD_SYNC and not AuthService.verify_password(password, admin_user.password_hash):
            admin_user.password_hash = AuthService.hash_password(password)
            dirty = True

        if dirty:
            db.add(admin_user)
            db.commit()
            logger.info("Synchronized bootstrap admin user '%s'", username)
    finally:
        db.close()


def _run_startup_db_task(task_name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except SQLAlchemyError as exc:
        logger.warning("Startup task '%s' skipped due database error: %s", task_name, exc)
    except Exception:
        logger.exception("Startup task '%s' failed unexpectedly", task_name)


def _ensure_sqlite_development_schema() -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        if "assessment_documents" in table_names:
            normalized_rows = connection.execute(
                text(
                    """
                    UPDATE assessment_documents
                    SET status = lower(status)
                    WHERE status IN ('DRAFT', 'COMPLETED')
                    """
                )
            )
            if normalized_rows.rowcount:
                logger.info(
                    "Normalized %s SQLite assessment_documents.status values to lowercase",
                    normalized_rows.rowcount,
                )

        if "bookings" not in table_names:
            return

        booking_columns = {column["name"] for column in inspector.get_columns("bookings")}
        booking_indexes = {index["name"] for index in inspector.get_indexes("bookings")}
        column_statements = [
            ("linked_assessment_id", "ALTER TABLE bookings ADD COLUMN linked_assessment_id VARCHAR(36)"),
            ("provider_name", "ALTER TABLE bookings ADD COLUMN provider_name VARCHAR(255)"),
            ("provider_external_id", "ALTER TABLE bookings ADD COLUMN provider_external_id VARCHAR(120)"),
            ("location_name", "ALTER TABLE bookings ADD COLUMN location_name VARCHAR(255)"),
            ("location_address", "ALTER TABLE bookings ADD COLUMN location_address TEXT"),
            ("patient_name_snapshot", "ALTER TABLE bookings ADD COLUMN patient_name_snapshot VARCHAR(255)"),
            ("patient_phone_snapshot", "ALTER TABLE bookings ADD COLUMN patient_phone_snapshot VARCHAR(30)"),
            ("patient_sex_snapshot", "ALTER TABLE bookings ADD COLUMN patient_sex_snapshot VARCHAR(30)"),
        ]

        for column_name, statement in column_statements:
            if column_name not in booking_columns:
                connection.execute(text(statement))
                logger.info("Added missing SQLite development column bookings.%s", column_name)

        if "ix_bookings_linked_assessment_id" not in booking_indexes:
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_bookings_linked_assessment_id ON bookings (linked_assessment_id)")
            )
        if "ix_bookings_provider_external_id" not in booking_indexes:
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_bookings_provider_external_id ON bookings (provider_external_id)")
            )

        if "payments" in table_names:
            payment_columns = {column["name"] for column in inspector.get_columns("payments")}
            payment_indexes = {index["name"] for index in inspector.get_indexes("payments")}
            payment_column_statements = [
                ("user_id", "ALTER TABLE payments ADD COLUMN user_id VARCHAR(36)"),
                ("payable_amount", "ALTER TABLE payments ADD COLUMN payable_amount NUMERIC(10, 2)"),
                ("discount_amount", "ALTER TABLE payments ADD COLUMN discount_amount NUMERIC(10, 2)"),
                ("received_amount", "ALTER TABLE payments ADD COLUMN received_amount NUMERIC(10, 2)"),
                ("customer_order_id", "ALTER TABLE payments ADD COLUMN customer_order_id VARCHAR(120)"),
                ("gateway_transaction_id", "ALTER TABLE payments ADD COLUMN gateway_transaction_id VARCHAR(120)"),
                ("bank_transaction_id", "ALTER TABLE payments ADD COLUMN bank_transaction_id VARCHAR(120)"),
                ("checkout_url", "ALTER TABLE payments ADD COLUMN checkout_url TEXT"),
                ("payer_name", "ALTER TABLE payments ADD COLUMN payer_name VARCHAR(255)"),
                ("payer_phone", "ALTER TABLE payments ADD COLUMN payer_phone VARCHAR(30)"),
                ("payer_email", "ALTER TABLE payments ADD COLUMN payer_email VARCHAR(255)"),
                ("customer_address", "ALTER TABLE payments ADD COLUMN customer_address TEXT"),
                ("customer_city", "ALTER TABLE payments ADD COLUMN customer_city VARCHAR(120)"),
                ("service_type", "ALTER TABLE payments ADD COLUMN service_type VARCHAR(120)"),
                ("service_details", "ALTER TABLE payments ADD COLUMN service_details JSON"),
                ("bank_status", "ALTER TABLE payments ADD COLUMN bank_status VARCHAR(120)"),
                ("sp_code", "ALTER TABLE payments ADD COLUMN sp_code INTEGER"),
                ("sp_message", "ALTER TABLE payments ADD COLUMN sp_message TEXT"),
                ("status_message", "ALTER TABLE payments ADD COLUMN status_message TEXT"),
                ("raw_init_payload", "ALTER TABLE payments ADD COLUMN raw_init_payload JSON"),
                ("raw_init_response", "ALTER TABLE payments ADD COLUMN raw_init_response JSON"),
                ("raw_verify_response", "ALTER TABLE payments ADD COLUMN raw_verify_response JSON"),
                ("raw_ipn_payload", "ALTER TABLE payments ADD COLUMN raw_ipn_payload JSON"),
                ("transaction_date", "ALTER TABLE payments ADD COLUMN transaction_date DATETIME"),
                ("verified_at", "ALTER TABLE payments ADD COLUMN verified_at DATETIME"),
                ("updated_at", "ALTER TABLE payments ADD COLUMN updated_at DATETIME"),
            ]

            for column_name, statement in payment_column_statements:
                if column_name not in payment_columns:
                    connection.execute(text(statement))
                    logger.info("Added missing SQLite development column payments.%s", column_name)

            payment_columns = {column["name"] for column in inspect(connection).get_columns("payments")}

            if "ix_payments_user_id" not in payment_indexes:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments (user_id)"))
            if "ix_payments_customer_order_id" not in payment_indexes:
                connection.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_payments_customer_order_id ON payments (customer_order_id)")
                )
            if "ix_payments_gateway_transaction_id" not in payment_indexes:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_payments_gateway_transaction_id ON payments (gateway_transaction_id)"
                    )
                )
            if "ix_payments_bank_transaction_id" not in payment_indexes:
                connection.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_payments_bank_transaction_id ON payments (bank_transaction_id)")
                )
            if "ix_payments_transaction_date" not in payment_indexes:
                connection.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_payments_transaction_date ON payments (transaction_date)")
                )
            if "ix_payments_verified_at" not in payment_indexes:
                connection.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_payments_verified_at ON payments (verified_at)")
                )

            if "user_id" in payment_columns:
                connection.execute(
                    text(
                        """
                        UPDATE payments
                        SET user_id = (
                            SELECT bookings.user_id
                            FROM bookings
                            WHERE bookings.id = payments.booking_id
                        )
                        WHERE user_id IS NULL OR user_id = ''
                        """
                    )
                )
            if "updated_at" in payment_columns:
                connection.execute(text("UPDATE payments SET updated_at = COALESCE(updated_at, created_at)"))
            if "discount_amount" in payment_columns:
                connection.execute(text("UPDATE payments SET discount_amount = COALESCE(discount_amount, 0)"))
            if "payable_amount" in payment_columns:
                connection.execute(text("UPDATE payments SET payable_amount = COALESCE(payable_amount, amount)"))
            if "received_amount" in payment_columns:
                connection.execute(
                    text(
                        """
                        UPDATE payments
                        SET received_amount = COALESCE(received_amount, amount)
                        WHERE status = 'completed'
                        """
                    )
                )
            if "service_type" in payment_columns:
                connection.execute(
                    text("UPDATE payments SET service_type = COALESCE(NULLIF(service_type, ''), 'doctor_booking')")
                )
            if "verified_at" in payment_columns:
                connection.execute(
                    text(
                        """
                        UPDATE payments
                        SET verified_at = COALESCE(verified_at, paid_at, updated_at)
                        WHERE raw_verify_response IS NOT NULL
                        """
                    )
                )


def _ensure_postgres_payments_runtime_schema() -> None:
    if engine.url.get_backend_name() != "postgresql":
        return

    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        if "payments" not in table_names:
            return

        payment_columns = {column["name"] for column in inspector.get_columns("payments")}
        payment_indexes = {index["name"] for index in inspector.get_indexes("payments")}

        column_statements = [
            ("user_id", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"),
            ("payable_amount", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payable_amount NUMERIC(10, 2)"),
            ("discount_amount", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(10, 2)"),
            ("received_amount", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS received_amount NUMERIC(10, 2)"),
            ("customer_order_id", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS customer_order_id VARCHAR(120)"),
            ("gateway_transaction_id", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS gateway_transaction_id VARCHAR(120)"),
            ("bank_transaction_id", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS bank_transaction_id VARCHAR(120)"),
            ("checkout_url", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS checkout_url TEXT"),
            ("payer_name", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payer_name VARCHAR(255)"),
            ("payer_phone", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payer_phone VARCHAR(30)"),
            ("payer_email", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payer_email VARCHAR(255)"),
            ("customer_address", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS customer_address TEXT"),
            ("customer_city", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS customer_city VARCHAR(120)"),
            ("service_type", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS service_type VARCHAR(120)"),
            ("service_details", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS service_details JSON"),
            ("bank_status", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS bank_status VARCHAR(120)"),
            ("sp_code", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS sp_code INTEGER"),
            ("sp_message", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS sp_message TEXT"),
            ("status_message", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS status_message TEXT"),
            ("raw_init_payload", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS raw_init_payload JSON"),
            ("raw_init_response", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS raw_init_response JSON"),
            ("raw_verify_response", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS raw_verify_response JSON"),
            ("raw_ipn_payload", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS raw_ipn_payload JSON"),
            ("transaction_date", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS transaction_date TIMESTAMPTZ"),
            ("verified_at", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ"),
            ("updated_at", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"),
        ]

        for column_name, statement in column_statements:
            if column_name not in payment_columns:
                connection.execute(text(statement))
                logger.info("Added missing Postgres runtime column payments.%s", column_name)

        connection.execute(
            text(
                """
                UPDATE payments
                SET user_id = bookings.user_id
                FROM bookings
                WHERE bookings.id::text = payments.booking_id
                  AND (payments.user_id IS NULL OR payments.user_id = '')
                """
            )
        )

        if "ix_payments_user_id" not in payment_indexes:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments (user_id)"))
        if "ix_payments_customer_order_id" not in payment_indexes:
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_customer_order_id ON payments (customer_order_id)")
            )
        if "ix_payments_gateway_transaction_id" not in payment_indexes:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_gateway_transaction_id "
                    "ON payments (gateway_transaction_id)"
                )
            )
        if "ix_payments_bank_transaction_id" not in payment_indexes:
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_payments_bank_transaction_id ON payments (bank_transaction_id)")
            )
        if "ix_payments_transaction_date" not in payment_indexes:
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_payments_transaction_date ON payments (transaction_date)")
            )
        if "ix_payments_verified_at" not in payment_indexes:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_verified_at ON payments (verified_at)"))

        connection.execute(text("UPDATE payments SET updated_at = COALESCE(updated_at, created_at)"))
        connection.execute(text("UPDATE payments SET discount_amount = COALESCE(discount_amount, 0)"))
        connection.execute(text("UPDATE payments SET payable_amount = COALESCE(payable_amount, amount)"))
        connection.execute(
            text(
                """
                UPDATE payments
                SET received_amount = COALESCE(received_amount, amount)
                WHERE lower(status::text) = 'completed'
                """
            )
        )
        connection.execute(
            text("UPDATE payments SET service_type = COALESCE(NULLIF(service_type, ''), 'doctor_booking')")
        )
        connection.execute(
            text(
                """
                UPDATE payments
                SET verified_at = COALESCE(verified_at, paid_at, updated_at)
                WHERE raw_verify_response IS NOT NULL
                """
            )
        )


def _merged_cors_origin_regex() -> str | None:
    # Temporary override: allow every origin, including Vercel preview domains.
    return r".*"

CORS_ORIGIN_REGEX = _merged_cors_origin_regex()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    is_serverless_runtime = os.getenv("VERCEL") == "1"
    active_backend = engine.url.get_backend_name()

    if settings.DB_EXPECTED_BACKEND != "any" and active_backend != settings.DB_EXPECTED_BACKEND:
        raise RuntimeError(
            f"Database backend mismatch: expected '{settings.DB_EXPECTED_BACKEND}', got '{active_backend}'"
        )

    if active_backend == "sqlite":
        _run_startup_db_task("sqlite_schema_bootstrap", lambda: Base.metadata.create_all(bind=engine))
        _run_startup_db_task("sqlite_schema_patch", _ensure_sqlite_development_schema)
    if active_backend == "postgresql" and not is_serverless_runtime:
        _run_startup_db_task("postgres_payments_schema_patch", _ensure_postgres_payments_runtime_schema)

    # Avoid expensive DB-wide startup tasks on serverless cold starts.
    if not is_serverless_runtime:
        _run_startup_db_task("normalize_legacy_special_use_user_emails", _normalize_legacy_special_use_user_emails)
        _run_startup_db_task("ensure_bootstrap_admin_user", _ensure_bootstrap_admin_user)

    # Log AI configuration status
    if settings.OPENAI_API_KEY:
        logger.info("OpenAI API key loaded")
        logger.info(f"OpenAI API base: {settings.OPENAI_API_BASE}")
        logger.info(f"OpenAI text model: {settings.OPENAI_TEXT_MODEL}")
        logger.info(f"OpenAI vision model: {settings.OPENAI_VISION_MODEL}")
    else:
        logger.warning("OpenAI API key NOT configured - AI features will not work!")

    # Runtime DB identity probe (proves active backend + target database at startup).
    db = SessionLocal()
    try:
        probe = probe_database_runtime(db, backend=active_backend, engine_url=str(engine.url))
        logger.info("Runtime database probe: %s", runtime_probe_to_dict(probe))
    except Exception as exc:
        logger.warning("Runtime database probe failed: %s", exc)
    finally:
        db.close()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_openai_http_client()


@app.get("/", tags=["health"])
def root() -> dict[str, str]:
    return {
        "status": "ok",
        "name": settings.PROJECT_NAME,
        "api_base": settings.API_V1_STR,
        "health_url": "/health",
    }


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
def reset_password_page() -> HTMLResponse:
    login_url = f"{settings.FRONTEND_URL}/login"
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{settings.PROJECT_NAME} Reset Password</title>
    <style>
      :root {{
        color-scheme: light;
        font-family: Arial, sans-serif;
      }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #eef4ff;
        color: #10234a;
      }}
      .card {{
        width: min(92vw, 420px);
        background: #fff;
        border: 1px solid #d9e2f3;
        border-radius: 16px;
        box-shadow: 0 16px 40px rgba(10, 27, 66, 0.12);
        padding: 28px;
      }}
      h1 {{
        margin: 0 0 8px;
        font-size: 28px;
      }}
      p {{
        margin: 0 0 18px;
        line-height: 1.5;
        color: #455a85;
      }}
      label {{
        display: block;
        margin: 14px 0 6px;
        font-size: 14px;
        font-weight: 700;
      }}
      input {{
        width: 100%;
        box-sizing: border-box;
        border: 1px solid #c8d6ef;
        border-radius: 10px;
        padding: 12px 14px;
        font-size: 15px;
      }}
      button {{
        width: 100%;
        margin-top: 18px;
        border: 0;
        border-radius: 10px;
        padding: 12px 14px;
        font-size: 15px;
        font-weight: 700;
        cursor: pointer;
        background: #2563eb;
        color: #fff;
      }}
      button:disabled {{
        opacity: 0.7;
        cursor: not-allowed;
      }}
      .hint {{
        margin-top: 10px;
        font-size: 13px;
        color: #7a8fb8;
      }}
      .message {{
        margin-top: 14px;
        font-size: 14px;
      }}
      .message.error {{
        color: #c62828;
      }}
      .message.success {{
        color: #1f7a1f;
      }}
      .link {{
        display: inline-block;
        margin-top: 16px;
        color: #2563eb;
        text-decoration: none;
        font-weight: 700;
      }}
    </style>
  </head>
  <body>
    <main class="card">
      <h1>Reset Password</h1>
      <p>Enter a new password for your account.</p>
      <form id="reset-form">
        <label for="password">New Password</label>
        <input id="password" name="password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required />
        <label for="confirm-password">Confirm Password</label>
        <input id="confirm-password" name="confirm-password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required />
        <button id="submit-button" type="submit">Reset Password</button>
        <div class="hint">Password must be at least 8 characters and include 1 uppercase letter and 1 number.</div>
        <div id="message" class="message" aria-live="polite"></div>
      </form>
      <a class="link" href="{login_url}">Back to login</a>
    </main>
    <script>
      const form = document.getElementById("reset-form");
      const message = document.getElementById("message");
      const submitButton = document.getElementById("submit-button");
      const token = new URLSearchParams(window.location.search).get("token");
      const passwordComplexityPattern = /^(?=.*[A-Z])(?=.*\\d).{{8,128}}$/;
      const passwordRequirementsMessage = "Password must be at least 8 characters and include 1 uppercase letter and 1 number.";

      const showMessage = (text, type) => {{
        message.textContent = text;
        message.className = `message ${{type}}`;
      }};

      const formatErrorDetail = (detail) => {{
        if (!detail) {{
          return "Unable to reset password.";
        }}

        if (typeof detail === "string") {{
          return detail;
        }}

        if (Array.isArray(detail)) {{
          return detail
            .map((item) => {{
              if (!item || typeof item !== "object") {{
                return String(item);
              }}

              const location = Array.isArray(item.loc)
                ? item.loc.filter((part) => part !== "body").join(".")
                : "";
              const prefix = location ? `${{location}}: ` : "";
              return `${{prefix}}${{item.msg || "Invalid input"}}`;
            }})
            .join(" ");
        }}

        if (typeof detail === "object" && detail.message) {{
          return String(detail.message);
        }}

        return "Unable to reset password.";
      }};

      if (!token) {{
        showMessage("Reset token is missing.", "error");
        submitButton.disabled = true;
      }}

      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        if (!token) return;

        const password = document.getElementById("password").value;
        const confirmPassword = document.getElementById("confirm-password").value;

        if (password !== confirmPassword) {{
          showMessage("Passwords do not match.", "error");
          return;
        }}

        if (!passwordComplexityPattern.test(password)) {{
          showMessage(passwordRequirementsMessage, "error");
          return;
        }}

        submitButton.disabled = true;
        showMessage("", "");

        try {{
          const response = await fetch("{settings.API_V1_STR}/auth/reset-password", {{
            method: "POST",
            headers: {{
              "Content-Type": "application/json"
            }},
            credentials: "include",
            body: JSON.stringify({{
              token,
              new_password: password
            }})
          }});

          const payload = await response.json().catch(() => ({{ detail: "Unable to reset password." }}));
          if (!response.ok) {{
            throw new Error(payload.message || formatErrorDetail(payload.detail));
          }}

          showMessage(payload.message || "Password reset successful.", "success");
          form.reset();
        }} catch (error) {{
          showMessage(error.message || "Unable to reset password.", "error");
        }} finally {{
          submitButton.disabled = false;
        }}
      }});
    </script>
  </body>
</html>"""
    return HTMLResponse(content=html)


def _is_allowed_origin(origin: str) -> bool:
    if origin in settings.BACKEND_CORS_ORIGINS:
        return True
    if CORS_ORIGIN_REGEX:
        try:
            return re.match(CORS_ORIGIN_REGEX, origin) is not None
        except re.error:
            return False
    return False


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception at %s %s", request.method, request.url.path)
    response = JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
    origin = request.headers.get("origin")
    if origin and _is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(payment_alias_router, prefix="/api")
