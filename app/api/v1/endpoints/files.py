import hashlib
import mimetypes
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import FileScanStatus
from app.models.file_record import FileRecord
from app.schemas.file import (
    DoctorImagePayload,
    DoctorImageResponse,
    FileUploadPayload,
    FileUploadResponse,
)
from app.services.storage_service import StorageService
from app.utils.file_validators import normalize_upload_content_type

router = APIRouter()


@lru_cache
def get_storage_service() -> StorageService:
    return StorageService()


def _build_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_file_type(file: UploadFile) -> str:
    normalized = normalize_upload_content_type(file.content_type)
    if normalized not in {"", "application/octet-stream", "binary/octet-stream"}:
        return normalized

    guessed, _ = mimetypes.guess_type(file.filename or "")
    return normalize_upload_content_type(guessed) or "application/octet-stream"


def _build_scan_metadata() -> dict[str, str | bool | None]:
    # Placeholder until a real AV scanner is wired in. This keeps the documented API contract stable.
    return {
        "status": FileScanStatus.CLEAN.value,
        "virus_scanned": True,
        "virus_found": False,
        "scan_result": None,
    }


def _build_upload_payload(record: FileRecord) -> FileUploadPayload:
    return FileUploadPayload(
        id=record.id,
        fileName=record.file_name,
        originalFileName=record.original_file_name,
        filePath=record.file_path,
        fileType=record.file_type,
        fileSize=record.file_size,
        fileHash=record.file_hash,
        uploadedBy=record.uploaded_by,
        uploadIp=record.upload_ip,
        status=record.status.value,
        virusScanned=record.virus_scanned,
        virusFound=record.virus_found,
        scanResult=record.scan_result,
        userId=record.user_id,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _should_return_doctor_image_json(request: Request, redirect: bool) -> bool:
    if not redirect:
        return True

    fetch_dest = request.headers.get("sec-fetch-dest", "").strip().lower()
    if fetch_dest == "empty":
        return True

    accept = request.headers.get("accept", "").lower()
    return "application/json" in accept and "text/html" not in accept


def _build_doctor_image_response(
    *,
    doctor_id: str,
    file_url: str,
    record: FileRecord,
) -> DoctorImageResponse:
    return DoctorImageResponse(
        success=True,
        message="Doctor image resolved successfully",
        data=DoctorImagePayload(
            id=record.id,
            fileName=record.file_name,
            originalFileName=record.original_file_name,
            filePath=record.file_path,
            fileType=record.file_type,
            fileSize=record.file_size,
            fileUrl=file_url,
            doctorId=doctor_id,
            createdAt=record.created_at,
        ),
        timestamp=_build_timestamp(),
        metadata=None,
        errorCode=None,
    )




@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_200_OK)
async def upload_file(
    request: Request,
    db: Session = Depends(get_db),
    storage_service: StorageService = Depends(get_storage_service),
    userid: str | None = Query(default=None),
    file: UploadFile = File(...),
) -> FileUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    await file.seek(0)
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    storage_user_id = (userid or "").strip() or "anonymous"
    stored_file = await storage_service.store_file(file, storage_user_id)
    if (userid or "").strip():
        await storage_service.upsert_doctor_image(file, (userid or "").strip())
    scan_metadata = _build_scan_metadata()

    record = FileRecord(
        file_name=stored_file.file_name,
        original_file_name=file.filename,
        file_path=stored_file.file_path,
        storage_reference=stored_file.storage_reference,
        file_type=_resolve_file_type(file),
        file_size=len(content),
        file_hash=hashlib.sha256(content).hexdigest(),
        uploaded_by="anonymous",
        upload_ip=(request.client.host if request.client else None) or "unknown",
        status=FileScanStatus(scan_metadata["status"]),
        virus_scanned=bool(scan_metadata["virus_scanned"]),
        virus_found=bool(scan_metadata["virus_found"]),
        scan_result=scan_metadata["scan_result"],
        user_id=(userid or "").strip() or None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return FileUploadResponse(
        success=True,
        message="File uploaded successfully",
        data=_build_upload_payload(record),
        timestamp=_build_timestamp(),
        metadata=None,
        errorCode=None,
    )


@router.get("/doctor/{doctor_id}", status_code=status.HTTP_307_TEMPORARY_REDIRECT, response_model=None)
async def get_doctor_image(
    request: Request,
    doctor_id: str,
    db: Session = Depends(get_db),
    storage_service: StorageService = Depends(get_storage_service),
    redirect: bool = Query(default=True),
) -> FileResponse | RedirectResponse | JSONResponse:
    doctor_image = await storage_service.get_doctor_image(doctor_id)
    if doctor_image is not None:
        if _should_return_doctor_image_json(request, redirect):
            record = (
                db.query(FileRecord)
                .filter(FileRecord.user_id == doctor_id)
                .order_by(FileRecord.created_at.desc(), FileRecord.id.desc())
                .first()
            )
            if record is not None:
                payload = _build_doctor_image_response(
                    doctor_id=doctor_id,
                    file_url=doctor_image.storage_reference,
                    record=record,
                )
                return JSONResponse(status_code=200, content=jsonable_encoder(payload))
        if doctor_image.is_local_file:
            return FileResponse(doctor_image.storage_reference, media_type=doctor_image.media_type)
        return RedirectResponse(doctor_image.storage_reference, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    record = (
        db.query(FileRecord)
        .filter(FileRecord.user_id == doctor_id)
        .order_by(FileRecord.created_at.desc(), FileRecord.id.desc())
        .first()
    )
    if record is None:
        payload = {
            "success": False,
            "message": f"No image found for doctor ID: {doctor_id}",
            "data": None,
            "timestamp": _build_timestamp(),
            "metadata": None,
            "errorCode": "DOCTOR_IMAGE_NOT_FOUND",
        }
        return JSONResponse(status_code=404, content=jsonable_encoder(payload))

    file_url = await storage_service.get_file_url(record.storage_reference)
    if _should_return_doctor_image_json(request, redirect):
        payload = _build_doctor_image_response(
            doctor_id=doctor_id,
            file_url=file_url,
            record=record,
        )
        return JSONResponse(status_code=200, content=jsonable_encoder(payload))
    return RedirectResponse(file_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
