from collections.abc import Generator
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import recommendations as recommendations_module
from app.api.v1.endpoints.recommendations import (
    _build_report_file_context,
    _ensure_report_analysis_present,
    get_document_analysis_cache_service,
    get_doctor_recommendation_service,
    get_storage_service,
)
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.services.rate_limit_service import RateLimitService, get_rate_limit_service


class _StubDoctorRecommendationService:
    async def suggest_doctors_preview(self, db, symptoms, prescription_ids=None, preferences=None, **kwargs):
        assert isinstance(symptoms, list)
        return (
            [
                {
                    "doctor_id": "doc-1",
                    "name": "Dr. Precise",
                    "specialization": ["Nephrology"],
                    "hospital_id": None,
                    "experience_years": 14,
                    "average_rating": 4.8,
                    "match_score": 0.91,
                    "rank": 1,
                    "reasons": ["Nephrology matches the documented specialist pathway."],
                    "fit_summary": "Nephrology is a solid match for these symptoms.",
                    "reasoning_source": "rules",
                    "details": {
                        "specialization": 0.95,
                        "continuity_of_care": 0.9,
                        "urgency_fit": 0.85,
                    },
                }
            ],
            {
                "primary_category": "urology",
                "severity": 4,
                "urgency": "moderate",
                "symptom_descriptions": symptoms,
                "recommended_specializations": ["Nephrology"],
                "keyword_hits": ["kidney"],
                "triage_note": "Specialist review is appropriate.",
                "profile_summary": "Kidney-related symptoms with prior specialist context.",
                "analysis_source": "rules",
                "additional_information": [],
                "additional_information_assessment": "",
                "clinical_impression": "Symptoms warrant nephrology review.",
                "likely_concerns": ["Kidney-related issue"],
                "immediate_actions": ["Arrange outpatient review."],
                "red_flags_to_watch": ["Fever", "Worsening pain"],
                "follow_up_questions": ["Any urinary changes?"],
                "recommended_next_steps": ["Book a nephrology follow-up."],
            },
        )

    async def generate_deferred_doctor_reasoning_updates(self, **kwargs):
        doctors = kwargs.get("doctors") or []
        if not doctors:
            return []
        first = doctors[0]
        doctor_id = str(first.get("doctor_id") or first.get("doctorId") or first.get("id") or "")
        if not doctor_id:
            return []
        return [
            {
                "doctor_id": doctor_id,
                "reasons": ["Deferred AI reason."],
                "fit_summary": "Deferred fit summary.",
                "reasoning_source": "openai",
            }
        ]

    async def explain_report_finding(
        self,
        *,
        test_name: str,
        observed_value: str | None,
        reference_range: str | None,
        status: str,
        language: str = "en",
        context: str | None = None,
    ) -> str:
        return f"{test_name} ({status}) indicates contextual review."


class _LanguageAwareDoctorRecommendationService(_StubDoctorRecommendationService):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def suggest_doctors_preview(self, db, symptoms, prescription_ids=None, preferences=None, **kwargs):
        self.calls.append(
            {
                "symptoms": symptoms,
                "preferences": preferences or {},
                **kwargs,
            }
        )
        language = str(kwargs.get("language") or "en").strip().lower()
        triage_note = (
            "বাংলা আউটপুট নিশ্চিত করা হয়েছে।"
            if language == "bn"
            else "English output confirmed."
        )
        next_step = (
            "বাংলা বিশেষজ্ঞ ফলো-আপ বুক করুন।"
            if language == "bn"
            else "Book specialist follow-up."
        )
        return (
            [
                {
                    "doctor_id": "doc-1",
                    "name": "Dr. Precise",
                    "specialization": ["Nephrology"],
                    "hospital_id": None,
                    "experience_years": 14,
                    "average_rating": 4.8,
                    "match_score": 0.91,
                    "rank": 1,
                    "reasons": [triage_note],
                    "fit_summary": triage_note,
                    "reasoning_source": "rules",
                    "details": {
                        "specialization": 0.95,
                        "continuity_of_care": 0.9,
                        "urgency_fit": 0.85,
                    },
                }
            ],
            {
                "primary_category": "urology",
                "severity": 4,
                "urgency": "moderate",
                "symptom_descriptions": symptoms,
                "recommended_specializations": ["Nephrology"],
                "keyword_hits": ["kidney"],
                "triage_note": triage_note,
                "profile_summary": triage_note,
                "analysis_source": "rules",
                "additional_information": [],
                "additional_information_assessment": "",
                "clinical_impression": triage_note,
                "likely_concerns": ["Kidney-related issue"],
                "immediate_actions": [triage_note],
                "red_flags_to_watch": [triage_note],
                "follow_up_questions": [triage_note],
                "recommended_next_steps": [next_step],
            },
        )


