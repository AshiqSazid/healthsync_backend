from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models.enums import UploadFileType
from app.models.upload import Upload
from app.models.user import User
from app.schemas.upload import UploadDetailResponse, UploadListResponse, UploadResponse
from app.services.cloudinary_service import (
    CloudinaryService,
    CloudinaryServiceError,
    get_cloudinary_service,
)
from app.utils.file_validators import validate_medical_upload

router = APIRouter()


def _build_upload_response(upload: Upload) -> UploadResponse:
    return UploadResponse(
        id=upload.id,
        file_type=upload.file_type,
        url=upload.cloudinary_url,
        secure_url=upload.cloudinary_secure_url,
        folder_path=upload.folder_path,
        uploaded_at=upload.uploaded_at,
    )


def _build_upload_detail_response(upload: Upload) -> UploadDetailResponse:
    return UploadDetailResponse(
        id=upload.id,
        file_type=upload.file_type,
        url=upload.cloudinary_url,
        secure_url=upload.cloudinary_secure_url,
        folder_path=upload.folder_path,
        uploaded_at=upload.uploaded_at,
        original_filename=upload.original_filename,
        file_size=upload.file_size,
        mime_type=upload.mime_type,
    )


def _persist_upload(
    *,
    db: Session,
    current_user: User,
    cloudinary_service: CloudinaryService,
    validated_file,
    file_type: UploadFileType,
) -> Upload:
    try:
        upload_result = cloudinary_service.upload_user_file(
            validated_file=validated_file,
            user_email=current_user.email,
            file_type=file_type,
        )
    except CloudinaryServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File upload failed. Please try again later.",
        ) from exc

    upload = Upload(
        user_id=current_user.id,
        file_type=file_type,
        cloudinary_public_id=upload_result.public_id,
        cloudinary_url=upload_result.url,
        cloudinary_secure_url=upload_result.secure_url,
        original_filename=validated_file.filename,
        file_size=validated_file.size,
        mime_type=validated_file.mime_type,
        folder_path=upload_result.folder_path,
        uploaded_at=upload_result.uploaded_at,
    )
    db.add(upload)
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            cloudinary_service.delete_file(public_id=upload_result.public_id, mime_type=validated_file.mime_type)
        except CloudinaryServiceError:
            pass
        raise
    db.refresh(upload)
    return upload


@router.post("/prescription", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_prescription(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    cloudinary_service: Annotated[CloudinaryService, Depends(get_cloudinary_service)],
    file: UploadFile = File(...),
) -> UploadResponse:
    validated_file = await validate_medical_upload(file)
    upload = _persist_upload(
        db=db,
        current_user=current_user,
        cloudinary_service=cloudinary_service,
        validated_file=validated_file,
        file_type=UploadFileType.PRESCRIPTION,
    )
    return _build_upload_response(upload)


@router.post("/report", response_model=list[UploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_reports(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    cloudinary_service: Annotated[CloudinaryService, Depends(get_cloudinary_service)],
    files: list[UploadFile] = File(...),
) -> list[UploadResponse]:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one file is required")

    validated_files = [await validate_medical_upload(file) for file in files]
    uploads: list[Upload] = []
    uploaded_assets: list[tuple[str, str]] = []

    try:
        for validated_file in validated_files:
            upload_result = cloudinary_service.upload_user_file(
                validated_file=validated_file,
                user_email=current_user.email,
                file_type=UploadFileType.REPORT,
            )
            uploaded_assets.append((upload_result.public_id, validated_file.mime_type))
            upload = Upload(
                user_id=current_user.id,
                file_type=UploadFileType.REPORT,
                cloudinary_public_id=upload_result.public_id,
                cloudinary_url=upload_result.url,
                cloudinary_secure_url=upload_result.secure_url,
                original_filename=validated_file.filename,
                file_size=validated_file.size,
                mime_type=validated_file.mime_type,
                folder_path=upload_result.folder_path,
                uploaded_at=upload_result.uploaded_at,
            )
            db.add(upload)
            uploads.append(upload)

        db.commit()
    except CloudinaryServiceError as exc:
        db.rollback()
        for public_id, mime_type in uploaded_assets:
            try:
                cloudinary_service.delete_file(public_id=public_id, mime_type=mime_type)
            except CloudinaryServiceError:
                pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File upload failed. Please try again later.",
        ) from exc
    except Exception:
        db.rollback()
        for public_id, mime_type in uploaded_assets:
            try:
                cloudinary_service.delete_file(public_id=public_id, mime_type=mime_type)
            except CloudinaryServiceError:
                pass
        raise

    for upload in uploads:
        db.refresh(upload)

    return [_build_upload_response(upload) for upload in uploads]


@router.get("/my-uploads", response_model=UploadListResponse)
def list_my_uploads(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    upload_type: Annotated[UploadFileType | None, Query(alias="type")] = None,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UploadListResponse:
    query = db.query(Upload).filter(Upload.user_id == current_user.id)
    if upload_type is not None:
        query = query.filter(Upload.file_type == upload_type)

    total = query.count()
    uploads = (
        query.order_by(Upload.uploaded_at.desc(), Upload.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return UploadListResponse(
        uploads=[_build_upload_detail_response(upload) for upload in uploads],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/{upload_id}", response_model=UploadDetailResponse)
def get_upload(
    upload_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UploadDetailResponse:
    upload = db.query(Upload).filter(Upload.id == upload_id, Upload.user_id == current_user.id).first()
    if not upload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    return _build_upload_detail_response(upload)


@router.delete("/{upload_id}", response_model=dict[str, str])
def delete_upload(
    upload_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    cloudinary_service: Annotated[CloudinaryService, Depends(get_cloudinary_service)],
) -> dict[str, str]:
    upload = db.query(Upload).filter(Upload.id == upload_id, Upload.user_id == current_user.id).first()
    if not upload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    try:
        cloudinary_service.delete_file(public_id=upload.cloudinary_public_id, mime_type=upload.mime_type)
    except CloudinaryServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to delete file from Cloudinary.",
        ) from exc

    db.delete(upload)
    db.commit()
    return {"message": "File deleted"}
