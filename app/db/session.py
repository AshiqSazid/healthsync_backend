from pathlib import Path

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import logging

from app.core.config import settings


def _resolve_sqlite_database_uri(database_uri: str) -> str:
    sqlite_prefix = "sqlite:///"
    if not database_uri.startswith(sqlite_prefix):
        return database_uri

    database_path = database_uri[len(sqlite_prefix) :]
    if database_path in {"", ":memory:"}:
        return database_uri

    candidate = Path(database_path).expanduser()
    if not candidate.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        candidate = (backend_root / candidate).resolve()

    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        if not candidate.exists():
            candidate.touch(exist_ok=True)
            candidate.unlink(missing_ok=True)
        return f"sqlite:///{candidate}"
    except OSError:
        fallback_dir = Path("/tmp/healthsynch")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = fallback_dir / (candidate.name or "healthsynch.db")
        return f"sqlite:///{fallback_path}"


logger = logging.getLogger(__name__)

database_uri = _resolve_sqlite_database_uri(settings.SQLALCHEMY_DATABASE_URI)

engine_kwargs: dict = {"echo": settings.SQL_ECHO, "future": True, "pool_pre_ping": True}
if database_uri.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
elif database_uri.startswith("postgresql"):
    # Fail fast in serverless cold starts when DB connectivity is broken.
    engine_kwargs["connect_args"] = {"connect_timeout": 5}

try:
    engine = create_engine(database_uri, **engine_kwargs)
except Exception as exc:
    if settings.DB_EXPECTED_BACKEND == "postgresql" and not settings.DB_ALLOW_SQLITE_FALLBACK:
        raise RuntimeError(
            f"Database engine initialization failed for expected PostgreSQL backend: {database_uri}"
        ) from exc
    fallback_uri = "sqlite:////tmp/healthsynch/healthsynch.db"
    logger.exception(
        "Database engine initialization failed for '%s'. Falling back to '%s'. Error: %s",
        database_uri,
        fallback_uri,
        exc,
    )
    engine = create_engine(
        fallback_uri,
        echo=settings.SQL_ECHO,
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
