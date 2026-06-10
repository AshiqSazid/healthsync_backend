from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.enums import FileScanStatus


class FileRecord(Base):
    __tablename__ = "file_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False, default="anonymous")
    upload_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    status: Mapped[FileScanStatus] = mapped_column(
        Enum(FileScanStatus, name="file_scan_status"),
        nullable=False,
        default=FileScanStatus.CLEAN,
        index=True,
    )
    virus_scanned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    virus_found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scan_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
