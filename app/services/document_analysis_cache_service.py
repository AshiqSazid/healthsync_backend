from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta
import hashlib
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document_analysis_cache import DocumentAnalysisCache
from app.core.config import settings

logger = logging.getLogger(__name__)


class DocumentAnalysisCacheService:
    @staticmethod
    def hash_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _can_query(db: Session | None) -> bool:
        return bool(db and hasattr(db, "query"))

    def get_cached_analysis(
        self,
        *,
        db: Session | None,
        content_hash: str,
        document_kind: str,
        language: str,
        vision_model: str,
        prompt_version: str,
    ) -> dict[str, Any] | None:
        if not self._can_query(db):
            return None
        try:
            row = (
                db.query(DocumentAnalysisCache)
                .filter(
                    DocumentAnalysisCache.content_hash == content_hash,
                    DocumentAnalysisCache.document_kind == document_kind,
                    DocumentAnalysisCache.language == language,
                    DocumentAnalysisCache.vision_model == vision_model,
                    DocumentAnalysisCache.prompt_version == prompt_version,
                )
                .first()
            )
            if row is None:
                return None
            if row.expires_at and row.expires_at <= datetime.now(timezone.utc):
                return None

            row.hit_count = int(row.hit_count or 0) + 1
            row.last_accessed_at = datetime.now(timezone.utc)
            db.add(row)
            db.commit()
            return dict(row.analysis_payload or {})
        except SQLAlchemyError as exc:
            logger.warning("Document analysis cache lookup failed: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass
            return None

    def upsert_cached_analysis(
        self,
        *,
        db: Session | None,
        content_hash: str,
        document_kind: str,
        language: str,
        vision_model: str,
        prompt_version: str,
        analysis_payload: dict[str, Any],
    ) -> None:
        if not self._can_query(db):
            return
        try:
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=settings.DOCUMENT_ANALYSIS_CACHE_TTL_DAYS)
            row = (
                db.query(DocumentAnalysisCache)
                .filter(
                    DocumentAnalysisCache.content_hash == content_hash,
                    DocumentAnalysisCache.document_kind == document_kind,
                    DocumentAnalysisCache.language == language,
                    DocumentAnalysisCache.vision_model == vision_model,
                    DocumentAnalysisCache.prompt_version == prompt_version,
                )
                .first()
            )
            if row is None:
                row = DocumentAnalysisCache(
                    content_hash=content_hash,
                    document_kind=document_kind,
                    language=language,
                    vision_model=vision_model,
                    prompt_version=prompt_version,
                    analysis_payload=dict(analysis_payload or {}),
                    hit_count=0,
                    last_accessed_at=now,
                    expires_at=expires_at,
                )
            else:
                row.analysis_payload = dict(analysis_payload or {})
                row.updated_at = now
                row.expires_at = expires_at

            db.add(row)
            db.commit()
        except SQLAlchemyError as exc:
            logger.warning("Document analysis cache write failed: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass
