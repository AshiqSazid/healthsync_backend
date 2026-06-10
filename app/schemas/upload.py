from __future__ import annotations

from datetime import datetime

from app.models.enums import UploadFileType
from app.schemas.common import ORMModel


class UploadResponse(ORMModel):
    id: str
    file_type: UploadFileType
    url: str
    secure_url: str
    folder_path: str
    uploaded_at: datetime


class UploadDetailResponse(UploadResponse):
    original_filename: str
    file_size: int
    mime_type: str


class UploadListResponse(ORMModel):
    uploads: list[UploadDetailResponse]
    total: int
    page: int
    limit: int