class _StubStorageService:
    def __init__(self) -> None:
        self.upload_calls: list[tuple[str, str]] = []

    async def upload_file(self, file, user_id: str) -> str:
        self.upload_calls.append((file.filename or "", user_id))
        return (
            "https://res.cloudinary.com/demo/image/upload/"
            f"v1/healthsynch/users/{user_id}/2026/March/12/{file.filename or 'upload.bin'}"
        )


class _StubPrescriptionAnalyzerService:
    def __init__(self) -> None:
        self.analysis_calls = 0

    async def analyze_prescription_image(self, processing_path: str, language: str = "en") -> dict:
        self.analysis_calls += 1
        return {
            "document_type": "prescription",
            "medications": [{"name": "ECOSPRIN 75 mg"}],
            "diagnosis": "Right Renal Calculi",
            "reported_symptoms": ["flank pain"],
            "warnings": [],
            "analysis_summary": "Prescription suggests kidney-stone follow-up.",
            "confidence_score": 0.82,
        }

    async def extract_medical_conditions(self, parsed: dict) -> list[str]:
        return ["right renal calculi"]


class _StubDocumentAnalysisCacheService:
    def __init__(self) -> None:
        self.cache: dict[tuple[str, str, str, str, str], dict] = {}

    @staticmethod
    def hash_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def get_cached_analysis(
        self,
        *,
        db,
        content_hash: str,
        document_kind: str,
        language: str,
        vision_model: str,
        prompt_version: str,
    ) -> dict | None:
        return self.cache.get((content_hash, document_kind, language, vision_model, prompt_version))

    def upsert_cached_analysis(
        self,
        *,
        db,
        content_hash: str,
        document_kind: str,
        language: str,
        vision_model: str,
        prompt_version: str,
        analysis_payload: dict,
    ) -> None:
        self.cache[(content_hash, document_kind, language, vision_model, prompt_version)] = dict(
            analysis_payload or {}
        )


