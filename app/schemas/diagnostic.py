from datetime import date, datetime

from app.schemas.common import ORMModel


class DiagnosticBase(ORMModel):
    user_id: str
    doctor_id: str
    symptom_checker_session_id: str | None = None
    prescription_id: str | None = None
    diagnosis: str | None = None
    prescription_text: str | None = None
    lab_tests: list[dict] = []
    follow_up_date: date | None = None
    notes: str | None = None


class DiagnosticCreate(DiagnosticBase):
    pass


class DiagnosticUpdate(ORMModel):
    diagnosis: str | None = None
    prescription_text: str | None = None
    lab_tests: list[dict] | None = None
    follow_up_date: date | None = None
    notes: str | None = None


class DiagnosticResponse(DiagnosticBase):
    id: str
    created_at: datetime
    updated_at: datetime
