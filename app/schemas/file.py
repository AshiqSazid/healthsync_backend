from datetime import datetime

from pydantic import BaseModel


class ApiEnvelope(BaseModel):
    success: bool
    message: str
    timestamp: datetime
    metadata: dict | None = None
    errorCode: str | None = None


class FileUploadPayload(BaseModel):
    id: str
    fileName: str
    originalFileName: str
    filePath: str
    fileType: str
    fileSize: int
    fileHash: str
    uploadedBy: str
    uploadIp: str
    status: str
    virusScanned: bool
    virusFound: bool
    scanResult: str | None = None
    userId: str | None = None
    createdAt: datetime
    updatedAt: datetime


class DoctorImagePayload(BaseModel):
    id: str
    fileName: str
    originalFileName: str
    filePath: str
    fileType: str
    fileSize: int
    fileUrl: str
    doctorId: str
    createdAt: datetime


class FileUploadResponse(ApiEnvelope):
    data: FileUploadPayload


class DoctorImageResponse(ApiEnvelope):
    data: DoctorImagePayload | None = None