def _fake_get_db() -> Generator[None, None, None]:
    yield None


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    rate_limit_service = RateLimitService()
    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_doctor_recommendation_service] = lambda: _StubDoctorRecommendationService()
    app.dependency_overrides[get_document_analysis_cache_service] = (
        lambda: _StubDocumentAnalysisCacheService()
    )
    app.dependency_overrides[get_rate_limit_service] = lambda: rate_limit_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_public_suggest_doctors_response_shape_stays_stable(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors",
        json={
            "symptoms": ["flank pain", "blood in urine"],
            "preferences": {"language": "en"},
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert set(payload.keys()) == {"doctor", "doctors", "patient_profile", "symptom_analysis"}
    assert payload["doctor"]["doctor_id"] == "doc-1"
    assert payload["doctor"]["specialization"] == ["Nephrology"]
    assert payload["patient_profile"]["recommended_specializations"] == ["Nephrology"]
    assert payload["symptom_analysis"]["recommended_next_steps"] == ["Book a nephrology follow-up."]


def test_public_suggest_doctors_with_prescription_without_files_response_shape_stays_stable(
    client: TestClient,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors-with-prescription",
        data={
            "symptoms_json": '["flank pain","blood in urine"]',
            "preferences_json": '{"language":"en"}',
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert set(payload.keys()) == {
        "doctor",
        "doctors",
        "patient_profile",
        "symptom_analysis",
        "prescription_context",
        "report_context",
    }
    assert payload["doctor"]["doctor_id"] == "doc-1"
    assert payload["prescription_context"] is None
    assert payload["report_context"] is None


def test_public_suggest_doctors_with_prescription_uploads_public_files_to_storage(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_service = _StubStorageService()
    app.dependency_overrides[get_storage_service] = lambda: storage_service
    monkeypatch.setattr(
        recommendations_module,
        "get_prescription_analyzer_service",
        lambda: _StubPrescriptionAnalyzerService(),
    )

    response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors-with-prescription",
        data={
            "symptoms_json": '["flank pain","fever"]',
            "preferences_json": '{"language":"en"}',
        },
        files={
            "prescription_file": ("kidney-note.jpg", b"fake-image-bytes", "image/jpeg"),
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert storage_service.upload_calls == [("kidney-note.jpg", "public-preview")]
    assert payload["prescription_context"]["file_url"] == (
        "https://res.cloudinary.com/demo/image/upload/"
        "v1/healthsynch/users/public-preview/2026/March/12/kidney-note.jpg"
    )


def test_public_suggest_doctors_prefers_top_level_language_over_preferences_language(
    client: TestClient,
) -> None:
    service = _LanguageAwareDoctorRecommendationService()
    app.dependency_overrides[get_doctor_recommendation_service] = lambda: service

    response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors",
        json={
            "symptoms": ["flank pain", "blood in urine"],
            "preferences": {"language": "en"},
            "language": "bn",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert service.calls[-1]["language"] == "bn"
    assert payload["symptom_analysis"]["triage_note"] == "বাংলা আউটপুট নিশ্চিত করা হয়েছে।"
    assert payload["symptom_analysis"]["recommended_next_steps"] == ["বাংলা বিশেষজ্ঞ ফলো-আপ বুক করুন।"]


def test_public_suggest_doctors_with_prescription_prefers_top_level_language_over_preferences_language(
    client: TestClient,
) -> None:
    service = _LanguageAwareDoctorRecommendationService()
    app.dependency_overrides[get_doctor_recommendation_service] = lambda: service

    response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors-with-prescription",
        data={
            "symptoms_json": '["flank pain","blood in urine"]',
            "preferences_json": '{"language":"en"}',
            "language": "bn",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert service.calls[-1]["language"] == "bn"
    assert payload["symptom_analysis"]["triage_note"] == "বাংলা আউটপুট নিশ্চিত করা হয়েছে।"
    assert payload["symptom_analysis"]["recommended_next_steps"] == ["বাংলা বিশেষজ্ঞ ফলো-আপ বুক করুন।"]


def test_public_suggest_doctors_enforces_ip_rate_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.rate_limit_service.settings.RATE_LIMIT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.rate_limit_service.settings.REDIS_ENABLED",
        False,
        raising=False,
    )
    payload = {
        "symptoms": ["flank pain", "blood in urine"],
        "preferences": {"language": "en"},
    }

    first_response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors",
        json=payload,
    )
    second_response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors",
        json=payload,
    )
    third_response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors",
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert third_response.status_code == 429
    assert third_response.headers["X-RateLimit-Remaining"] == "0"
    assert third_response.json()["detail"]["limit"] == 2


def test_public_suggest_doctors_with_prescription_cache_hit_skips_vision_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_service = _StubStorageService()
    analyzer_service = _StubPrescriptionAnalyzerService()
    cache_service = _StubDocumentAnalysisCacheService()
    app.dependency_overrides[get_storage_service] = lambda: storage_service
    app.dependency_overrides[get_document_analysis_cache_service] = lambda: cache_service
    monkeypatch.setattr(
        recommendations_module,
        "get_prescription_analyzer_service",
        lambda: analyzer_service,
    )
    payload = {
        "symptoms_json": '["flank pain","fever"]',
        "preferences_json": '{"language":"en"}',
    }
    file_payload = {
        "prescription_file": ("kidney-note.jpg", b"same-image-bytes", "image/jpeg"),
    }

    first = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors-with-prescription",
        data=payload,
        files=file_payload,
    )
    second = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors-with-prescription",
        data=payload,
        files=file_payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert analyzer_service.analysis_calls == 1
    assert first.json()["prescription_context"]["diagnosis"] == "Right Renal Calculi"
    assert second.json()["prescription_context"]["diagnosis"] == "Right Renal Calculi"


def test_public_suggest_doctors_with_report_upload_always_returns_report_analysis(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_service = _StubStorageService()
    analyzer_service = _StubPrescriptionAnalyzerService()
    app.dependency_overrides[get_storage_service] = lambda: storage_service
    monkeypatch.setattr(
        recommendations_module,
        "get_prescription_analyzer_service",
        lambda: analyzer_service,
    )

    response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors-with-prescription",
        data={
            "symptoms_json": '["flank pain","fever"]',
            "preferences_json": '{"language":"en"}',
            "language": "en",
        },
        files={
            "report_files": ("cbc-report.jpg", b"fake-report-bytes", "image/jpeg"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_context"] is not None
    assert payload["symptom_analysis"]["report_analysis"]["overall_assessment"]


def test_ensure_report_analysis_present_replaces_low_value_llm_report_summary() -> None:
    updated = _ensure_report_analysis_present(
        {
            "report_analysis": {
                "overall_assessment": "No specific lab findings were provided in the report.",
                "lab_findings": [],
            }
        },
        {
            "analysis_summary": "CBC summary suggests anemia with low hemoglobin.",
            "report_findings": [],
        },
        language="en",
    )

    assert (
        updated["report_analysis"]["overall_assessment"]
        == "CBC summary suggests anemia with low hemoglobin."
    )


def test_ensure_report_analysis_present_prefers_context_summary_when_no_findings_exist() -> None:
    updated = _ensure_report_analysis_present(
        {
            "report_analysis": {
                "overall_assessment": "No abnormal lab findings were reported, indicating stable conditions post-stroke.",
                "lab_findings": [],
            }
        },
        {
            "analysis_summary": "This document is a clinical report on stroke, not a patient-specific lab report.",
            "report_findings": [],
        },
        language="en",
    )

    assert (
        updated["report_analysis"]["overall_assessment"]
        == "This document is a clinical report on stroke, not a patient-specific lab report."
    )


def test_build_report_file_context_uses_meaningful_extraction_notes_when_summary_missing() -> None:
    context = _build_report_file_context(
        {
            "file_name": "stroke_report.pdf",
            "file_url": "https://example.com/stroke_report.pdf",
            "parsed": {
                "document_type": "report",
                "confidence_score": 0.72,
                "analysis_summary": None,
                "extraction_notes": "This document appears to be a clinical report on stroke, not a patient-specific lab table.",
                "report_findings": [],
                "vision_status": "used",
                "analysis_source": "openai_vision",
            },
            "reported_symptoms": [],
        }
    )

    assert (
        context["analysis_summary"]
        == "This document appears to be a clinical report on stroke, not a patient-specific lab table."
    )


def test_build_report_file_context_ignores_low_value_extraction_notes() -> None:
    context = _build_report_file_context(
        {
            "file_name": "cbc-report.pdf",
            "file_url": "https://example.com/cbc-report.pdf",
            "parsed": {
                "document_type": "report",
                "confidence_score": 0.72,
                "analysis_summary": None,
                "extraction_notes": "Typed report",
                "report_findings": [],
                "vision_status": "used",
                "analysis_source": "openai_vision",
            },
            "reported_symptoms": [],
        }
    )

    assert context["analysis_summary"] is None


def test_ensure_report_analysis_present_uses_clear_upload_fallback_when_report_is_unstructured() -> None:
    updated = _ensure_report_analysis_present(
        {
            "report_analysis": {
                "overall_assessment": "No lab findings were provided in the report.",
                "lab_findings": [],
            }
        },
        {
            "analysis_summary": None,
            "report_findings": [],
        },
        language="en",
    )

    assert (
        updated["report_analysis"]["overall_assessment"]
        == "Report uploaded, but clear structured values could not be extracted. Re-uploading a clearer copy can improve analysis."
    )


def test_public_suggest_doctors_with_prescription_stream_emits_expected_event_sequence(
    client: TestClient,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-suggest-doctors-with-prescription/stream",
        data={
            "symptoms_json": json.dumps(["flank pain"]),
            "preferences_json": "{}",
            "language": "en",
        },
    )

    assert response.status_code == 200
    events = [
        line.split(":", 1)[1].strip()
        for line in response.text.splitlines()
        if line.startswith("event:")
    ]
    assert events[0] == "start"
    assert "symptom_analysis" in events
    assert "doctors" in events
    assert "doctor_reasons" in events
    assert events[-1] == "done"
    assert events.index("doctors") < events.index("doctor_reasons")


def test_public_report_finding_explanation_returns_short_explanation(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/recommendations/public-report-finding-explanation",
        json={
            "test_name": "Hemoglobin",
            "observed_value": "13.9",
            "reference_range": "12-16",
            "status": "normal",
            "language": "en",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["explanation"] == "Hemoglobin (normal) indicates contextual review."
