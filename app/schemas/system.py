from datetime import datetime

from app.schemas.common import ORMModel


class DatabaseRuntimeStatusResponse(ORMModel):
    db_backend: str
    db_name: str | None = None
    db_user: str | None = None
    db_host: str | None = None
    db_schema_version: str | None = None
    db_verified_at: datetime
