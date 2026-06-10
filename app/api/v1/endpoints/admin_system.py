from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import engine, get_db
from app.models.enums import UserRole
from app.schemas.system import DatabaseRuntimeStatusResponse
from app.services.db_runtime_service import probe_database_runtime

router = APIRouter()


@router.get("/db-runtime", response_model=DatabaseRuntimeStatusResponse)
def get_db_runtime_status(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[object, Depends(require_roles(UserRole.ADMIN))],
) -> DatabaseRuntimeStatusResponse:
    probe = probe_database_runtime(
        db,
        backend=engine.url.get_backend_name(),
        engine_url=str(engine.url),
    )
    return DatabaseRuntimeStatusResponse(
        db_backend=probe.db_backend,
        db_name=probe.db_name,
        db_user=probe.db_user,
        db_host=probe.db_host,
        db_schema_version=probe.db_schema_version,
        db_verified_at=probe.db_verified_at,
    )
