from datetime import datetime

from pydantic import Field

from app.models.enums import AssessmentDocumentStatus
from app.schemas.common import ORMModel


class AssessmentDocumentBase(ORMModel):
    session_id: str
    title: str
    symptom_name: str | None = None
    source_route: str | None = None
    intake_payload: dict = Field(default_factory=dict)
    ai_output: dict = Field(default_factory=dict)
    conversation_log: list[dict] = Field(default_factory=list)
    status: AssessmentDocumentStatus = AssessmentDocumentStatus.DRAFT


class AssessmentDocumentCreate(AssessmentDocumentBase):
    pass


class AssessmentDocumentUpdate(ORMModel):
    title: str | None = None
    symptom_name: str | None = None
    source_route: str | None = None
    intake_payload: dict | None = None
    ai_output: dict | None = None
    conversation_log: list[dict] | None = None
    status: AssessmentDocumentStatus | None = None


class AssessmentDocumentResponse(AssessmentDocumentBase):
    id: str
    user_id: str
    size_bytes: int = 0
    summary: str | None = None
    created_at: datetime
    updated_at: datetime
