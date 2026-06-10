from datetime import datetime

from pydantic import Field

from app.models.enums import SymptomCategory
from app.schemas.common import ORMModel


class SymptomBase(ORMModel):
    name: str
    description: str | None = None
    category: SymptomCategory = SymptomCategory.GENERAL
    severity_level: int = Field(default=1, ge=1, le=10)
    common_causes: list[str] = []
    related_symptoms: list[str] = []
    recommended_specializations: list[str] = []
    urgency_indicators: dict = {}


class SymptomCreate(SymptomBase):
    pass


class SymptomUpdate(ORMModel):
    name: str | None = None
    description: str | None = None
    category: SymptomCategory | None = None
    severity_level: int | None = Field(default=None, ge=1, le=10)
    common_causes: list[str] | None = None
    related_symptoms: list[str] | None = None
    recommended_specializations: list[str] | None = None
    urgency_indicators: dict | None = None


class SymptomResponse(SymptomBase):
    id: str
    created_at: datetime
    updated_at: datetime
