from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


@dataclass
class DatabaseRuntimeProbe:
    db_backend: str
    db_name: str | None
    db_user: str | None
    db_host: str | None
    db_schema_version: str | None
    db_verified_at: datetime


def _extract_host_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return None
    if len(hostname) <= 14:
        return hostname
    return f"{hostname[:6]}...{hostname[-6:]}"


def probe_database_runtime(db: Session, *, backend: str, engine_url: str) -> DatabaseRuntimeProbe:
    verified_at = datetime.now(timezone.utc)
    schema_version = None
    db_name = None
    db_user = None

    if backend == "postgresql":
        db_name = db.execute(text("select current_database()")).scalar()
        db_user = db.execute(text("select current_user")).scalar()
        try:
            schema_version = db.execute(text("select version_num from alembic_version limit 1")).scalar()
        except SQLAlchemyError:
            schema_version = None
    elif backend == "sqlite":
        db_name = db.execute(text("PRAGMA database_list")).fetchone()[1]
        try:
            schema_version = db.execute(text("select version_num from alembic_version limit 1")).scalar()
        except SQLAlchemyError:
            schema_version = None

    return DatabaseRuntimeProbe(
        db_backend=backend,
        db_name=str(db_name) if db_name is not None else None,
        db_user=str(db_user) if db_user is not None else None,
        db_host=_extract_host_from_url(engine_url),
        db_schema_version=str(schema_version) if schema_version is not None else None,
        db_verified_at=verified_at,
    )


def runtime_probe_to_dict(probe: DatabaseRuntimeProbe) -> dict[str, Any]:
    return {
        "db_backend": probe.db_backend,
        "db_name": probe.db_name,
        "db_user": probe.db_user,
        "db_host": probe.db_host,
        "db_schema_version": probe.db_schema_version,
        "db_verified_at": probe.db_verified_at.isoformat(),
    }
