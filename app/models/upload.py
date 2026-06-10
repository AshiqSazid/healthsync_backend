from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.enums import UploadFileType


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_type: Mapped[UploadFileType] = mapped_column(
        SAEnum(UploadFileType, name="upload_file_type"),
        nullable=False,
        index=True,
    )
    cloudinary_public_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    cloudinary_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    cloudinary_secure_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    folder_path: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="uploads")
