from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import textwrap
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.llm_client import LLMClient
from app.ai.medical_normalization import (
    canonical_specialties,
    is_low_value_report_analysis,
    medication_concepts,
    merge_specialties,
    normalize_report_test_name,
    normalize_text as normalize_medical_text,
    specialty_matches,
)
from app.ai.medical_prompts import (
    DOCTOR_RECOMMENDATION_SYSTEM_PROMPT,
    SYMPTOM_TRIAGE_SYSTEM_PROMPT,
    get_prompt,
    normalize_response_language,
)
from app.ai.openai_response_utils import clamp_confidence
from app.core.config import settings
from app.models.doctor import Doctor
from app.models.prescription import Prescription
from app.models.recommendation import DoctorRecommendation

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PreviewDoctorCandidate:
    id: str
    user: Any = None
    specialization: list[str] = field(default_factory=list)
    hospital_id: str | None = None
    experience_years: float = 0.0
    average_rating: float = 0.0
    available_slots: list[dict[str, Any]] = field(default_factory=list)
    conditions_treated: list[str] = field(default_factory=list)
    source_payload: dict[str, Any] = field(default_factory=dict)


class DoctorRecommendationService:
    def __init__(self) -> None:
        self.llm_client = LLMClient()
        self._public_doctor_candidates_cache: list[PreviewDoctorCandidate] | None = None
        self._public_doctor_candidates_cache_expires_at: float = 0.0
        self._public_doctor_candidates_pending_task: asyncio.Task[list[PreviewDoctorCandidate]] | None = None

    @staticmethod
    def _should_skip_preview_db_lookup() -> bool:
        # Vercel cannot use the default relative SQLite fallback as a real production DB.
        return (
            settings.SQLALCHEMY_DATABASE_URI == "sqlite:///./healthsynch.db"
            and (settings.ENVIRONMENT == "production" or os.getenv("VERCEL") == "1")
        )

    @staticmethod
    def _coerce_public_api_string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _normalize_public_doctor_candidate(self, payload: dict[str, Any]) -> PreviewDoctorCandidate | None:
        if not isinstance(payload, dict):
            return None

        public_id = payload.get("id")
        normalized_id = str(public_id or payload.get("doctorId") or payload.get("doctor_id") or "").strip()
        if not normalized_id:
            return None

        doctor_name = str(payload.get("name") or "").strip() or "Doctor"
        specialization = self._coerce_public_api_string_list(payload.get("specialization"))
        locations = payload.get("locations") if isinstance(payload.get("locations"), list) else []
        available_slots = locations if locations else []
        conditions_treated = self._coerce_public_api_string_list(payload.get("servesFor"))
        experience_years = self._coerce_float(
            payload.get("experience_years") or payload.get("experience")
        ) or 0.0
        average_rating = self._coerce_float(payload.get("average_rating")) or 0.0

        return PreviewDoctorCandidate(
            id=normalized_id,
            user=SimpleNamespace(username=doctor_name),
            specialization=specialization,
            hospital_id=str(payload.get("hospitalId") or payload.get("hospital_id") or "").strip() or None,
            experience_years=experience_years,
            average_rating=average_rating,
            available_slots=available_slots,
            conditions_treated=conditions_treated,
            source_payload=dict(payload),
        )

    async def _fetch_public_doctor_candidates(self) -> list[PreviewDoctorCandidate]:
        ttl_seconds = max(float(settings.PUBLIC_DOCTOR_API_CACHE_TTL_SECONDS or 0.0), 0.0)
        now = time.monotonic()
        if (
            ttl_seconds > 0
            and self._public_doctor_candidates_cache is not None
            and self._public_doctor_candidates_cache_expires_at > now
        ):
            logger.info(
                "Public doctor source cache hit candidate_count=%d",
                len(self._public_doctor_candidates_cache),
            )
            return list(self._public_doctor_candidates_cache)

        pending_task = self._public_doctor_candidates_pending_task
        if pending_task is not None:
            return list(await pending_task)

        fetch_task = asyncio.create_task(self._load_public_doctor_candidates())
        self._public_doctor_candidates_pending_task = fetch_task
        try:
            candidates = await fetch_task
            if ttl_seconds > 0:
                self._public_doctor_candidates_cache = list(candidates)
                self._public_doctor_candidates_cache_expires_at = time.monotonic() + ttl_seconds
            return list(candidates)
        finally:
            if self._public_doctor_candidates_pending_task is fetch_task:
                self._public_doctor_candidates_pending_task = None

    async def _load_public_doctor_candidates(self) -> list[PreviewDoctorCandidate]:
        # Load from local static config — no external API call needed.
        started_at = time.monotonic()
        try:
            from app.local_doctors import get_doctors_with_urls
            doctors = get_doctors_with_urls("")
        except Exception as exc:
            logger.warning("Could not load local doctor config: %s", exc)
            return []

        candidates: list[PreviewDoctorCandidate] = []
        for doc in doctors:
            candidate = self._normalize_public_doctor_candidate({
                "id": str(doc["id"]),
                "name": doc.get("name", "Doctor"),
                "display_name": doc.get("display_name") or doc.get("name", "Doctor"),
                "specialization": doc.get("specialization", []),
                "experience_years": doc.get("experience_years", 0),
                "average_rating": 0.0,
                "education": doc.get("education", []),
                "locations": doc.get("available_slots", []),
                "consultation_fee": doc.get("consultation_fee"),
                "consultation_fee_currency": doc.get("consultation_fee_currency", "BDT"),
                "photo_url": doc.get("photo_url"),
                "image_url": doc.get("photo_url"),
                "imageUrl": doc.get("photo_url"),
                "has_photo": doc.get("has_photo", False),
            })
            if candidate is not None:
                candidates.append(candidate)

        logger.info(
            "Local doctor config loaded duration_ms=%d candidate_count=%d",
            int((time.monotonic() - started_at) * 1000),
            len(candidates),
        )
        return candidates

    async def _fetch_public_doctor_candidate_page(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        path: str,
        page: int,
        page_size: int,
    ) -> tuple[list[PreviewDoctorCandidate], int]:
        response = await client.get(
            f"{base_url}{path}",
            params={
                "page": page,
                "size": page_size,
                "sortBy": "createdAt",
                "sortDirection": "asc",
            },
        )
        response.raise_for_status()

        payload = response.json()
        payload_data = payload.get("data") if isinstance(payload, dict) else payload
        page_content = payload_data.get("content") if isinstance(payload_data, dict) else payload_data
        doctors = page_content if isinstance(page_content, list) else []

        normalized_candidates: list[PreviewDoctorCandidate] = []
        for item in doctors:
            candidate = self._normalize_public_doctor_candidate(item)
            if candidate is not None:
                normalized_candidates.append(candidate)

        total_pages = 1
        if isinstance(payload_data, dict):
            try:
                total_pages = max(int(payload_data.get("totalPages") or 1), 1)
            except (TypeError, ValueError):
                total_pages = 1

        return normalized_candidates, total_pages

    async def recommend_doctors(
        self,
        db: Session,
        user_id: str,
        symptoms: list[str],
        prescription_ids: list[str] | None = None,
        preferences: dict | None = None,
        symptom_checker_session_id: str | None = None,
        previous_session_context: dict | None = None,
        language: str = "en",
    ) -> tuple[DoctorRecommendation, list[dict[str, Any]]]:
        normalized_language = normalize_response_language(language)
        effective_preferences = dict(preferences or {})
        effective_preferences["language"] = normalized_language
        medical_history = await self._analyze_prescriptions(
            db,
            prescription_ids or [],
            user_id=user_id,
        )
        symptom_analysis = await self._analyze_symptoms(
            symptoms,
            previous_session_context=previous_session_context,
            language=normalized_language,
        )
        symptom_analysis = self._apply_medical_context_routing(
            symptom_analysis,
            medical_history,
            language=normalized_language,
        )
        symptom_analysis = self._prioritize_specialty_recommendations(
            symptom_analysis,
            medical_history,
            language=normalized_language,
        )

        candidates = await self._get_candidate_doctors(
            db,
            symptom_analysis,
            medical_history,
            effective_preferences,
        )
        ranked_doctors = await self._score_and_rank(
            candidates,
            symptom_analysis,
            medical_history,
            effective_preferences,
            language=normalized_language,
        )

        recommendation = DoctorRecommendation(
            user_id=user_id,
            symptom_checker_session_id=symptom_checker_session_id,
            prescription_ids=prescription_ids or [],
            recommended_doctors=ranked_doctors,
            recommendation_criteria={
                "symptoms": symptoms,
                "preferences": effective_preferences,
                "symptom_analysis": symptom_analysis,
                "medical_history": medical_history,
            },
            algorithm_version="v1",
        )
        db.add(recommendation)
        db.commit()
        db.refresh(recommendation)

        return recommendation, ranked_doctors

    async def suggest_doctors_preview(
        self,
        db: Session,
        symptoms: list[str],
        prescription_ids: list[str] | None = None,
        preferences: dict | None = None,
        external_medical_conditions: list[str] | None = None,
        external_recent_diagnoses: list[str] | None = None,
        external_symptom_context: list[str] | None = None,
        prescription_medications: list[dict] | None = None,
        prescription_instructions: str | None = None,
        document_warnings: list[str] | None = None,
        report_findings: list[dict] | None = None,
        document_summary: str | None = None,
        language: str = "en",
        include_llm_reasons: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        normalized_language = normalize_response_language(language)
        effective_preferences = dict(preferences or {})
        effective_preferences["language"] = normalized_language
        analysis_context = self._coerce_analysis_context(effective_preferences)
        context_conditions = self._coerce_string_list(analysis_context.get("extracted_conditions"))
        context_diagnoses = self._coerce_string_list(analysis_context.get("diagnosis"))
        context_specializations = self._coerce_string_list(
            analysis_context.get("doctor_specialization")
        )
        context_recommended_specs = self._coerce_string_list(
            analysis_context.get("recommended_specializations")
        )
        context_warnings = self._coerce_string_list(analysis_context.get("document_warnings"))
        context_report_findings = (
            analysis_context.get("report_findings")
            if isinstance(analysis_context.get("report_findings"), list)
            else []
        )
        context_medications = (
            analysis_context.get("medications")
            if isinstance(analysis_context.get("medications"), list)
            else []
        )
        context_report_summary = str(analysis_context.get("report_summary") or "").strip() or None
        context_clinical_impression = (
            str(analysis_context.get("clinical_impression") or "").strip() or None
        )
        context_additional_assessment = (
            str(analysis_context.get("additional_information_assessment") or "").strip() or None
        )
        context_prescription_instructions = (
            str(analysis_context.get("prescription_instructions") or "").strip() or None
        )

        medical_history = await self._analyze_prescriptions(
            db,
            prescription_ids or [],
            user_id=None,
        )
        medical_history = self._merge_external_medical_context(
            medical_history,
            external_medical_conditions=self._merge_unique_strings(
                context_conditions,
                external_medical_conditions or [],
                limit=20,
            ),
            external_recent_diagnoses=self._merge_unique_strings(
                context_diagnoses,
                external_recent_diagnoses or [],
                limit=10,
            ),
        )
        if context_specializations or context_recommended_specs:
            medical_history["previous_specializations"] = self._merge_unique_strings(
                context_specializations,
                context_recommended_specs,
                self._coerce_string_list(medical_history.get("previous_specializations")),
                limit=8,
            )
        clean_symptoms = [str(item).strip() for item in symptoms if str(item).strip()]
        extra_symptom_context = [
            str(item).strip()
            for item in (external_symptom_context or [])
            if str(item).strip()
        ]
        merged_symptoms = self._merge_unique_strings(clean_symptoms, extra_symptom_context, limit=24)
        # Extract diagnosis from external_recent_diagnoses for AI analysis
        diagnosis = None
        diagnosis_candidates = self._merge_unique_strings(
            context_diagnoses,
            external_recent_diagnoses or [],
            limit=4,
        )
        if diagnosis_candidates:
            diagnosis = diagnosis_candidates[0]
        # Extract doctor specialization from medical history
        doctor_specializations = self._merge_unique_strings(
            context_specializations,
            context_recommended_specs,
            self._coerce_string_list(medical_history.get("previous_specializations")),
            limit=8,
        )
        doctor_specialization = doctor_specializations[0] if doctor_specializations else None
        symptom_analysis = await self._analyze_symptoms(
            merged_symptoms,
            prescription_medications or context_medications,
            diagnosis,
            report_findings=report_findings or context_report_findings,
            document_summary=document_summary or context_report_summary or context_clinical_impression,
            document_instructions=prescription_instructions or context_prescription_instructions,
            document_warnings=self._merge_unique_strings(
                context_warnings,
                document_warnings or [],
                limit=10,
            ),
            doctor_specialization=doctor_specialization,
            language=normalized_language,
        )
        symptom_analysis = self._apply_medical_context_routing(
            symptom_analysis,
            medical_history,
            language=normalized_language,
        )
        if context_recommended_specs or doctor_specialization:
            symptom_analysis = self._prioritize_specialty_recommendations(
                symptom_analysis,
                medical_history,
                preferred_specializations=self._merge_unique_strings(
                    [doctor_specialization] if doctor_specialization else [],
                    context_recommended_specs,
                    limit=6,
                ),
                language=normalized_language,
            )
        else:
            symptom_analysis = self._prioritize_specialty_recommendations(
                symptom_analysis,
                medical_history,
                language=normalized_language,
            )
        if context_additional_assessment and not str(
            symptom_analysis.get("additional_information_assessment") or ""
        ).strip():
            symptom_analysis["additional_information_assessment"] = context_additional_assessment
        candidates: list[Doctor | PreviewDoctorCandidate] = []
        try:
            candidates = await self._fetch_public_doctor_candidates()
        except Exception as exc:
            logger.warning(
                "Public doctor source unavailable for preview suggestions; falling back to local DB: %s",
                exc,
            )

        if candidates:
            logger.info(
                "Preview doctor lookup loaded %d candidates from public doctor source",
                len(candidates),
            )
        elif self._should_skip_preview_db_lookup():
            logger.info(
                "Preview doctor lookup skipped: SQLALCHEMY_DATABASE_URI is using the default SQLite fallback."
            )
        else:
            try:
                candidates = await self._get_candidate_doctors(
                    db,
                    symptom_analysis,
                    medical_history,
                    effective_preferences,
                )
            except SQLAlchemyError as exc:
                logger.warning(
                    "Preview doctor lookup unavailable; returning analysis without doctors: %s",
                    exc,
                )
                candidates = []
        ranked = await self._score_and_rank(
            candidates,
            symptom_analysis,
            medical_history,
            effective_preferences,
            language=normalized_language,
            include_llm_reasons=include_llm_reasons,
        )
        return ranked, symptom_analysis

    async def generate_external_doctor_previews(
        self,
        symptoms: list[str],
        doctors: list[dict[str, Any]],
        limit: int = 6,
        language: str = "en",
    ) -> tuple[dict[str, dict[str, Any]], str]:
        normalized_language = normalize_response_language(language)
        clean_symptoms = [str(item).strip() for item in symptoms if str(item).strip()]
        if not clean_symptoms:
            return {}, "rules"
        if not doctors:
            return {}, "rules"

        normalized_limit = max(1, min(int(limit or 6), 10))
        normalized_candidates: list[dict[str, Any]] = []
        for index, item in enumerate(doctors[:normalized_limit]):
            if not isinstance(item, dict):
                continue
            doctor_id = str(item.get("doctor_id") or item.get("id") or item.get("doctorId") or "").strip()
            if not doctor_id:
                doctor_id = f"external-{index + 1}"

            normalized_candidates.append(
                {
                    "doctor_id": doctor_id,
                    "name": str(item.get("name") or "").strip() or "Doctor",
                    "specialization": self._coerce_string_list(item.get("specialization")),
                    "experience_years": self._coerce_float(item.get("experience_years") or item.get("experience")) or 0.0,
                    "average_rating": self._coerce_float(item.get("average_rating")) or 0.0,
                    "match_score": self._coerce_float(item.get("match_score")) or 0.0,
                    "current_reasons": self._coerce_string_list(
                        item.get("current_reasons") or item.get("reasons")
                    ),
                }
            )

        if not normalized_candidates:
            return {}, "rules"

        symptom_analysis = await self._analyze_symptoms(
            clean_symptoms,
            language=normalized_language,
        )
        llm_rationales = await self._generate_doctor_rationales_with_llm(
            symptom_analysis=symptom_analysis,
            medical_history={},
            ranked_doctors=normalized_candidates,
            language=normalized_language,
        )
        if llm_rationales:
            return llm_rationales, "openai"

        fallback: dict[str, dict[str, Any]] = {}
        for candidate in normalized_candidates:
            candidate_id = str(candidate.get("doctor_id") or "").strip()
            if not candidate_id:
                continue
            fallback[candidate_id] = {
                "reasons": [],
                "fit_summary": "",
            }
        return fallback, "rules"

    async def _analyze_symptoms(
        self,
        symptoms: list[str],
        medications: list[dict] | None = None,
        diagnosis: str | None = None,
        report_findings: list[dict] | None = None,
        document_summary: str | None = None,
        document_instructions: str | None = None,
        document_warnings: list[str] | None = None,
        doctor_specialization: str | None = None,
        previous_session_context: dict | None = None,
        language: str = "en",
    ) -> dict:
        normalized_language = normalize_response_language(language)
        clean_symptoms = [str(item).strip() for item in symptoms if str(item).strip()]
        additional_information = self._extract_additional_information(clean_symptoms)
        additional_information_assessment = self._build_additional_information_assessment(
            additional_information,
            language=normalized_language,
        )
        normalized_report_findings = self._normalize_report_findings(report_findings)
        normalized_warnings = self._coerce_string_list(document_warnings)
        template_follow_up_questions = self._build_default_follow_up_questions(
            clean_symptoms,
            diagnosis=diagnosis,
            medications=medications,
            report_findings=normalized_report_findings,
            document_summary=document_summary,
            language=normalized_language,
        )
        llm_analysis = await self._analyze_symptoms_with_llm(
            clean_symptoms,
            medications,
            diagnosis,
            report_findings=normalized_report_findings,
            document_summary=document_summary,
            document_instructions=document_instructions,
            document_warnings=normalized_warnings,
            doctor_specialization=doctor_specialization,
            previous_session_context=previous_session_context,
            language=normalized_language,
        )
        if llm_analysis:
            llm_analysis["additional_information"] = additional_information
            # Follow-up questions are always template-based for speed and determinism.
            llm_analysis["follow_up_questions"] = template_follow_up_questions
            return self._finalize_symptom_analysis_output(
                llm_analysis,
                language=normalized_language,
            )

        lower = [s.lower().strip() for s in clean_symptoms]
        joined = " ".join(lower)
        diagnosis_text = self._normalize_text(diagnosis or "")
        document_summary_text = self._normalize_text(document_summary or "")
        doctor_specialization_text = self._normalize_text(doctor_specialization or "")
        report_finding_text = self._normalize_text(
            " ".join(
                [
                    str(item.get("test_name") or "").strip()
                    for item in normalized_report_findings
                    if str(item.get("test_name") or "").strip()
                ]
            )
        )
        context_joined = self._normalize_text(
            " ".join(
                part
                for part in [
                    joined,
                    diagnosis_text,
                    document_summary_text,
                    doctor_specialization_text,
                    report_finding_text,
                ]
                if part
            )
        )
        category = "general"
        recommended_specs = ["Internal Medicine"]
        keyword_hits: list[str] = []

        oncology_terms = [
            "cancer",
            "oncology",
            "tumor",
            "mass",
            "radiotherapy",
            "chemo",
            "metastatic",
            "lymph node",
            "unexplained weight loss",
            "breast lump",
            "breast mass",
            "nipple discharge",
            "gynecological cancer",
            "lung cancer",
        ]
        neuro_terms = [
            "neuro",
            "neurology",
            "headache",
            "migraine",
            "seizure",
            "stroke",
            "nerve",
            "brain",
            "memory",
            "numbness",
            "weakness",
            "dizziness",
            "slurred speech",
            "speech difficulty",
            "facial droop",
            "one-sided weakness",
            "tingling",
        ]
        cardiac_terms = [
            "heart",
            "cardiac",
            "cardio",
            "chest pain",
            "palpitation",
            "bp",
            "pressure",
            "tight",
            "exertion",
            "shortness of breath",
            "breathlessness",
            "squeezing or pressure",
            "mild to moderate exertion",
            "jaw pain",
            "left arm pain",
            "sweating",
            "syncope",
        ]
        respiratory_terms = ["cough", "asthma", "breath", "wheeze", "phlegm", "respiratory infection"]
        gastrointestinal_terms = [
            "abdominal pain",
            "abdomen",
            "stomach pain",
            "stomach",
            "bowel",
            "colorectal",
            "gastrointestinal",
            "gastroenterology",
            "gi pain",
            "indigestion",
            "bloating",
            "constipation",
            "diarrhea",
            "diverticulum",
            "diverticulitis",
            "blood in stool",
            "rectal bleeding",
            "vomiting",
            "nausea",
            "change in bowel habit",
            "black stool",
            "melena",
            "bilirubin",
            "alt",
            "sgpt",
            "alkaline phosphatase",
            "liver function test",
            "hepatobiliary",
            "pancreatic",
            "liver",
        ]
        urology_terms = [
            "kidney stone",
            "kidney stones",
            "renal calculi",
            "renal calculus",
            "renal stone",
            "urolithiasis",
            "nephrolithiasis",
            "ureteric stone",
            "ureter stone",
            "flank pain",
            "renal colic",
            "hematuria",
            "blood in urine",
            "painful urination",
            "dysuria",
            "urinary urgency",
            "unable to urinate",
        ]
        dermatology_terms = [
            "rash",
            "skin rash",
            "itching",
            "itchy skin",
            "hives",
            "urticaria",
            "eczema",
            "psoriasis",
            "skin lesion",
            "drug rash",
        ]
        endocrinology_terms = [
            "diabetes",
            "high blood sugar",
            "low blood sugar",
            "blood sugar",
            "polyuria",
            "polydipsia",
            "thyroid",
            "heat intolerance",
            "cold intolerance",
            "unexplained weight change",
        ]

        terms_by_category: dict[str, list[str]] = {
            "oncology": oncology_terms,
            "neurology": neuro_terms,
            "gastrointestinal": gastrointestinal_terms,
            "cardiac": cardiac_terms,
            "respiratory": respiratory_terms,
            "urology": urology_terms,
            "dermatology": dermatology_terms,
            "endocrinology": endocrinology_terms,
        }
        specs_by_category: dict[str, list[str]] = {
            "oncology": [
                "clinical oncology",
                "oncology",
                "cancer specialist",
                "radiotherapy",
                "oncoplastic breast surgery",
                "breast surgery",
                "surgical oncology",
            ],
            "neurology": [
                "neurology",
                "neuromedicine",
                "stroke and neuro-intervention",
                "neurologist",
            ],
            "gastrointestinal": [
                "gastroenterology",
                "hepatobiliary pancreatic surgery",
                "colorectal surgery",
                "gastrointestinal surgery",
            ],
            "cardiac": [
                "cardiology",
                "cardiac surgery",
                "heart specialist",
                "interventional cardiology",
            ],
            "respiratory": ["pulmonology", "pulmonologist", "chest medicine", "general medicine"],
            "urology": [
                "urology",
                "kidney & urology",
                "endourology",
                "nephrology",
            ],
            "dermatology": ["dermatology", "dermatologist", "skin specialist"],
            "endocrinology": ["endocrinology", "endocrinologist", "diabetes specialist"],
        }
        category_priority = {
            "cardiac": 5,
            "neurology": 4,
            "urology": 3,
            "gastrointestinal": 2,
            "oncology": 1,
            "respiratory": 0,
            "endocrinology": 0,
            "dermatology": 0,
        }

        matches_by_category: dict[str, list[str]] = {
            key: self._collect_keyword_hits(context_joined, terms) for key, terms in terms_by_category.items()
        }
        matched_categories = [(key, hits) for key, hits in matches_by_category.items() if hits]
        if matched_categories:
            matched_categories.sort(
                key=lambda item: (len(item[1]), category_priority.get(item[0], 0)),
                reverse=True,
            )
            category, keyword_hits = matched_categories[0]
            recommended_specs = specs_by_category.get(category, recommended_specs)
        elif "chest" in context_joined:
            category = "cardiac"
            recommended_specs = specs_by_category.get("cardiac", ["cardiology", "general physician"])
            keyword_hits.append("chest")

        severe_markers = [
            "severe",
            "sudden",
            "fainting",
            "loss of consciousness",
            "slurred speech",
            "speech difficulty",
            "facial droop",
            "one-sided weakness",
            "seizure",
            "shortness of breath",
            "breathlessness",
            "crushing chest pain",
        ]
        gi_alarm_markers = ["blood in stool", "rectal bleeding", "black stool", "melena"]
        cancer_red_flags = ["breast lump", "breast mass", "tumor", "mass", "unexplained weight loss", "nipple discharge"]
        respiratory_alarm_markers = [
            "breathlessness at rest",
            "shortness of breath at rest",
            "unable to speak full sentences",
            "bluish lips",
            "coughing blood",
        ]
        respiratory_warning_markers = [
            "productive cough",
            "phlegm",
            "sputum",
            "night cough",
            "nocturnal cough",
            "breathlessness",
            "shortness of breath",
            "wheeze",
            "wheezing",
            "chest congestion",
        ]
        respiratory_persistence_markers = [
            "for 7 days",
            "for 10 days",
            "for 14 days",
            "for a week",
            "for one week",
            "for two weeks",
            "for 10 day",
            "persistent",
            "ongoing",
            "recurrent",
            "night",
            "sleep",
            "disrupting sleep",
            "worse at night",
        ]
        urology_alarm_markers = [
            "fever with flank pain",
            "high fever",
            "unable to urinate",
            "very low urine output",
            "anuria",
            "persistent vomiting",
            "uncontrolled pain",
        ]
        urology_warning_markers = [
            "kidney stone",
            "renal calculi",
            "urolithiasis",
            "flank pain",
            "renal colic",
            "hematuria",
            "blood in urine",
            "dysuria",
        ]
        has_severe_marker = self._contains_any(joined, severe_markers)
        has_gi_alarm = self._contains_any(joined, gi_alarm_markers)
        has_cancer_red_flag = self._contains_any(joined, cancer_red_flags)
        has_respiratory_alarm = category == "respiratory" and self._contains_any(joined, respiratory_alarm_markers)
        has_respiratory_warning = category == "respiratory" and self._contains_any(joined, respiratory_warning_markers)
        has_respiratory_persistence = category == "respiratory" and self._contains_any(joined, respiratory_persistence_markers)
        has_urology_alarm = self._contains_any(joined, urology_alarm_markers)
        has_urology_warning = self._contains_any(joined, urology_warning_markers)

        severity = 4
        if "severe" in joined or "sudden" in joined:
            severity = 8
        elif has_respiratory_alarm:
            severity = 8
        elif has_urology_alarm:
            severity = 8
        elif has_gi_alarm or has_cancer_red_flag:
            severity = 6
        elif has_respiratory_warning and (has_respiratory_persistence or "breathlessness" in joined):
            severity = 5
        elif category == "urology" and has_urology_warning:
            severity = 5
        elif any(term in joined for term in ["ongoing or recurrent", "tight", "pressure", "exertion", "palpitation"]):
            severity = 6

        if category == "urology" and has_urology_alarm:
            urgency = "high"
        elif has_respiratory_alarm:
            urgency = "high"
        elif has_severe_marker and category in {"cardiac", "neurology", "respiratory"}:
            urgency = "high"
        elif has_respiratory_warning and has_respiratory_persistence:
            urgency = "moderate"
        elif severity >= 5:
            urgency = "moderate"
        else:
            urgency = "low"

        return self._finalize_symptom_analysis_output(
            {
            "primary_category": category,
            "severity": severity,
            "urgency": urgency,
            "recommended_specializations": recommended_specs,
            "recommended_specializations_canonical": merge_specialties(
                recommended_specs,
                primary_category=category,
                include_fallback=False,
                limit=6,
            ),
            "symptom_descriptions": clean_symptoms,
            "keyword_hits": sorted(set(keyword_hits)),
            "triage_note": "",
            "profile_summary": "",
            "analysis_source": "rules",
            "additional_information": additional_information,
            "additional_information_assessment": "",
            "clinical_impression": "",
            "likely_concerns": [],
            "immediate_actions": [],
            "red_flags_to_watch": [],
            "follow_up_questions": template_follow_up_questions,
            "recommended_next_steps": [],
            "prescription_analysis": {},
            "report_analysis": {},
            }
        , language=normalized_language)

    async def _analyze_symptoms_with_llm(
        self,
        symptoms: list[str],
        medications: list[dict] | None = None,
        diagnosis: str | None = None,
        report_findings: list[dict] | None = None,
        document_summary: str | None = None,
        document_instructions: str | None = None,
        document_warnings: list[str] | None = None,
        doctor_specialization: str | None = None,
        previous_session_context: dict | None = None,
        language: str = "en",
    ) -> dict | None:
        """Analyze symptoms using LLM with enhanced medical prompt."""
        normalized_language = normalize_response_language(language)
        document_context_available = self._has_llm_document_context(
            medications=medications,
            diagnosis=diagnosis,
            report_findings=report_findings,
            document_summary=document_summary,
            document_instructions=document_instructions,
            document_warnings=document_warnings,
            doctor_specialization=doctor_specialization,
        )
        if not symptoms and not document_context_available:
            return None
        started_at = time.monotonic()
        symptom_prompt_input = ", ".join(symptoms) if symptoms else (
            "No direct symptom text was provided. Use only the uploaded diagnosis, medications, "
            "report findings, and treating specialist context for conservative triage."
        )

        # Format medications for AI analysis
        medication_text = ""
        if medications:
            med_summaries = []
            for med in medications[:10]:  # Limit to 10 medications
                name = str(med.get("name") or med.get("medication_name") or "").strip()
                dosage = str(med.get("dosage") or "").strip()
                frequency = str(med.get("frequency") or "").strip()
                duration = str(med.get("duration") or "").strip()

                med_desc = name
                if dosage:
                    med_desc += f" {dosage}"
                if frequency:
                    med_desc += f", {frequency}"
                if duration:
                    med_desc += f", for {duration}"
                med_summaries.append(med_desc)

            medication_text = "; ".join(med_summaries) if med_summaries else ""

        # Build chronic conditions from medications
        chronic_conditions = []
        if medications:
            med_concepts: list[str] = []
            for med in medications:
                med_concepts.extend(
                    medication_concepts(
                        str(med.get("name") or med.get("medication_name") or "").strip(),
                        str(med.get("purpose") or "").strip(),
                    )
                )
            for med_name in med_concepts:
                if med_name in {"metformin", "insulin"}:
                    chronic_conditions.append("diabetes")
                elif med_name in {"amlodipine", "losartan", "cilnidipine", "hydrochlorothiazide"} or "bp" in med_name:
                    chronic_conditions.append("hypertension")

        # Use the enhanced medical prompt
        prev_ctx = previous_session_context or {}
        prompt = get_prompt(
            "symptom_analysis",
            language=normalized_language,
            symptoms=symptom_prompt_input,
            chronic_conditions=", ".join(chronic_conditions) if chronic_conditions else "",
            medications=medication_text,
            diagnosis=diagnosis or "",
            doctor_specialization=doctor_specialization or "",
            document_instructions=document_instructions or "",
            document_warnings=", ".join(self._coerce_string_list(document_warnings)) if document_warnings else "",
            document_summary=document_summary or "",
            report_findings=json.dumps(report_findings or [], ensure_ascii=True, default=str),
            age_group="adult",
            previous_symptoms=prev_ctx.get("previous_symptoms", ""),
            previous_progression=prev_ctx.get("previous_progression", ""),
            days_since_last=prev_ctx.get("days_since_last", ""),
        )
        system_prompt = SYMPTOM_TRIAGE_SYSTEM_PROMPT

        try:
            parsed = await self.llm_client.complete_json(
                prompt=prompt,
                system_prompt=system_prompt,
                language=normalized_language,
            )
        except Exception:
            logger.info(
                "Symptom LLM analysis failed duration_ms=%d symptom_count=%d has_medications=%s has_report_findings=%s",
                int((time.monotonic() - started_at) * 1000),
                len(symptoms),
                bool(medications),
                bool(report_findings),
            )
            return None

        if not isinstance(parsed, dict):
            logger.info(
                "Symptom LLM analysis returned no structured data duration_ms=%d symptom_count=%d",
                int((time.monotonic() - started_at) * 1000),
                len(symptoms),
            )
            return None
        parsed = await self._repair_symptom_analysis_language_if_needed(
            parsed,
            language=normalized_language,
        )

        raw_confidence = clamp_confidence(parsed.get("confidence_score"), default=0.0)
        meaningful_document_analysis = document_context_available and self._llm_analysis_has_meaningful_content(parsed)
        if raw_confidence < 0.35 and not meaningful_document_analysis:
            logger.info(
                "Symptom LLM analysis rejected for low confidence duration_ms=%d symptom_count=%d confidence=%.3f",
                int((time.monotonic() - started_at) * 1000),
                len(symptoms),
                raw_confidence,
            )
            return None
        if raw_confidence < 0.35 and meaningful_document_analysis:
            logger.info(
                "Symptom LLM analysis accepted despite low confidence duration_ms=%d symptom_count=%d confidence=%.3f document_context=%s",
                int((time.monotonic() - started_at) * 1000),
                len(symptoms),
                raw_confidence,
                document_context_available,
            )
        logger.info(
            "Symptom LLM analysis completed duration_ms=%d symptom_count=%d confidence=%.3f",
            int((time.monotonic() - started_at) * 1000),
            len(symptoms),
            raw_confidence,
        )

        allowed_categories = {
            "oncology",
            "neurology",
            "cardiac",
            "gastrointestinal",
            "respiratory",
            "urology",
            "nephrology",
            "dermatology",
            "endocrinology",
            "rheumatology",
            "psychiatry",
            "obstetrics_gynecology",
            "orthopedics",
            "ent",
            "ophthalmology",
            "mental_health",
            "general_medicine",
            "emergency",
            "general",
        }
        primary_category = str(parsed.get("primary_category", "general")).strip().lower()
        if primary_category not in allowed_categories:
            primary_category = "general"
        if primary_category == "nephrology":
            primary_category = "urology"
        if primary_category == "general_medicine":
            primary_category = "general"
        if primary_category == "mental_health":
            primary_category = "psychiatry"

        try:
            severity = int(float(parsed.get("severity", 4)))
        except (TypeError, ValueError):
            severity = 4
        severity = max(1, min(severity, 10))

        urgency = str(parsed.get("urgency", "moderate")).strip().lower()
        urgency_alias = {
            "routine": "low",
            "priority": "moderate",
            "urgent": "moderate",
            "emergency": "high",
        }
        urgency = urgency_alias.get(urgency, urgency)
        if urgency not in {"low", "moderate", "high"}:
            urgency = "moderate" if severity >= 5 else "low"

        recommended_raw = parsed.get("recommended_specializations")
        if isinstance(recommended_raw, list):
            recommended_specializations = [str(item).strip() for item in recommended_raw if str(item).strip()]
        elif isinstance(recommended_raw, str) and recommended_raw.strip():
            recommended_specializations = [recommended_raw.strip()]
        else:
            recommended_specializations = []
        recommended_specializations_canonical = merge_specialties(
            recommended_specializations,
            primary_category=primary_category,
            include_fallback=False,
            limit=6,
        )

        keyword_raw = parsed.get("keyword_hits")
        if isinstance(keyword_raw, list):
            keyword_hits = [str(item).strip().lower() for item in keyword_raw if str(item).strip()]
        elif isinstance(keyword_raw, str) and keyword_raw.strip():
            keyword_hits = [keyword_raw.strip().lower()]
        else:
            keyword_hits = []

        symptom_text = " ".join([str(item).lower() for item in symptoms if str(item).strip()])
        respiratory_signal_terms = [
            "cough",
            "phlegm",
            "sputum",
            "breathlessness",
            "shortness of breath",
            "wheeze",
            "wheezing",
            "night cough",
        ]
        respiratory_persistence_terms = [
            "for 7 days",
            "for 10 days",
            "for a week",
            "for one week",
            "for two weeks",
            "persistent",
            "ongoing",
            "recurrent",
            "night",
            "disrupting sleep",
        ]
        respiratory_override_applied = False
        if (
            (primary_category == "respiratory" or self._contains_any(symptom_text, respiratory_signal_terms))
            and self._contains_any(symptom_text, respiratory_signal_terms)
            and self._contains_any(symptom_text, respiratory_persistence_terms)
        ):
            respiratory_override_applied = True
            primary_category = "respiratory"
            severity = max(severity, 5)
            if urgency == "low":
                urgency = "moderate"
            recommended_specializations_canonical = self._merge_unique_strings(
                ["Pulmonology", "Respiratory Medicine", "Chest Medicine"],
                recommended_specializations_canonical,
                limit=6,
            )

        triage_note = self._clean_generated_text(parsed.get("triage_note"))
        profile_summary = self._clean_generated_text(parsed.get("profile_summary"))
        additional_information_assessment = self._clean_generated_text(
            parsed.get("additional_information_assessment")
        )
        clinical_impression = self._clean_generated_text(parsed.get("clinical_impression"))

        likely_concerns = self._coerce_string_list(
            parsed.get("likely_concerns") or parsed.get("possible_conditions")
        )
        immediate_actions = self._coerce_string_list(
            parsed.get("immediate_actions") or parsed.get("immediate_suggestions")
        )
        red_flags_to_watch = self._coerce_string_list(
            parsed.get("red_flags_to_watch")
            or parsed.get("concerning_things_to_monitor")
            or parsed.get("red_flags")
        )
        follow_up_questions = self._sanitize_question_list(parsed.get("follow_up_questions"))
        recommended_next_steps = self._coerce_string_list(parsed.get("recommended_next_steps"))

        prescription_analysis = (
            parsed.get("prescription_analysis")
            if isinstance(parsed.get("prescription_analysis"), dict)
            else {}
        )
        report_analysis = (
            parsed.get("report_analysis")
            if isinstance(parsed.get("report_analysis"), dict)
            else {}
        )
        report_analysis = self._align_llm_report_analysis_to_source(
            report_analysis,
            report_findings,
        )

        return self._finalize_symptom_analysis_output(
            {
            "primary_category": primary_category,
            "severity": severity,
            "urgency": urgency,
            "recommended_specializations": recommended_specializations,
            "recommended_specializations_canonical": recommended_specializations_canonical,
            "symptom_descriptions": symptoms,
            "keyword_hits": sorted(set(keyword_hits)),
            "triage_note": triage_note,
            "profile_summary": profile_summary,
            "analysis_source": "openai",
            "additional_information_assessment": additional_information_assessment,
            "clinical_impression": clinical_impression,
            "likely_concerns": likely_concerns,
            "immediate_actions": immediate_actions,
            "red_flags_to_watch": red_flags_to_watch,
            "follow_up_questions": follow_up_questions,
            "recommended_next_steps": recommended_next_steps,
            "prescription_analysis": prescription_analysis,
            "report_analysis": report_analysis,
            }
        , language=normalized_language)

    async def _analyze_prescriptions(
        self,
        db: Session,
        prescription_ids: list[str],
        user_id: str | None = None,
    ) -> dict:
        if not prescription_ids:
            return {}

        query = db.query(Prescription).filter(Prescription.id.in_(prescription_ids))
        if user_id:
            query = query.filter(Prescription.user_id == user_id)
        rows = query.all()
        chronic_conditions: set[str] = set()
        recent_diagnoses: list[str] = []
        medication_patterns: set[str] = set()
        previous_specializations: set[str] = set()
        treatment_context: set[str] = set()

        for row in rows:
            parsed = row.parsed_data or {}
            diagnosis = str(parsed.get("diagnosis") or "").strip()
            if diagnosis:
                diagnosis_lower = diagnosis.lower()
                recent_diagnoses.append(diagnosis_lower)
                chronic_conditions.add(diagnosis_lower)

            specialization = str(parsed.get("doctor_specialization") or "").strip()
            if specialization:
                canonical_specs = canonical_specialties([specialization], limit=2)
                if canonical_specs:
                    previous_specializations.update([item.lower() for item in canonical_specs])
                else:
                    previous_specializations.add(specialization.lower())
            instructions = str(parsed.get("instructions") or "").strip()
            if instructions:
                treatment_context.add(instructions.lower())
            follow_up = str(parsed.get("follow_up") or "").strip()
            if follow_up:
                treatment_context.add(follow_up.lower())

            for med in parsed.get("medications") or []:
                if isinstance(med, dict):
                    name = str(med.get("name") or "").strip().lower()
                    purpose = str(med.get("purpose") or "").strip()
                else:
                    name = str(med).strip().lower()
                    purpose = ""
                if not name:
                    continue
                medication_patterns.add(name)

                concepts = medication_concepts(name, purpose)
                for concept in concepts:
                    medication_patterns.add(concept)

                if any(token in concepts for token in {"metformin", "insulin"}):
                    chronic_conditions.add("diabetes")
                if any(token in concepts for token in {"amlodipine", "losartan", "cilnidipine", "hydrochlorothiazide"}):
                    chronic_conditions.add("hypertension")

        medical_history = {
            "chronic_conditions": sorted(chronic_conditions),
            "recent_diagnoses": recent_diagnoses,
            "medication_patterns": sorted(medication_patterns),
            "previous_specializations": sorted(previous_specializations),
            "treatment_context": sorted(treatment_context),
        }
        medical_history["oncology_context"] = self._extract_oncology_context(medical_history)
        medical_history["urology_context"] = self._extract_urology_context(medical_history)
        medical_history["respiratory_context"] = self._extract_respiratory_context(medical_history)
        return medical_history

    async def _get_candidate_doctors(
        self,
        db: Session,
        symptom_analysis: dict,
        medical_history: dict,
        preferences: dict | None,
    ) -> list[Doctor]:
        query = db.query(Doctor)

        if preferences:
            max_fee = preferences.get("max_fee")
            if max_fee is not None:
                query = query.filter(Doctor.consultation_fee <= max_fee)

            language = preferences.get("language")
            if language:
                query = query.filter(Doctor.languages_spoken.isnot(None))

        return query.all()

    async def _score_and_rank(
        self,
        candidates: list[Doctor | PreviewDoctorCandidate],
        symptom_analysis: dict,
        medical_history: dict,
        preferences: dict | None,
        language: str = "en",
        include_llm_reasons: bool = True,
    ) -> list[dict]:
        normalized_language = normalize_response_language(language)
        started_at = time.monotonic()
        scored: list[dict] = []
        for doctor in candidates:
            spec_score = self._calculate_specialization_match(doctor, symptom_analysis)
            continuity_score = self._calculate_continuity_of_care_score(doctor, medical_history)
            urgency_fit_score = self._calculate_urgency_fit_score(doctor, symptom_analysis)
            condition_score = self._calculate_condition_match(doctor, medical_history)
            exp_score = self._calculate_experience_score(doctor)
            avail_score = self._calculate_availability_score(doctor)
            total = (
                (spec_score * 0.45)
                + (continuity_score * 0.2)
                + (urgency_fit_score * 0.12)
                + (condition_score * 0.1)
                + (exp_score * 0.09)
                + (avail_score * 0.04)
            )
            total = min(total, 1.0)
            source_payload = doctor.source_payload if isinstance(doctor, PreviewDoctorCandidate) else {}
            doctor_name = doctor.user.username if doctor.user else "Doctor"
            doctor_id = (
                str(source_payload.get("doctorId") or source_payload.get("doctor_id") or "").strip()
                if source_payload
                else ""
            )
            public_id = source_payload.get("id") if source_payload else None

            scored.append(
                {
                    "id": public_id if public_id is not None else doctor.id,
                    "doctor_id": doctor_id or doctor.id,
                    "doctorId": doctor_id or doctor.id,
                    "name": doctor_name,
                    "specialization": doctor.specialization or [],
                    "hospital_id": doctor.hospital_id,
                    "experience_years": doctor.experience_years or 0,
                    "average_rating": doctor.average_rating or 0.0,
                    "image_url": source_payload.get("image_url"),
                    "imageUrl": source_payload.get("imageUrl"),
                    "imagePath": source_payload.get("imagePath"),
                    "fileMetadata": source_payload.get("fileMetadata"),
                    "avatar": source_payload.get("avatar"),
                    "credentials": source_payload.get("credentials"),
                    "servesFor": source_payload.get("servesFor", []),
                    "about": source_payload.get("about", ""),
                    "education": source_payload.get("education", []),
                    "locations": source_payload.get("locations", []),
                    "hospitalName": source_payload.get("hospitalName"),
                    "hospitalAddress": source_payload.get("hospitalAddress"),
                    "contactNumber": source_payload.get("contactNumber"),
                    "isActive": source_payload.get("isActive"),
                    "match_score": round(float(total), 4),
                    "reasons": self._build_rule_based_doctor_reasons(
                        doctor_specializations=doctor.specialization or [],
                        symptom_analysis=symptom_analysis,
                        match_score=round(float(total), 4),
                        language=normalized_language,
                    ),
                    "fit_summary": "",
                    "details": {
                        "specialization": round(float(spec_score), 4),
                        "continuity_of_care": round(float(continuity_score), 4),
                        "urgency_fit": round(float(urgency_fit_score), 4),
                        "condition_match": round(float(condition_score), 4),
                        "experience": round(float(exp_score), 4),
                        "availability": round(float(avail_score), 4),
                    },
                }
            )

        scored.sort(key=lambda x: x["match_score"], reverse=True)
        top_ranked = scored[:10]
        llm_rationales: dict[str, dict[str, Any]] = {}
        if include_llm_reasons:
            llm_rationales = await self._generate_doctor_rationales_with_llm(
                symptom_analysis=symptom_analysis,
                medical_history=medical_history,
                ranked_doctors=top_ranked,
                language=normalized_language,
            )
        for rank, item in enumerate(top_ranked, start=1):
            item["rank"] = rank
            item["reasoning_source"] = "rules"
            doctor_keys = {
                str(item.get("doctor_id") or "").strip(),
                str(item.get("doctorId") or "").strip(),
                str(item.get("id") or "").strip(),
            }
            rationale = next(
                (
                    payload
                    for doctor_key, payload in llm_rationales.items()
                    if doctor_key and doctor_key in doctor_keys
                ),
                None,
            )
            if rationale:
                reasons = self._sanitize_doctor_reasons(rationale.get("reasons") or [])
                fit_summary = self._sanitize_doctor_fit_summary(
                    str(rationale.get("fit_summary") or "").strip()
                )
                item["reasons"] = reasons
                item["fit_summary"] = fit_summary
                if reasons or fit_summary:
                    item["reasoning_source"] = "openai"
        logger.info(
            "Doctor ranking completed duration_ms=%d candidate_count=%d returned_count=%d",
            int((time.monotonic() - started_at) * 1000),
            len(candidates),
            len(top_ranked),
        )
        return top_ranked

    def _build_rule_based_doctor_reasons(
        self,
        *,
        doctor_specializations: list[str],
        symptom_analysis: dict[str, Any],
        match_score: float,
        language: str = "en",
    ) -> list[str]:
        recommended_specializations = merge_specialties(
            symptom_analysis.get("recommended_specializations_canonical", [])
            or symptom_analysis.get("recommended_specializations", []),
            primary_category=str(symptom_analysis.get("primary_category") or "general"),
            include_fallback=False,
            limit=6,
        )
        doctor_specs = merge_specialties(doctor_specializations or [], limit=6)
        reasons: list[str] = []
        overlap = [spec for spec in doctor_specs if spec in recommended_specializations]
        if overlap:
            reasons.append(
                f"এই বিশেষজ্ঞতা উপসর্গের সাথে মিলে: {overlap[0]}।"
                if self._is_bangla(language)
                else f"Specialty alignment with symptoms: {overlap[0]}."
            )
        urgency = str(symptom_analysis.get("urgency") or "low").strip().lower()
        if urgency in {"moderate", "high"}:
            reasons.append(
                "বর্তমান জরুরিতা অনুযায়ী দ্রুত বিশেষজ্ঞ মূল্যায়ন উপযোগী।"
                if self._is_bangla(language)
                else "Fit for the current urgency and specialist review needs."
            )
        if match_score >= 0.75:
            reasons.append(
                "ম্যাচ স্কোর তুলনামূলকভাবে শক্তিশালী।"
                if self._is_bangla(language)
                else "Rule-based match score is comparatively strong."
            )
        else:
            reasons.append(
                "ম্যাচ স্কোর মাঝারি; প্রেক্ষাপট মিলিয়ে দেখুন।"
                if self._is_bangla(language)
                else "Rule-based match score is moderate; review with context."
            )
        return self._sanitize_doctor_reasons(reasons)[:3]

    async def generate_deferred_doctor_reasoning_updates(
        self,
        *,
        symptom_analysis: dict[str, Any],
        doctors: list[dict[str, Any]],
        language: str = "en",
    ) -> list[dict[str, Any]]:
        if not doctors:
            return []
        llm_rationales = await self._generate_doctor_rationales_with_llm(
            symptom_analysis=symptom_analysis or {},
            medical_history={},
            ranked_doctors=doctors,
            language=normalize_response_language(language),
        )
        if not llm_rationales:
            return []

        updates: list[dict[str, Any]] = []
        for item in doctors:
            doctor_id = str(item.get("doctor_id") or item.get("doctorId") or item.get("id") or "").strip()
            if not doctor_id:
                continue
            rationale = llm_rationales.get(doctor_id)
            if not rationale:
                continue
            reasons = self._sanitize_doctor_reasons(rationale.get("reasons") or [])
            fit_summary = self._sanitize_doctor_fit_summary(str(rationale.get("fit_summary") or "").strip())
            if not reasons and not fit_summary:
                continue
            updates.append(
                {
                    "doctor_id": doctor_id,
                    "reasons": reasons,
                    "fit_summary": fit_summary,
                    "reasoning_source": "openai",
                }
            )
        return updates

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
        normalized_language = normalize_response_language(language)
        prompt = textwrap.dedent(
            f"""\
            Explain this single medical finding in plain language for a patient.
            Keep it to one short sentence.
            Mention what the test generally reflects and what this value usually suggests in context.

            Test: {test_name}
            Observed value: {observed_value or "not provided"}
            Reference range: {reference_range or "not provided"}
            Status: {status}
            Context: {context or ""}
            """
        )
        generated = await self.llm_client.complete(prompt=prompt, language=normalized_language)
        concise = self._condense_generated_text(
            generated,
            fallback="",
            max_sentences=1,
            max_words=24,
        )
        if concise:
            return concise
        if str(status or "").strip().lower() in {"normal", "managed"}:
            return (
                "এই মানটি সাধারণত স্বাভাবিক সীমার মধ্যে থাকে।"
                if self._is_bangla(normalized_language)
                else "This value is generally within expected limits."
            )
        return (
            "এই ফলাফলের জন্য চিকিৎসকের সাথে প্রসঙ্গ মিলিয়ে আলোচনা করুন।"
            if self._is_bangla(normalized_language)
            else "Discuss this finding with your clinician in full context."
        )

    async def _generate_doctor_rationales_with_llm(
        self,
        symptom_analysis: dict,
        medical_history: dict,
        ranked_doctors: list[dict],
        language: str = "en",
    ) -> dict[str, dict]:
        """Generate doctor-specific recommendation rationales using enhanced prompts."""
        if not ranked_doctors:
            return {}
        normalized_language = normalize_response_language(language)

        candidate_payload = []
        for item in ranked_doctors[:6]:
            candidate_payload.append(
                {
                    "doctor_id": item.get("doctor_id"),
                    "name": item.get("name"),
                    "specialization": item.get("specialization", []),
                    "experience_years": item.get("experience_years", 0),
                    "average_rating": item.get("average_rating", 0.0),
                    "match_score": item.get("match_score", 0.0),
                    "current_reasons": item.get("reasons", []),
                }
            )

        # Use the enhanced doctor recommendation prompt
        prompt = get_prompt(
            "doctor_recommendation",
            symptoms=json.dumps(symptom_analysis.get("symptom_descriptions", []), ensure_ascii=True),
            symptom_analysis=json.dumps(symptom_analysis, ensure_ascii=True, default=str),
            medical_history=json.dumps(medical_history or {}, ensure_ascii=True, default=str),
            preferences="",
            doctors=json.dumps(candidate_payload, ensure_ascii=True),
        )

        system_prompt = DOCTOR_RECOMMENDATION_SYSTEM_PROMPT

        try:
            parsed = await self.llm_client.complete_json(
                prompt=prompt,
                system_prompt=system_prompt,
                language=normalized_language,
            )
        except Exception:
            return {}

        if not isinstance(parsed, dict):
            return {}

        recommendations = parsed.get("recommendations")
        if not isinstance(recommendations, list):
            return {}

        result: dict[str, dict] = {}
        for entry in recommendations:
            if not isinstance(entry, dict):
                continue
            doctor_id = str(entry.get("doctor_id") or "").strip()
            if not doctor_id:
                continue

            reasons_raw = entry.get("reasons")
            if isinstance(reasons_raw, list):
                reasons = [str(item).strip() for item in reasons_raw if str(item).strip()]
            elif isinstance(reasons_raw, str) and reasons_raw.strip():
                reasons = [reasons_raw.strip()]
            else:
                reasons = []
            reasons = reasons[:3]

            fit_summary = str(entry.get("fit_summary") or "").strip()
            if not reasons and not fit_summary:
                continue

            result[doctor_id] = {"reasons": reasons, "fit_summary": fit_summary}

        return result

    def _calculate_specialization_match(self, doctor: Doctor, symptom_analysis: dict) -> float:
        doctor_specs = merge_specialties(doctor.specialization or [], limit=6)
        recommended_specs = merge_specialties(
            symptom_analysis.get("recommended_specializations_canonical", [])
            or symptom_analysis.get("recommended_specializations", []),
            primary_category=str(symptom_analysis.get("primary_category") or "general"),
            include_fallback=True,
            limit=6,
        )
        if not recommended_specs:
            return 0.35
        if not doctor_specs:
            return 0.0

        overlap = 0
        for recommended in recommended_specs:
            if any(specialty_matches(recommended, doctor_spec) for doctor_spec in doctor_specs):
                overlap += 1

        base = overlap / max(len(recommended_specs), 1)
        return min(base + 0.2 if overlap else base, 1.0)

    def _calculate_continuity_of_care_score(self, doctor: Doctor, medical_history: dict) -> float:
        previous_specs = merge_specialties(
            (medical_history or {}).get("previous_specializations", []),
            include_fallback=False,
            limit=6,
        )
        if not previous_specs:
            return 0.0

        doctor_specs = merge_specialties(doctor.specialization or [], include_fallback=False, limit=6)
        if not doctor_specs:
            return 0.0

        overlap = sum(
            1 for previous in previous_specs if any(specialty_matches(previous, doctor_spec) for doctor_spec in doctor_specs)
        )
        if not overlap:
            return 0.0
        return min((overlap / max(len(previous_specs), 1)) + 0.15, 1.0)

    def _calculate_urgency_fit_score(self, doctor: Doctor, symptom_analysis: dict) -> float:
        urgency = str(symptom_analysis.get("urgency") or "low").strip().lower()
        has_slots = bool(doctor.available_slots)
        if urgency == "high":
            return 1.0 if has_slots else 0.2
        if urgency == "moderate":
            return 0.85 if has_slots else 0.45
        return 0.7 if has_slots else 0.5

    def _calculate_condition_match(self, doctor: Doctor, medical_history: dict) -> float:
        if not medical_history:
            return 0.5
        patient_conditions = {
            str(item).strip().lower()
            for item in (medical_history.get("chronic_conditions") or [])
            if str(item).strip()
        }
        doctor_conditions = {item.lower() for item in (doctor.conditions_treated or [])}
        if not patient_conditions:
            return 0.5
        intersection = patient_conditions.intersection(doctor_conditions)
        union = patient_conditions.union(doctor_conditions)
        if not union:
            return 0.5
        return len(intersection) / len(union)

    def _merge_external_medical_context(
        self,
        medical_history: dict,
        external_medical_conditions: list[str],
        external_recent_diagnoses: list[str],
    ) -> dict:
        merged = dict(medical_history or {})
        chronic_conditions = {
            str(item).strip().lower()
            for item in (merged.get("chronic_conditions") or [])
            if str(item).strip()
        }
        recent_diagnoses = [str(item).strip().lower() for item in (merged.get("recent_diagnoses") or []) if str(item).strip()]

        for item in external_medical_conditions:
            if str(item).strip():
                chronic_conditions.add(str(item).strip().lower())
        for item in external_recent_diagnoses:
            if str(item).strip():
                recent_diagnoses.append(str(item).strip().lower())
                chronic_conditions.add(str(item).strip().lower())

        merged["chronic_conditions"] = sorted(chronic_conditions)
        merged["recent_diagnoses"] = recent_diagnoses
        merged.setdefault("medication_patterns", [])
        merged.setdefault("previous_specializations", [])
        merged.setdefault("treatment_context", [])
        merged["oncology_context"] = self._extract_oncology_context(merged)
        merged["urology_context"] = self._extract_urology_context(merged)
        merged["respiratory_context"] = self._extract_respiratory_context(merged)
        return merged

    def _apply_medical_context_routing(
        self,
        symptom_analysis: dict[str, Any],
        medical_history: dict[str, Any],
        language: str = "en",
    ) -> dict[str, Any]:
        return dict(symptom_analysis or {})

    def _prioritize_specialty_recommendations(
        self,
        symptom_analysis: dict[str, Any],
        medical_history: dict[str, Any],
        preferred_specializations: list[str] | None = None,
        language: str = "en",
    ) -> dict[str, Any]:
        if not symptom_analysis:
            return symptom_analysis

        updated = dict(symptom_analysis)
        primary_category = str(updated.get("primary_category") or "general").strip().lower()
        previous_specializations = self._coerce_string_list((medical_history or {}).get("previous_specializations"))
        recommended_specializations_canonical = merge_specialties(
            preferred_specializations or [],
            previous_specializations,
            self._coerce_string_list(updated.get("recommended_specializations_canonical"))
            or self._coerce_string_list(updated.get("recommended_specializations")),
            primary_category=primary_category,
            include_fallback=False,
            limit=6,
        )
        updated["recommended_specializations_canonical"] = recommended_specializations_canonical
        if not self._is_bangla(language):
            updated["recommended_specializations"] = recommended_specializations_canonical

        return self._finalize_symptom_analysis_output(updated, language=language)

    def _finalize_symptom_analysis_output(self, analysis: dict[str, Any], language: str = "en") -> dict[str, Any]:
        updated = dict(analysis or {})
        primary_category = str(updated.get("primary_category") or "general").strip().lower()
        try:
            severity_value = int(float(updated.get("severity", 4)))
        except (TypeError, ValueError):
            severity_value = 4
        severity_value = max(1, min(severity_value, 10))
        updated["severity"] = severity_value

        recommended_specializations = self._merge_unique_strings(
            self._coerce_string_list(updated.get("recommended_specializations")),
            limit=6,
        )
        recommended_specializations_canonical = merge_specialties(
            self._coerce_string_list(updated.get("recommended_specializations_canonical"))
            or recommended_specializations,
            primary_category=primary_category,
            include_fallback=False,
            limit=6,
        )
        updated["recommended_specializations"] = (
            recommended_specializations
            if self._is_bangla(language)
            else recommended_specializations_canonical
        )
        updated["recommended_specializations_canonical"] = recommended_specializations_canonical

        updated["triage_note"] = self._condense_generated_text(
            updated.get("triage_note"),
            fallback="",
            max_sentences=2,
            max_words=30,
        )
        updated["profile_summary"] = self._condense_generated_text(
            updated.get("profile_summary"),
            fallback="",
            max_sentences=2,
            max_words=30,
        )
        updated["clinical_impression"] = self._condense_generated_text(
            updated.get("clinical_impression"),
            fallback="",
            max_sentences=2,
            max_words=34,
        )
        updated["likely_concerns"] = self._sanitize_short_list(
            updated.get("likely_concerns"),
            max_items=6,
            max_words=10,
        )
        updated["immediate_actions"] = self._sanitize_short_list(
            updated.get("immediate_actions"),
            max_items=5,
            max_words=22,
        )
        updated["red_flags_to_watch"] = self._sanitize_short_list(
            updated.get("red_flags_to_watch"),
            max_items=6,
            max_words=22,
        )
        updated["recommended_next_steps"] = self._sanitize_short_list(
            updated.get("recommended_next_steps"),
            max_items=5,
            max_words=22,
        )
        updated["follow_up_questions"] = self._sanitize_question_list(
            updated.get("follow_up_questions")
        )
        updated["prescription_analysis"] = self._sanitize_prescription_analysis(
            updated.get("prescription_analysis"),
            language=language,
        )
        updated["report_analysis"] = self._sanitize_report_analysis(
            updated.get("report_analysis"),
            language=language,
        )
        return updated

    def _sanitize_prescription_analysis(self, value: Any, language: str = "en") -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        breakdown: list[dict[str, Any]] = []
        for item in payload.get("medication_breakdown") or []:
            if not isinstance(item, dict):
                continue
            medication_name = self._clean_generated_text(item.get("medication_name"))
            if not medication_name:
                continue
            generic_name = self._clean_generated_text(item.get("generic_name")) or None
            drug_class = self._clean_generated_text(item.get("drug_class")) or None
            condition_treated = self._clean_generated_text(item.get("condition_treated")) or None
            why_prescribed = self._condense_generated_text(
                item.get("why_prescribed"),
                fallback="",
                max_sentences=1,
                max_words=12,
            ) or None
            how_it_works = self._condense_generated_text(
                item.get("how_it_works"),
                fallback="",
                max_sentences=1,
                max_words=10,
            ) or None
            key_instructions = self._condense_generated_text(
                item.get("key_instructions"),
                fallback="",
                max_sentences=1,
                max_words=10,
            ) or None
            things_to_know = self._sanitize_short_list(
                item.get("things_to_know"),
                max_items=2,
                max_words=10,
            )
            suggested_for = self._build_medication_suggested_for(
                suggested_for=item.get("suggested_for"),
                condition_treated=condition_treated,
                why_prescribed=why_prescribed,
                ai_analysis=item.get("ai_analysis"),
                language=language,
            )
            breakdown.append(
                {
                    **item,
                    "medication_name": medication_name,
                    "generic_name": generic_name,
                    "drug_class": drug_class,
                    "condition_treated": condition_treated,
                    "why_prescribed": why_prescribed,
                    "how_it_works": how_it_works,
                    "key_instructions": key_instructions,
                    "things_to_know": things_to_know,
                    "suggested_for": suggested_for,
                    # Keep compatibility field while returning minimal text.
                    "ai_analysis": suggested_for,
                }
            )
            if len(breakdown) >= 10:
                break

        interaction_alerts: list[dict[str, Any]] = []
        for alert in payload.get("interaction_alerts") or []:
            if not isinstance(alert, dict):
                continue
            severity = str(alert.get("severity") or "").strip().lower()
            if severity not in {"major", "moderate", "minor"}:
                severity = "moderate"
            drugs = self._coerce_string_list(alert.get("drugs"))[:2]
            note = self._condense_generated_text(
                alert.get("alert"),
                fallback="",
                max_sentences=2,
                max_words=28,
            )
            action = self._condense_generated_text(
                alert.get("action"),
                fallback="",
                max_sentences=2,
                max_words=24,
            )
            if not drugs and not note and not action:
                continue
            interaction_alerts.append(
                {
                    "drugs": drugs,
                    "severity": severity,
                    "alert": note or None,
                    "action": action or None,
                }
            )
            if len(interaction_alerts) >= 6:
                break

        contraindication_flags = self._sanitize_short_list(
            payload.get("contraindication_flags"),
            max_items=8,
            max_words=20,
        )
        overall_assessment = self._condense_generated_text(
            payload.get("overall_assessment"),
            fallback="",
            max_sentences=2,
            max_words=40,
        )
        return {
            "medication_breakdown": breakdown,
            "overall_assessment": overall_assessment or None,
            "interaction_alerts": interaction_alerts,
            "contraindication_flags": contraindication_flags,
        }

    def _build_medication_suggested_for(
        self,
        *,
        suggested_for: Any,
        condition_treated: str | None,
        why_prescribed: str | None,
        ai_analysis: Any,
        language: str = "en",
    ) -> str:
        candidate = (
            self._clean_generated_text(suggested_for)
            or self._clean_generated_text(condition_treated)
            or self._clean_generated_text(why_prescribed)
            or self._clean_generated_text(ai_analysis)
        )
        fallback = (
            "প্রধান উপসর্গ বা অবস্থার নিয়ন্ত্রণে।"
            if self._is_bangla(language)
            else "For the primary symptom or condition."
        )
        condensed = self._condense_generated_text(
            candidate,
            fallback=fallback,
            max_sentences=1,
            max_words=8,
        )
        return self._trim_to_words(condensed, max_words=8)

    @staticmethod
    def _trim_to_words(value: str, *, max_words: int) -> str:
        text = str(value or "").replace("\n", " ").strip()
        if not text:
            return ""
        words = text.split()
        if len(words) <= max_words:
            return text
        trimmed = " ".join(words[:max_words]).rstrip(" ,;:.")
        return f"{trimmed}."

    def _sanitize_report_analysis(self, value: Any, language: str = "en") -> dict[str, Any]:
        payload = value if isinstance(value, dict) else {}
        lab_findings: list[dict[str, Any]] = []
        for item in payload.get("lab_findings") or []:
            if not isinstance(item, dict):
                continue
            test_name = normalize_report_test_name(str(item.get("test_name") or "").strip())
            if not test_name:
                continue
            observed_value = str(item.get("observed_value") or "").strip() or None
            reference_range = str(item.get("reference_range") or "").strip() or None
            status = str(item.get("status") or "unknown").strip().lower() or "unknown"
            lab_findings.append(
                {
                    **item,
                    "test_name": test_name,
                    "observed_value": observed_value,
                    "reference_range": reference_range,
                    "status": status,
                    "ai_analysis": self._sanitize_report_finding_analysis(
                        item.get("ai_analysis"),
                        test_name=test_name,
                        observed_value=observed_value,
                        reference_range=reference_range,
                        status=status,
                        language=language,
                    ),
                }
            )
            if len(lab_findings) >= 12:
                break

        overall_assessment = self._condense_generated_text(
            payload.get("overall_assessment"),
            fallback="",
            max_sentences=2,
            max_words=40,
        )
        patient_action_summary = self._sanitize_short_list(
            payload.get("patient_action_summary"),
            max_items=3,
            max_words=20,
        )
        noteworthy_findings = [
            finding
            for finding in lab_findings
            if self._is_report_status_noteworthy(finding.get("status"))
        ]
        if not overall_assessment:
            fallback_summary_parts = [
                finding.get("ai_analysis")
                for finding in (noteworthy_findings or lab_findings)
                if str(finding.get("ai_analysis") or "").strip()
            ]
            if fallback_summary_parts:
                overall_assessment = self._condense_generated_text(
                    " ".join(fallback_summary_parts[:2]),
                    fallback="",
                    max_sentences=2,
                    max_words=40,
                )
        return {
            "lab_findings": lab_findings,
            "overall_assessment": overall_assessment or None,
            "patient_action_summary": patient_action_summary,
            "noteworthy_findings": noteworthy_findings,
        }

    def _sanitize_report_finding_analysis(
        self,
        value: Any,
        *,
        test_name: str,
        observed_value: str | None,
        reference_range: str | None,
        status: str,
        language: str = "en",
    ) -> str:
        if not self._is_report_status_noteworthy(status):
            return ""
        normalized_test_name = normalize_report_test_name(test_name)
        condensed = self._condense_generated_text(
            value,
            fallback="",
            max_sentences=2,
            max_words=32,
        )
        if is_low_value_report_analysis(condensed, normalized_test_name):
            return ""
        return condensed

    @staticmethod
    def _is_report_status_noteworthy(status: Any) -> bool:
        normalized = str(status or "").strip().lower()
        return normalized in {"borderline", "abnormal", "critical"}

    def _apply_urology_context_routing(
        self,
        symptom_analysis: dict[str, Any],
        medical_history: dict[str, Any],
        language: str = "en",
    ) -> dict[str, Any]:
        """
        Apply urology context routing to symptom analysis.
        LLM should generate all localized content - this only provides clinical context.
        """
        if not symptom_analysis:
            return symptom_analysis

        updated = dict(symptom_analysis)
        current_category = str(updated.get("primary_category") or "").strip().lower()
        if current_category == "oncology" or bool(updated.get("oncology_escalation_applied")):
            return updated

        urology_context = self._extract_urology_context(medical_history or {})
        if not urology_context.get("has_urology_context"):
            return updated

        symptom_text_parts = self._coerce_string_list(updated.get("symptom_descriptions")) + self._coerce_string_list(
            updated.get("keyword_hits")
        )
        symptom_text = " ".join([part.lower() for part in symptom_text_parts if str(part).strip()])
        urology_symptom_terms = [
            "kidney stone",
            "renal calculi",
            "urolithiasis",
            "flank pain",
            "renal colic",
            "hematuria",
            "blood in urine",
            "dysuria",
            "unable to urinate",
        ]

        if current_category not in {"general", "urology"} and not self._contains_any(symptom_text, urology_symptom_terms):
            return updated

        emergency_markers = [
            "fever with flank pain",
            "high fever",
            "unable to urinate",
            "very low urine output",
            "anuria",
            "persistent vomiting",
            "uncontrolled pain",
            "severe flank pain",
        ]
        urgent_markers = [
            "flank pain",
            "renal colic",
            "hematuria",
            "blood in urine",
            "painful urination",
            "dysuria",
            "nausea",
            "vomiting",
        ]
        has_emergency_marker = self._contains_any(symptom_text, emergency_markers)
        has_urgent_marker = has_emergency_marker or self._contains_any(symptom_text, urgent_markers)

        try:
            current_severity = int(float(updated.get("severity", 4)))
        except (TypeError, ValueError):
            current_severity = 4
        minimum_severity = 8 if has_emergency_marker else 5 if has_urgent_marker else 4
        severity = max(1, min(max(current_severity, minimum_severity), 10))

        urgency_rank = {"low": 1, "moderate": 2, "high": 3}
        current_urgency = str(updated.get("urgency") or "low").strip().lower()
        current_urgency = {"routine": "low", "urgent": "moderate", "emergency": "high"}.get(
            current_urgency,
            current_urgency,
        )
        if current_urgency not in urgency_rank:
            current_urgency = "moderate" if severity >= 5 else "low"
        minimum_urgency = "high" if has_emergency_marker else "moderate" if has_urgent_marker else "low"
        urgency = current_urgency
        if urgency_rank[urgency] < urgency_rank[minimum_urgency]:
            urgency = minimum_urgency

        existing_specs = self._coerce_string_list(updated.get("recommended_specializations"))
        forced_specs = ["urology", "kidney & urology", "endourology", "nephrology"]
        recommended_specializations = self._merge_unique_strings(forced_specs, existing_specs, limit=6)

        existing_keywords = self._coerce_string_list(updated.get("keyword_hits"))
        context_terms = self._coerce_string_list(urology_context.get("matched_terms"))
        keyword_hits = self._merge_unique_strings(existing_keywords, context_terms, limit=12)

        if urgency == "high":
            triage_note = (
                "Possible complicated kidney-stone or urinary obstruction pattern. "
                "Seek emergency care now and request urgent urology evaluation."
            )
        elif urgency == "moderate":
            triage_note = (
                "Kidney-stone/urinary tract pattern suggests early urology review within 24 to 72 hours."
            )
        else:
            triage_note = (
                "Known kidney-stone history should be followed up in outpatient urology for reassessment and prevention."
            )
        triage_note = self._ensure_triage_note_mentions_specialist(
            triage_note=triage_note,
            primary_category="urology",
            recommended_specializations=recommended_specializations,
            urgency=urgency,
            language=language,
        )

        urology_actions = [
            "Bring prior prescription and available ultrasound/CT KUB reports to the urology visit.",
            "Track pain episodes, urine output, fever, vomiting, and visible blood in urine before consultation.",
            "Maintain hydration unless your clinician advised fluid restriction.",
        ]
        if urgency == "high":
            urology_actions.insert(0, "Arrange same-day emergency or urgent in-person evaluation.")
        elif urgency == "moderate":
            urology_actions.insert(0, "Book urology consultation within 24 to 72 hours.")
        else:
            urology_actions.insert(0, "Arrange routine outpatient urology follow-up.")

        urology_red_flags = [
            "Fever/chills with flank pain or burning urination.",
            "Unable to pass urine, very low urine output, or worsening one-sided back/flank pain.",
            "Persistent vomiting, dehydration, or visible blood in urine with worsening pain.",
        ]
        urology_next_steps = [
            (
                "Use emergency services now for fever with flank pain, uncontrolled pain, persistent vomiting, or inability to pass urine."
                if urgency == "high"
                else (
                    "Arrange urology specialist consultation within 24 to 72 hours."
                    if urgency == "moderate"
                    else "Arrange routine urology outpatient follow-up."
                )
            ),
            "Bring prior imaging (USG/CT KUB), urinalysis reports, and medication list for specialist review.",
            "Consider nephrology co-management if stones recur frequently or kidney function is reduced.",
        ]
        urology_next_steps = self._ensure_next_steps_include_specialist(
            steps=urology_next_steps,
            recommended_specializations=recommended_specializations,
            language=language,
        )

        updated["primary_category"] = "urology"
        updated["severity"] = severity
        updated["urgency"] = urgency
        updated["recommended_specializations"] = recommended_specializations
        updated["keyword_hits"] = keyword_hits
        updated["triage_note"] = triage_note
        updated["profile_summary"] = (
            f"Prescription context suggests urology follow-up with {urgency} urgency and severity {severity}/10."
        )
        updated["clinical_impression"] = self._merge_contextual_clinical_impression(
            updated.get("clinical_impression"),
            (
                "Medical history indicates kidney-stone/urology context requiring targeted specialist review. "
                f"Current triage priority is {urgency} with severity {severity}/10."
            ),
            language=language,
        )
        updated["immediate_actions"] = self._merge_unique_strings(
            urology_actions,
            self._coerce_string_list(updated.get("immediate_actions")),
            limit=6,
        )
        updated["red_flags_to_watch"] = self._merge_unique_strings(
            urology_red_flags,
            self._coerce_string_list(updated.get("red_flags_to_watch")),
            limit=6,
        )
        updated["recommended_next_steps"] = self._merge_unique_strings(
            urology_next_steps,
            self._coerce_string_list(updated.get("recommended_next_steps")),
            limit=6,
        )
        updated["urology_context_applied"] = True
        updated["urology_context"] = urology_context
        return updated

    def _apply_respiratory_context_routing(
        self,
        symptom_analysis: dict[str, Any],
        medical_history: dict[str, Any],
        language: str = "en",
    ) -> dict[str, Any]:
        """
        Apply respiratory context routing to symptom analysis.
        LLM should generate all localized content - this only provides clinical context.
        """
        if not symptom_analysis:
            return symptom_analysis

        updated = dict(symptom_analysis)
        current_category = str(updated.get("primary_category") or "").strip().lower()
        if current_category == "oncology" or bool(updated.get("oncology_escalation_applied")):
            return updated
        if bool(updated.get("urology_context_applied")):
            return updated

        respiratory_context = self._extract_respiratory_context(medical_history or {})
        if not respiratory_context.get("has_respiratory_context"):
            return updated

        symptom_text_parts = self._coerce_string_list(updated.get("symptom_descriptions")) + self._coerce_string_list(
            updated.get("keyword_hits")
        )
        symptom_text = " ".join([part.lower() for part in symptom_text_parts if str(part).strip()])
        respiratory_symptom_terms = [
            "cough",
            "phlegm",
            "sputum",
            "night cough",
            "nocturnal cough",
            "breathlessness",
            "shortness of breath",
            "wheeze",
            "wheezing",
            "chest congestion",
            "productive cough",
        ]
        has_respiratory_symptom = self._contains_any(symptom_text, respiratory_symptom_terms) or bool(
            respiratory_context.get("has_active_respiratory_diagnosis")
        )
        if current_category not in {"general", "respiratory"} and not has_respiratory_symptom:
            return updated
        if not has_respiratory_symptom:
            return updated

        respiratory_persistence_terms = [
            "for 7 days",
            "for 10 days",
            "for a week",
            "for one week",
            "for two weeks",
            "persistent",
            "ongoing",
            "recurrent",
            "night",
            "sleep",
            "disrupting sleep",
        ]
        respiratory_breath_terms = [
            "breathlessness",
            "shortness of breath",
            "dyspnea",
            "wheeze",
            "wheezing",
        ]
        respiratory_high_risk_terms = [
            "breathlessness at rest",
            "shortness of breath at rest",
            "unable to speak full sentences",
            "bluish lips",
            "coughing blood",
            "oxygen saturation",
        ]
        has_persistent_pattern = self._contains_any(symptom_text, respiratory_persistence_terms)
        has_breath_pattern = self._contains_any(symptom_text, respiratory_breath_terms)
        has_high_risk_pattern = self._contains_any(symptom_text, respiratory_high_risk_terms)

        try:
            current_severity = int(float(updated.get("severity", 4)))
        except (TypeError, ValueError):
            current_severity = 4
        minimum_severity = (
            7 if has_high_risk_pattern else 6 if (has_breath_pattern and has_persistent_pattern) else 5
        )
        severity = max(1, min(max(current_severity, minimum_severity), 10))

        urgency_rank = {"low": 1, "moderate": 2, "high": 3}
        current_urgency = str(updated.get("urgency") or "low").strip().lower()
        current_urgency = {"routine": "low", "urgent": "moderate", "emergency": "high"}.get(
            current_urgency,
            current_urgency,
        )
        if current_urgency not in urgency_rank:
            current_urgency = "moderate" if severity >= 5 else "low"
        minimum_urgency = "high" if has_high_risk_pattern else "moderate"
        urgency = current_urgency
        if urgency_rank[urgency] < urgency_rank[minimum_urgency]:
            urgency = minimum_urgency

        existing_specs = self._coerce_string_list(updated.get("recommended_specializations"))

        # NUANCED SPECIALTY RECOMMENDATION BASED ON RESPIRATORY CONTEXT:
        # 1. Simple acute infection without chronic disease + no persistence/breath issues:
        #    -> Include General Physician (continuity) + Pulmonologist (specialist option)
        # 2. Chronic respiratory disease OR persistent symptoms OR breath issues:
        #    -> Prioritize pulmonology specialties
        # 3. High-risk symptoms: -> Emergency/urgent care (already handled above)

        has_chronic_airway_disease = respiratory_context.get("has_chronic_airway_disease", False)
        is_simple_acute_case = (
            not has_chronic_airway_disease
            and not has_persistent_pattern
            and not has_breath_pattern
            and not has_high_risk_pattern
        )

        if is_simple_acute_case:
            # For simple acute respiratory infections, include both GP and Pulmonologist
            # This allows continuity with treating doctor while offering specialist option
            forced_specs = ["general physician", "general medicine", "pulmonologist", "respiratory medicine"]
        else:
            # For chronic disease, persistent symptoms, or breathing issues: prioritize pulmonology
            forced_specs = ["pulmonology", "pulmonologist", "respiratory medicine", "chest medicine"]
            if has_chronic_airway_disease:
                forced_specs.append("allergy and immunology")

        recommended_specializations = self._merge_unique_strings(forced_specs, existing_specs, limit=6)

        existing_keywords = self._coerce_string_list(updated.get("keyword_hits"))
        context_terms = self._coerce_string_list(respiratory_context.get("matched_terms"))
        keyword_hits = self._merge_unique_strings(existing_keywords, context_terms, limit=12)

        if urgency == "high":
            triage_note = (
                "Respiratory warning signs require urgent in-person assessment; seek emergency care now for worsening breathlessness."
            )
        elif is_simple_acute_case:
            triage_note = (
                "Acute respiratory infection with bacterial markers. Follow up with your treating doctor "
                "to monitor response to antibiotics. Consider pulmonology referral if symptoms worsen or persist beyond 5-7 days."
            )
        else:
            triage_note = (
                "Persistent respiratory symptoms with airway-disease context should be reviewed by pulmonology within 24 to 72 hours."
            )
        triage_note = self._ensure_triage_note_mentions_specialist(
            triage_note=triage_note,
            primary_category="respiratory",
            recommended_specializations=recommended_specializations,
            urgency=urgency,
            language=language,
        )

        respiratory_actions = [
            "Track cough frequency, sputum/phlegm amount, breathlessness triggers, and nighttime sleep disturbance.",
            "Bring current medications, recent lab reports, and prescription history to your follow-up visit.",
            "Avoid smoke and respiratory irritants until assessed.",
        ]
        if urgency == "high":
            respiratory_actions.insert(0, "Arrange same-day emergency or urgent in-person respiratory assessment.")
        elif is_simple_acute_case:
            respiratory_actions.insert(0, "Follow up with your treating doctor within 3-5 days to monitor response to treatment.")
        else:
            respiratory_actions.insert(0, "Book pulmonology consultation within 24 to 72 hours.")

        respiratory_red_flags = [
            "Breathlessness at rest, bluish lips, inability to speak full sentences, or confusion.",
            "Coughing blood, persistent fever, chest pain, or rapidly worsening wheeze.",
            "Low oxygen saturation, severe fatigue, or dehydration due to poor oral intake.",
        ]
        if urgency == "high":
            next_step_action = (
                "Use emergency services now for severe breathlessness, cyanosis, confusion, or coughing blood."
            )
        elif is_simple_acute_case:
            next_step_action = (
                "Follow up with your treating doctor in 3-5 days. Seek pulmonology referral if symptoms worsen or persist beyond one week."
            )
        else:
            next_step_action = (
                "Arrange pulmonology specialist consultation within 24 to 72 hours."
            )

        respiratory_next_steps = [next_step_action]

        if not is_simple_acute_case:
            # Only include inhaler/airway plan steps for chronic/persistent cases
            respiratory_next_steps.extend([
                "Review inhaler technique and asthma/airway-control plan with the specialist.",
                "If recurrent episodes continue, assess long-term airway management and trigger prevention.",
            ])
        else:
            # For simple acute cases, focus on monitoring
            respiratory_next_steps.extend([
                "Complete the full course of prescribed antibiotics as directed.",
                "Monitor for worsening symptoms: high fever, difficulty breathing, or chest pain.",
            ])

        respiratory_next_steps = self._ensure_next_steps_include_specialist(
            steps=respiratory_next_steps,
            recommended_specializations=recommended_specializations,
            language=language,
        )

        updated["primary_category"] = "respiratory"
        updated["severity"] = severity
        updated["urgency"] = urgency
        updated["recommended_specializations"] = recommended_specializations
        updated["keyword_hits"] = keyword_hits
        updated["triage_note"] = triage_note

        # Nuanced profile summary based on case type
        if is_simple_acute_case:
            updated["profile_summary"] = (
                f"Acute respiratory infection (bacterial pattern) with {urgency} priority and severity {severity}/10. "
                "Responding to antibiotics; monitor for symptom improvement."
            )
        else:
            updated["profile_summary"] = (
                f"Respiratory context escalation applied with {urgency} urgency and severity {severity}/10."
            )

        # Nuanced clinical impression based on case type
        if is_simple_acute_case:
            clinical_context = (
                "Acute respiratory infection with elevated inflammatory markers (WBC, neutrophils) indicating bacterial etiology. "
                "Current antibiotic treatment appears appropriate. Recommended approach: follow up with treating doctor "
                "to monitor treatment response; consider pulmonology referral if symptoms worsen or persist beyond one week. "
                f"Current priority is {urgency} with severity {severity}/10."
            )
        else:
            clinical_context = (
                "Medical context and symptom pattern indicate active respiratory concerns requiring pulmonology-focused triage. "
                f"Current priority is {urgency} with severity {severity}/10."
            )

        updated["clinical_impression"] = self._merge_contextual_clinical_impression(
            updated.get("clinical_impression"),
            clinical_context,
            language=language,
        )
        updated["immediate_actions"] = self._merge_unique_strings(
            respiratory_actions,
            self._coerce_string_list(updated.get("immediate_actions")),
            limit=6,
        )
        updated["red_flags_to_watch"] = self._merge_unique_strings(
            respiratory_red_flags,
            self._coerce_string_list(updated.get("red_flags_to_watch")),
            limit=6,
        )
        updated["recommended_next_steps"] = self._merge_unique_strings(
            respiratory_next_steps,
            self._coerce_string_list(updated.get("recommended_next_steps")),
            limit=6,
        )
        updated["respiratory_context_applied"] = True
        updated["respiratory_context"] = respiratory_context
        return updated

    def _apply_oncology_context_escalation(
        self,
        symptom_analysis: dict[str, Any],
        medical_history: dict[str, Any],
        language: str = "en",
    ) -> dict[str, Any]:
        """
        Apply oncology context escalation to symptom analysis.
        LLM should generate all localized content - this only provides clinical context.
        """
        if not symptom_analysis:
            return symptom_analysis

        oncology_context = self._extract_oncology_context(medical_history or {})
        if not oncology_context.get("has_oncology_context"):
            return symptom_analysis

        updated = dict(symptom_analysis)
        has_advanced = bool(oncology_context.get("has_advanced_cancer"))
        has_palliative = bool(oncology_context.get("has_palliative_intent"))
        has_active_chemo = bool(oncology_context.get("has_active_chemotherapy"))

        try:
            current_severity = int(float(updated.get("severity", 4)))
        except (TypeError, ValueError):
            current_severity = 4
        minimum_severity = 9 if (has_advanced or has_palliative or has_active_chemo) else 7
        severity = max(1, min(max(current_severity, minimum_severity), 10))

        urgency_rank = {"low": 1, "moderate": 2, "high": 3}
        current_urgency = str(updated.get("urgency") or "low").strip().lower()
        if current_urgency not in urgency_rank:
            current_urgency = "low"
        minimum_urgency = "high" if (has_advanced or has_palliative or has_active_chemo) else "moderate"
        urgency = current_urgency
        if urgency_rank[urgency] < urgency_rank[minimum_urgency]:
            urgency = minimum_urgency

        context_terms = self._coerce_string_list(oncology_context.get("matched_terms"))
        existing_keywords = self._coerce_string_list(updated.get("keyword_hits"))
        keyword_hits = self._merge_unique_strings(existing_keywords, context_terms, limit=12)

        existing_specs = self._coerce_string_list(updated.get("recommended_specializations"))
        forced_specs = ["clinical oncology", "oncology", "medical oncology"]
        if has_palliative:
            forced_specs.append("palliative care")
        recommended_specializations = self._merge_unique_strings(forced_specs, existing_specs, limit=6)

        context_labels: list[str] = []
        if has_advanced:
            context_labels.append("advanced/metastatic disease")
        if has_palliative:
            context_labels.append("palliative-intent treatment")
        if has_active_chemo:
            context_labels.append("active chemotherapy regimen")
        context_text = (
            ", ".join(context_labels)
            if context_labels
            else "active oncology context"
        )

        if urgency == "high":
            triage_note = (
                f"Urgent oncology-led review is advised due to {context_text}. "
                "Contact the treating oncology team today; seek emergency care now for fever "
                ">=100.4F (38C), breathing distress, bleeding, confusion, or uncontrolled vomiting."
            )
        else:
            triage_note = (
                f"Prompt oncology follow-up is advised due to {context_text}. "
                "Arrange specialist review within 24 to 72 hours and escalate immediately for any red-flag symptoms."
            )
        triage_note = self._ensure_triage_note_mentions_specialist(
            triage_note=triage_note,
            primary_category="oncology",
            recommended_specializations=recommended_specializations,
            urgency=urgency,
            language=language,
        )

        oncology_actions = [
            "Contact the treating oncologist/chemotherapy unit for same-day treatment-context review.",
            "Carry current prescription, regimen schedule, and latest reports to the oncology visit.",
        ]
        if has_active_chemo:
            oncology_actions.append(
                "If temperature reaches >=100.4F (38C) during or after chemotherapy, seek emergency care immediately."
            )
        if has_palliative:
            oncology_actions.append(
                "Coordinate symptom-control plan with oncology and palliative-care teams for pain, nausea, and fatigue."
            )

        oncology_red_flags = [
            "Fever >=100.4F (38C), chills, or signs of infection during/after chemotherapy.",
            "Uncontrolled vomiting/diarrhea, dehydration, or inability to keep fluids down.",
            "New bleeding, severe breathlessness, chest pain, confusion, or sudden weakness.",
        ]
        oncology_next_steps = [
            "Prioritize oncology specialist assessment within 24 hours.",
            "Ensure treating oncologist reviews active regimen, cycle timing, and adverse-effect risk.",
            "Use emergency services immediately for infection signs, respiratory distress, or acute deterioration.",
        ]
        oncology_next_steps = self._ensure_next_steps_include_specialist(
            steps=oncology_next_steps,
            recommended_specializations=recommended_specializations,
            language=language,
        )

        updated["primary_category"] = "oncology"
        updated["severity"] = severity
        updated["urgency"] = urgency
        updated["recommended_specializations"] = recommended_specializations
        updated["keyword_hits"] = keyword_hits
        updated["triage_note"] = triage_note
        updated["profile_summary"] = (
            f"Oncology escalation applied from prescription context ({context_text}) "
            f"with {urgency} urgency and severity {severity}/10."
        )
        updated["clinical_impression"] = self._merge_contextual_clinical_impression(
            updated.get("clinical_impression"),
            (
                f"Prescription context indicates {context_text}. "
                f"This profile requires oncology-centered assessment with {urgency} urgency (severity {severity}/10). "
                "Triage has been escalated beyond routine outpatient symptom sorting."
            ),
            language=language,
        )
        updated["immediate_actions"] = self._merge_unique_strings(
            oncology_actions,
            self._coerce_string_list(updated.get("immediate_actions")),
            limit=6,
        )
        updated["red_flags_to_watch"] = self._merge_unique_strings(
            oncology_red_flags,
            self._coerce_string_list(updated.get("red_flags_to_watch")),
            limit=6,
        )
        updated["recommended_next_steps"] = self._merge_unique_strings(
            oncology_next_steps,
            self._coerce_string_list(updated.get("recommended_next_steps")),
            limit=6,
        )
        updated["oncology_escalation_applied"] = True
        updated["oncology_context"] = oncology_context
        return updated

    def _extract_oncology_context(self, medical_history: dict[str, Any]) -> dict[str, Any]:
        context_parts: list[str] = []
        for key in [
            "chronic_conditions",
            "recent_diagnoses",
            "medication_patterns",
            "previous_specializations",
            "treatment_context",
        ]:
            context_parts.extend(
                [str(item).strip().lower() for item in self._coerce_string_list(medical_history.get(key)) if str(item).strip()]
            )
        context_text = " ".join(context_parts)

        oncology_terms = [
            "cancer",
            "oncology",
            "carcinoma",
            "adenocarcinoma",
            "malignancy",
            "neoplasm",
            "tumor",
        ]
        advanced_terms = [
            "metastatic",
            "metastasis",
            "stage iv",
            "stage 4",
            "advanced stage",
            "terminal",
            "end stage",
        ]
        palliative_terms = [
            "palliative",
            "best supportive care",
            "not curative",
            "non curative",
        ]
        chemotherapy_terms = [
            "chemotherapy",
            "chemo",
            "folfox",
            "folfiri",
            "folfirinox",
            "gemcitabine",
            "cisplatin",
            "carboplatin",
            "oxaliplatin",
            "paclitaxel",
            "docetaxel",
            "capecitabine",
            "immunotherapy",
        ]

        has_advanced = self._contains_any(context_text, advanced_terms)
        has_palliative = self._contains_any(context_text, palliative_terms)
        has_active_chemo = self._contains_any(context_text, chemotherapy_terms)
        has_oncology = (
            self._contains_any(context_text, oncology_terms)
            or has_advanced
            or has_palliative
            or has_active_chemo
        )

        matched_terms = sorted(
            {
                term
                for term in (oncology_terms + advanced_terms + palliative_terms + chemotherapy_terms)
                if term in context_text
            }
        )
        return {
            "has_oncology_context": has_oncology,
            "has_advanced_cancer": has_advanced,
            "has_palliative_intent": has_palliative,
            "has_active_chemotherapy": has_active_chemo,
            "matched_terms": matched_terms,
        }

    def _extract_urology_context(self, medical_history: dict[str, Any]) -> dict[str, Any]:
        context_parts: list[str] = []
        for key in [
            "chronic_conditions",
            "recent_diagnoses",
            "medication_patterns",
            "previous_specializations",
            "treatment_context",
        ]:
            context_parts.extend(
                [str(item).strip().lower() for item in self._coerce_string_list(medical_history.get(key)) if str(item).strip()]
            )
        context_text = " ".join(context_parts)

        stone_terms = [
            "renal calculi",
            "renal calculus",
            "kidney stone",
            "kidney stones",
            "renal stone",
            "urolithiasis",
            "nephrolithiasis",
            "ureteric stone",
            "ureter stone",
            "urinary stone",
            "bladder stone",
        ]
        urology_terms = [
            "urology",
            "urologist",
            "kidney and urology",
            "endourology",
            "hematuria",
            "flank pain",
            "renal colic",
        ]
        complicated_terms = [
            "obstructive uropathy",
            "hydronephrosis",
            "anuria",
            "acute kidney injury",
            "fever",
            "sepsis",
            "pyelonephritis",
        ]

        has_stone_context = self._contains_any(context_text, stone_terms)
        has_urology_context = has_stone_context or self._contains_any(context_text, urology_terms)
        has_complicated_signals = self._contains_any(context_text, complicated_terms)

        matched_terms = sorted(
            {
                term
                for term in (stone_terms + urology_terms + complicated_terms)
                if term in context_text
            }
        )
        return {
            "has_urology_context": has_urology_context,
            "has_stone_context": has_stone_context,
            "has_complicated_signals": has_complicated_signals,
            "matched_terms": matched_terms,
        }

    def _extract_respiratory_context(self, medical_history: dict[str, Any]) -> dict[str, Any]:
        context_parts: list[str] = []
        for key in [
            "chronic_conditions",
            "recent_diagnoses",
            "medication_patterns",
            "previous_specializations",
            "treatment_context",
        ]:
            context_parts.extend(
                [str(item).strip().lower() for item in self._coerce_string_list(medical_history.get(key)) if str(item).strip()]
            )
        context_text = " ".join(context_parts)

        chronic_airway_terms = [
            "asthma",
            "reactive airway",
            "copd",
            "chronic obstructive pulmonary disease",
            "allergic rhinitis",
            "chronic bronchitis",
        ]
        active_respiratory_terms = [
            "bacterial bronchitis",
            "acute bronchitis",
            "respiratory infection",
            "productive cough",
            "phlegm",
            "sputum",
            "breathlessness",
            "shortness of breath",
            "wheeze",
            "wheezing",
            "night cough",
            "nocturnal cough",
        ]
        respiratory_specialty_terms = [
            "pulmonology",
            "pulmonologist",
            "chest medicine",
            "respiratory medicine",
        ]

        has_chronic_airway_disease = self._contains_any(context_text, chronic_airway_terms)
        has_active_respiratory_diagnosis = self._contains_any(context_text, active_respiratory_terms)
        has_respiratory_context = (
            has_chronic_airway_disease
            or has_active_respiratory_diagnosis
            or self._contains_any(context_text, respiratory_specialty_terms)
        )

        matched_terms = sorted(
            {
                term
                for term in (chronic_airway_terms + active_respiratory_terms + respiratory_specialty_terms)
                if term in context_text
            }
        )
        return {
            "has_respiratory_context": has_respiratory_context,
            "has_chronic_airway_disease": has_chronic_airway_disease,
            "has_active_respiratory_diagnosis": has_active_respiratory_diagnosis,
            "matched_terms": matched_terms,
        }

    def _get_specialist_hint_for_category(
        self,
        primary_category: str,
        recommended_specializations: list[str],
    ) -> str:
        spec = merge_specialties(
            recommended_specializations,
            primary_category=primary_category,
            include_fallback=True,
            limit=3,
        )
        if spec:
            return spec[0]

        fallback_map = {
            "cardiac": "Cardiology",
            "neurology": "Neurology",
            "oncology": "Clinical Oncology",
            "gastrointestinal": "Gastroenterology",
            "respiratory": "Pulmonology",
            "urology": "Urology",
            "dermatology": "Dermatology",
            "endocrinology": "Endocrinology",
            "general": "Internal Medicine",
        }
        return fallback_map.get(str(primary_category or "general").strip().lower(), "Internal Medicine")

    def _ensure_triage_note_mentions_specialist(
        self,
        triage_note: str,
        primary_category: str,
        recommended_specializations: list[str],
        urgency: str,
        language: str = "en",
    ) -> str:
        note = str(triage_note or "").strip()
        if not note:
            urgency_value = str(urgency or "").strip().lower()
            if urgency_value == "high":
                note = (
                    "অবিলম্বে সরাসরি মূল্যায়ন দরকার।"
                    if self._is_bangla(language)
                    else "Immediate in-person assessment is advised."
                )
            elif urgency_value == "moderate":
                note = (
                    "আগেভাগে বিশেষজ্ঞ পর্যালোচনা দরকার।"
                    if self._is_bangla(language)
                    else "Early specialist review is advised."
                )
            else:
                note = (
                    "আউটপেশেন্ট বিশেষজ্ঞ পরামর্শ যুক্তিসঙ্গত।"
                    if self._is_bangla(language)
                    else "Outpatient specialist consultation is reasonable."
                )

        specialist_hint = self._get_specialist_hint_for_category(
            primary_category=primary_category,
            recommended_specializations=recommended_specializations,
        )
        normalized_note = self._normalize_text(note)
        specific_markers = [
            self._normalize_text(item)
            for item in ([specialist_hint] + [str(spec).strip() for spec in recommended_specializations[:3]])
            if str(item).strip()
        ]
        has_specific_specialty = any(marker and marker in normalized_note for marker in specific_markers)
        if has_specific_specialty:
            return note

        suffix = (
            f"প্রস্তাবিত বিশেষজ্ঞ: {specialist_hint}।"
            if self._is_bangla(language)
            else f"Recommended specialist: {specialist_hint}."
        )
        note = note.rstrip(".")
        return f"{note}. {suffix}"

    def _ensure_next_steps_include_specialist(
        self,
        steps: list[str],
        recommended_specializations: list[str],
        language: str = "en",
    ) -> list[str]:
        normalized_steps = [str(step).strip() for step in steps if str(step).strip()]
        spec = merge_specialties(recommended_specializations, include_fallback=False, limit=3)
        if not spec:
            return normalized_steps[:6]

        steps_blob = " ".join([self._normalize_text(item) for item in normalized_steps])
        has_specialist_guidance = any(self._normalize_text(item) in steps_blob for item in spec[:3])
        if not has_specialist_guidance:
            specialist_step = (
                f"লক্ষ্য বিশেষজ্ঞ বিভাগ: {', '.join(spec[:2])}।"
                if self._is_bangla(language)
                else f"Target specialist area: {', '.join(spec[:2])}."
            )
            insert_index = 1 if normalized_steps else 0
            normalized_steps.insert(insert_index, specialist_step)
        return normalized_steps[:6]

    def _calculate_experience_score(self, doctor: Doctor) -> float:
        exp_score = min((doctor.experience_years or 0) / 20, 1.0)
        rating_score = (doctor.average_rating or 3.0) / 5.0
        return (exp_score * 0.4) + (rating_score * 0.6)

    def _calculate_availability_score(self, doctor: Doctor) -> float:
        return 0.85 if doctor.available_slots else 0.5

    def _calculate_doctor_affinity_boost(self, doctor: Doctor, symptom_analysis: dict) -> tuple[float, list[str]]:
        text = " ".join([item.lower() for item in symptom_analysis.get("symptom_descriptions", [])])
        name = (doctor.user.username.lower() if doctor.user and doctor.user.username else "")
        boost = 0.0
        reasons: list[str] = []

        if "shafique" in name and self._contains_any(
            text,
            [
                "heart",
                "cardiac",
                "chest pain",
                "palpitation",
                "pressure",
                "exertion",
                "jaw pain",
                "left arm pain",
                "shortness of breath",
            ],
        ):
            boost += 0.4
            reasons.append("High cardiac fit for current symptom pattern")

        if "himu" in name and self._contains_any(
            text,
            [
                "headache",
                "seizure",
                "stroke",
                "neurology",
                "nerve",
                "memory",
                "numbness",
                "dizziness",
                "slurred speech",
                "one-sided weakness",
            ],
        ):
            boost += 0.4
            reasons.append("High neurological fit for current symptom pattern")

        if "akram" in name and self._contains_any(
            text,
            [
                "cancer",
                "oncology",
                "radiotherapy",
                "chemo",
                "tumor",
                "lymph node",
                "unexplained weight loss",
                "lung cancer",
                "gynecological cancer",
            ],
        ):
            boost += 0.35
            reasons.append("Clinical oncology/radiotherapy profile matches likely need")

        if "farid" in name and self._contains_any(
            text,
            ["breast", "breast lump", "breast mass", "nipple discharge", "tumor", "cancer", "oncology"],
        ):
            boost += 0.3
            reasons.append("Oncoplastic breast surgery profile matches symptom context")

        if "qazi" in name and self._contains_any(
            text,
            [
                "cancer",
                "oncology",
                "tumor",
                "mass",
                "unexplained weight loss",
                "abdominal pain",
                "gastrointestinal",
                "bowel",
                "lung cancer",
                "gynecological cancer",
            ],
        ):
            boost += 0.35
            reasons.append("Cancer-care profile aligns with reported symptom cluster")

        if "farid" in name and self._contains_any(
            text,
            ["abdominal pain", "colorectal", "bowel", "gastrointestinal", "rectal bleeding", "blood in stool"],
        ):
            boost += 0.35
            reasons.append("Colorectal and surgical oncology focus fits symptom pattern")

        return min(boost, 1.0), reasons

    @staticmethod
    def _contains_any(text: str, terms: list[str]) -> bool:
        return any(term in text for term in terms)

    @staticmethod
    def _collect_keyword_hits(text: str, terms: list[str]) -> list[str]:
        return sorted({term for term in terms if term in text})

    @staticmethod
    def _normalize_text(value: str) -> str:
        return normalize_medical_text(value)

    @staticmethod
    def _clean_generated_text(value: Any) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        if not text:
            return ""
        text = re.sub(
            r"^(?:null|none|undefined|n/?a|not available|not provided|unknown)\b[\s:;,\-–]*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        normalized = normalize_medical_text(text)
        if normalized in {
            "",
            "n a",
            "na",
            "none",
            "not available",
            "not provided",
            "null",
            "undefined",
            "unknown",
        }:
            return ""
        return text

    @staticmethod
    def _is_bangla(language: str | None = None) -> bool:
        return normalize_response_language(language) == "bn"

    @staticmethod
    def _translate_specialty_to_bangla(specialty: str) -> str:
        """Translate medical specialty names to Bangla."""
        specialty_map = {
            "Nephrologist": "নেফ্রোলজি",
            "Kidney Specialist": "নেফ্রোলজি",
            "Cardiologist": "কার্ডিওলজি",
            "Heart Specialist": "হৃদরোগ বিশেষজ্ঞ",
            "Endocrinologist": "এন্ডোক্রিনোলজি",
            "Urologist": "ইউরোলজি",
            "Gastroenterologist": "গ্যাস্ট্রোএন্টেরোলজি",
            "Neurologist": "নিউরোলজি",
            "Pulmonologist": "ফুসফুলোগ বিশেষজ্ঞ",
            "Oncologist": "ক্যান্সার বিশেষজ্ঞ",
            "Rheumatologist": "রিউমাটয়ড বিশেষজ্ঞ",
            "Dermatologist": "চর্মরোগ বিশেষজ্ঞ",
            "Psychiatrist": "মানসিক রোগ বিশেষজ্ঞ",
            "Obstetrician & Gynecologist": "প্রসূতি ও স্ত্রী রোগ বিশেষজ্ঞ",
            "Orthopedic Surgeon": "অর্থোপেডিক সার্জন",
            "ENT Specialist": "নাক কান গলা বিশেষজ্ঞ",
            "ENT": "নাক কান গলা বিশেষজ্ঞ",
            "Ophthalmologist": "চক্ষু বিশেষজ্ঞ",
            "Internal Medicine": "ইন্টার্নাল মেডিসিন বিশেষজ্ঞ",
            "General Physician": "জেনারেল ফিজিশিয়ান",
            "General Medicine": "জেনারেল মেডিসিন",
            "Pediatrician": "শিশু রোগ বিশেষজ্ঞ",
            "Pain Specialist": "ব্যথা বিশেষজ্ঞ",
            "Hepatologist": "লিভার বিশেষজ্ঞ",
        }
        return specialty_map.get(specialty, specialty)

    @staticmethod
    def _translate_condition_to_bangla(condition: str) -> str:
        """Translate medical condition names to Bangla."""
        condition_map = {
            "hypertension": "উচ্চ রক্তচাপ",
            "high blood pressure": "উচ্চ রক্তচাপ",
            "hyperlipidemia": "হাইপারলিপিড (উচ্চ কোলেস্টেরল)",
            "right renal calculi": "ডান কিডনি পাথর",
            "kidney stone": "কিডনি পাথর",
            "renal calculi": "কিডনি পাথর",
            "diabetes": "ডায়াবিটিস",
            "diabetes mellitus": "ডায়াবিটিস",
            "chronic kidney disease": "দীর্ঘস্থায় কিডনি রোগ",
            "ckd": "দীর্ঘস্থায় কিডনি রোগ",
            "cardiac disease": "হৃদরোগ",
            "heart disease": "হৃদরোগ",
            "gastroesophageal reflux": "খাদ্যনালী রিফ্লাক্স (GERD)",
            "gerd": "খাদ্যনালী রিফ্লাক্স",
            "diverticulum": "ডাইভার্টিকুলাম",
            "diverticulitis": "ডাইভার্টিকুলাম প্রদাহর",
            "anxiety": "উদ্বেগ",
            "depression": "বিষণগ্রস্তা",
            "insomnia": "অনিদ্র নিদ্র",
        }
        return condition_map.get(condition.lower(), condition)

    @staticmethod
    def _category_display(primary_category: str, language: str | None = None) -> str:
        category_key = str(primary_category or "general").strip().lower().replace("_", " ")
        if not DoctorRecommendationService._is_bangla(language):
            return category_key

        labels = {
            "cardiac": "হৃদ্‌রোগ-সংক্রান্ত",
            "neurology": "স্নায়ু-সংক্রান্ত",
            "oncology": "অনকোলজি-সংক্রান্ত",
            "gastrointestinal": "পাকস্থলী ও অন্ত্র-সংক্রান্ত",
            "respiratory": "শ্বাসতন্ত্র-সংক্রান্ত",
            "urology": "ইউরোলজি-সংক্রান্ত",
            "dermatology": "ত্বক-সংক্রান্ত",
            "endocrinology": "হরমোন-সংক্রান্ত",
            "general": "সাধারণ",
        }
        return labels.get(category_key, category_key)

    @staticmethod
    def _urgency_display(urgency: str, language: str | None = None) -> str:
        urgency_key = str(urgency or "low").strip().lower()
        if not DoctorRecommendationService._is_bangla(language):
            return urgency_key

        labels = {
            "low": "কম",
            "routine": "রুটিন",
            "moderate": "মাঝারি",
            "urgent": "জরুরি",
            "high": "উচ্চ",
            "emergency": "জরুরি",
        }
        return labels.get(urgency_key, urgency_key)

    @staticmethod
    def _default_outpatient_triage_note(language: str | None = None) -> str:
        if DoctorRecommendationService._is_bangla(language):
            return "দেওয়া তথ্য অনুযায়ী আউটপেশেন্ট বিশেষজ্ঞ পরামর্শ যুক্তিসঙ্গত।"
        return "Outpatient consultation is reasonable based on provided symptoms."

    def _localize_follow_up_question(self, question: str, language: str | None = None) -> str:
        text = str(question or "").strip()
        if not text or not self._is_bangla(language):
            return text

        translations = {
            # Common follow-up questions - exact matches
            "When did the kidney pain start?": "কিডনির ব্যথা কবে শুরু হয়েছে?",
            "Have you noticed any changes in your urine color or frequency?": "আপনি কি প্রস্রবের রঙে বা প্রস্রবের ধরনে কোনো পরিবর্তন লক্ষ্য করেছেন?",
            "Is the pain constant, or does it come and go?": "ব্যথা কি সারাসময় থাকে, নাকি আসা-যাওয়া করে?",
            "Have you experienced any nausea or vomiting?": "আপনার কি বমিভাব বা বমি হয়েছে?",
            "Are you currently following any specific dietary restrictions?": "আপনি কি বর্তমানে কোনো বিশেষ খাদ্যাভ্যাস মেনে চলছেন?",
            # Original translations
            "Since the kidney pain or fever started, have the symptoms been getting worse, improving, or coming in waves?": "কিডনির ব্যথা বা জ্বর শুরু হওয়ার পর থেকে উপসর্গগুলো কি বাড়ছে, কমছে, নাকি ঢেউয়ের মতো আসা-যাওয়া করছে?",
            "When did the kidney pain and fever start, and have they been getting worse, improving, or coming in waves?": "কিডনির ব্যথা ও জ্বর কবে শুরু হয়েছে, এবং এগুলো কি বাড়ছে, কমছে, নাকি ঢেউয়ের মতো আসা-যাওয়া করছে?",
            "Where exactly is the pain, does it move toward the groin, and how severe is it on a 0 to 10 scale?": "ব্যথা ঠিক কোথায় হচ্ছে, এটি কি কুঁচকির দিকে ছড়ায়, এবং ০ থেকে ১০-এর মধ্যে এর তীব্রতা কত?",
            "Have you had burning urine, blood in urine, reduced urine output, urgency, or difficulty passing urine?": "প্রস্রাবে জ্বালা, প্রস্রাবে রক্ত, প্রস্রাব কম হওয়া, তাড়াহুড়ো অনুভব করা বা প্রস্রাব করতে কষ্ট হচ্ছে কি?",
            "What temperature have you measured, and have you had chills, shivering, or felt markedly unwell with it?": "আপনি কত তাপমাত্রা মেপেছেন, এবং এর সঙ্গে কাঁপুনি, শীত শীত ভাব বা খুব অসুস্থ লাগা আছে কি?",
            "Have you had nausea or vomiting, and are you able to keep fluids down?": "বমিভাব বা বমি হয়েছে কি, এবং আপনি কি পানি বা তরল ধরে রাখতে পারছেন?",
            "Have you had a recent ultrasound or CT scan, or a previous stone episode, and what did it show?": "সম্প্রতি কি আল্ট্রাসাউন্ড বা সিটি স্ক্যান হয়েছে, বা আগে পাথরের সমস্যা ছিল? থাকলে তাতে কী দেখা গিয়েছিল?",
            "Since the Blood Urea, Serum Creatinine results were abnormal, have you noticed swelling, poor appetite, increasing weakness, or less urine than usual?": "Blood Urea ও Serum Creatinine-এর ফল অস্বাভাবিক হওয়ার পর থেকে কি ফোলা, ক্ষুধা কমে যাওয়া, দুর্বলতা বাড়া বা স্বাভাবিকের তুলনায় প্রস্রাব কম হওয়া লক্ষ্য করেছেন?",
            "Have you taken any pain medicine or prescribed treatment for this, and did it help even temporarily?": "এ জন্য কি কোনো ব্যথার ওষুধ বা নির্ধারিত চিকিৎসা নিয়েছেন, এবং তা সাময়িক হলেও উপকার করেছে কি?",
            "Since these symptoms started, have they been constant, coming and going, or clearly getting worse?": "উপসর্গগুলো শুরু হওয়ার পর থেকে কি সবসময় একই আছে, আসা-যাওয়া করছে, নাকি স্পষ্টভাবে খারাপ হচ্ছে?",
            "When exactly did these symptoms start, and have they been constant or coming and going?": "এই উপসর্গগুলো ঠিক কবে শুরু হয়েছে, এবং এগুলো কি সবসময় আছে নাকি আসা-যাওয়া করছে?",
            "Where is the discomfort worst right now, does it spread anywhere, and how severe is it on a 0 to 10 scale?": "এই মুহূর্তে অস্বস্তি সবচেয়ে বেশি কোথায়, এটি কি অন্য কোথাও ছড়ায়, এবং ০ থেকে ১০-এর মধ্যে এর তীব্রতা কত?",
            "Have you noticed symptoms that may relate to the Blood Urea, Serum Creatinine result, such as weakness, dizziness, swelling, or appetite change?": "Blood Urea বা Serum Creatinine-এর ফলের সঙ্গে সম্পর্কিত হতে পারে এমন দুর্বলতা, মাথা ঘোরা, ফোলা বা ক্ষুধার পরিবর্তন কি লক্ষ্য করেছেন?",
            "Were any recent report values marked high or low, and did your current symptoms begin before or after those results?": "সাম্প্রতিক রিপোর্টের কোনো মান কি বেশি বা কম চিহ্নিত হয়েছে, এবং আপনার বর্তমান উপসর্গগুলো সেই ফলের আগে না পরে শুরু হয়েছে?",
            "Is the chest discomfort triggered by exertion or stress, and does it spread to your arm, jaw, back, or shoulder?": "বুকের অস্বস্তি কি পরিশ্রম বা মানসিক চাপের সময় বাড়ে, এবং এটি কি হাত, চোয়াল, পিঠ বা কাঁধে ছড়ায়?",
            "Have you had sweating, nausea, palpitations, fainting, or shortness of breath with it?": "এর সঙ্গে ঘাম, বমিভাব, ধড়ফড়ানি, অজ্ঞান হওয়া বা শ্বাসকষ্ট হয়েছে কি?",
            "Is the cough or breathing problem worse at night, with walking, or when lying flat?": "কাশি বা শ্বাসকষ্ট কি রাতে, হাঁটলে বা সোজা শোয়ায় বাড়ে?",
            "Have you had wheezing, fever, chest tightness, or low oxygen readings with this episode?": "এই সমস্যার সঙ্গে কি হাঁপানির মতো শব্দ, জ্বর, বুকে চাপ বা অক্সিজেন কম থাকার রিডিং হয়েছে?",
            "Is the abdominal problem related to meals or bowel movements, and have you had vomiting, diarrhea, constipation, or black stool?": "পেটের সমস্যা কি খাওয়া বা পায়খানার সঙ্গে সম্পর্কিত, এবং বমি, ডায়রিয়া, কোষ্ঠকাঠিন্য বা কালো পায়খানা হয়েছে কি?",
            "Did the headache or neurological symptom start suddenly or gradually, and have you had weakness, numbness, speech change, or vision problems?": "মাথাব্যথা বা স্নায়বিক উপসর্গটি কি হঠাৎ শুরু হয়েছে নাকি ধীরে ধীরে, এবং এর সঙ্গে দুর্বলতা, অবশভাব, কথা জড়িয়ে যাওয়া বা দৃষ্টির সমস্যা আছে কি?",
            "Does the pain move from your side or back toward the groin, and have you had burning urine, blood in urine, fever, or reduced urine output?": "ব্যথা কি পাশ বা পিঠ থেকে কুঁচকির দিকে যায়, এবং প্রস্রাবে জ্বালা, রক্ত, জ্বর বা প্রস্রাব কম হওয়া আছে কি?",
            "When did the skin change start, where did it begin, and is it itchy, painful, blistering, or spreading?": "ত্বকের পরিবর্তন কবে শুরু হয়েছে, কোথা থেকে শুরু হয়েছে, এবং এটি কি চুলকাচ্ছে, ব্যথা করছে, ফোসকা হচ্ছে, বা ছড়িয়ে পড়ছে?",
            "Have you noticed increased thirst, frequent urination, unusual sweating, tremor, or recent weight or appetite change?": "বাড়তি পিপাসা, ঘন ঘন প্রস্রাব, অস্বাভাবিক ঘাম, কাঁপুনি, বা সাম্প্রতিক ওজন বা ক্ষুধার পরিবর্তন লক্ষ্য করেছেন কি?",
            "Since starting your prescribed medicines, have the symptoms improved, worsened, or caused any side effects?": "নির্ধারিত ওষুধগুলো শুরু করার পর উপসর্গ কমেছে, বেড়েছে, নাকি কোনো পার্শ্বপ্রতিক্রিয়া হয়েছে?",
            "Has anything changed since you were told this may be related to Diverticulum?": "এটি Diverticulum-এর সঙ্গে সম্পর্কিত হতে পারে বলা হওয়ার পর থেকে কি কোনো পরিবর্তন হয়েছে?",
            "What clearly makes the main symptom worse or better, such as movement, food, deep breathing, rest, or stress?": "কোন বিষয়গুলো মূল উপসর্গকে স্পষ্টভাবে বাড়ায় বা কমায়, যেমন নড়াচড়া, খাবার, গভীর শ্বাস, বিশ্রাম বা মানসিক চাপ?",
            "Are you having any warning signs right now such as fever, bleeding, fainting, severe breathlessness, or rapidly worsening pain?": "এই মুহূর্তে কি জ্বর, রক্তপাত, অজ্ঞান হওয়া, তীব্র শ্বাসকষ্ট বা দ্রুত বাড়তে থাকা ব্যথার মতো সতর্কতামূলক লক্ষণ আছে?",
            "Have you had any recent imaging studies (ultrasound, CT, or X-ray), and what were the results?": "সম্প্রতি কি কোনো ইমেজিং টেস্ট (আল্ট্রাসাউন্ড, সিটি, বা এক্স-রে) হয়েছে, এবং তাতে কী ফল এসেছে?",
            "Have there been any recent diet, hydration, or lifestyle changes that affect your symptoms?": "সাম্প্রতিক খাদ্যাভ্যাস, পানি পানের ধরন বা জীবনযাত্রায় এমন কোনো পরিবর্তন হয়েছে কি যা উপসর্গকে প্রভাবিত করছে?",
            "What medications are you taking now, and did any medicine change your symptoms?": "আপনি এখন কী কী ওষুধ খাচ্ছেন, এবং কোনো ওষুধ কি আপনার উপসর্গে পরিবর্তন এনেছে?",
            "What temperature have you measured, and have you had chills or shivering with it?": "আপনি কত তাপমাত্রা মেপেছেন, এবং এর সঙ্গে কাঁপুনি হয়েছে কি?",
            "Is the pain steady, or does it come in waves, and is it becoming more severe?": "ব্যথা কি একটানা থাকে, নাকি ঢেউয়ের মতো আসে, এবং এটি কি আরও তীব্র হচ্ছে?",
            # Additional common follow-up questions
            "How long have you had this pain?": "আপনার কতদিন ধরে এই ব্যথা আছে?",
            "Do you have any fever?": "আপনার কি জ্বর আছে?",
            "Are you taking any medications?": "আপনি কি কোনো ওষুধ খাচ্ছেন?",
            "Do you have any medical conditions?": "আপনার কি কোনো স্বাস্থ্য সমস্যা আছে?",
            "Have you had this problem before?": "আগে কি এই সমস্যা হয়েছে?",
            "What makes the pain better or worse?": "কী করলে ব্যথা কমে বা বাড়ে?",
            "Where is the pain located?": "ব্যথা কোথায় হচ্ছে?",
            "Does the pain radiate to any other part of your body?": "ব্যথা কি শরীরের অন্য কোনো অংশে ছড়িয়ে পড়ে?",
            "Have you noticed any swelling?": "আপনি কি কোনো ফোলা লক্ষ্য করেছেন?",
            "Are you able to sleep comfortably?": "আপনি কি আরামে ঘুমাতে পারেন?",
            "Have you lost any weight recently?": "সম্প্রতি আপনার ওজন কমেছে কি?",
            "Do you have any allergies?": "আপনার কি কোনো অ্যালার্জি আছে?",
            "How is your appetite?": "আপনার ক্ষুধা কেমন?",
            "Are you feeling more tired than usual?": "আপনি কি স্বাভাবিকের চেয়ে বেশি ক্লান্ত বোধ করছেন?",
            "Have you had any recent tests done?": "সম্প্রতি কি কোনো পরীক্ষা হয়েছে?",
        }

        return translations.get(text, text)

    @staticmethod
    def _has_llm_document_context(
        *,
        medications: list[dict] | None = None,
        diagnosis: str | None = None,
        report_findings: list[dict] | None = None,
        document_summary: str | None = None,
        document_instructions: str | None = None,
        document_warnings: list[str] | None = None,
        doctor_specialization: str | None = None,
    ) -> bool:
        return any(
            [
                bool(medications),
                bool(DoctorRecommendationService._clean_generated_text(diagnosis)),
                bool(report_findings),
                bool(DoctorRecommendationService._clean_generated_text(document_summary)),
                bool(DoctorRecommendationService._clean_generated_text(document_instructions)),
                bool(document_warnings),
                bool(DoctorRecommendationService._clean_generated_text(doctor_specialization)),
            ]
        )

    def _llm_analysis_has_meaningful_content(self, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        return any(
            [
                bool(self._coerce_string_list(payload.get("recommended_specializations"))),
                bool(self._clean_generated_text(payload.get("clinical_impression"))),
                bool(self._coerce_string_list(payload.get("follow_up_questions"))),
                isinstance(payload.get("prescription_analysis"), dict),
                isinstance(payload.get("report_analysis"), dict),
            ]
        )

    @staticmethod
    def _contains_bangla_chars(value: Any) -> bool:
        return any("\u0980" <= char <= "\u09ff" for char in str(value or ""))

    @staticmethod
    def _contains_latin_letters(value: Any) -> bool:
        return any("a" <= char.lower() <= "z" for char in str(value or ""))

    def _collect_symptom_analysis_patient_facing_text(self, payload: dict[str, Any]) -> list[str]:
        if not isinstance(payload, dict):
            return []

        collected: list[str] = []

        def add(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    add(item)
                return
            text = self._clean_generated_text(value)
            if text:
                collected.append(text)

        for key in [
            "recommended_specializations",
            "triage_note",
            "profile_summary",
            "additional_information_assessment",
            "clinical_impression",
            "likely_concerns",
            "immediate_actions",
            "immediate_suggestions",
            "red_flags_to_watch",
            "concerning_things_to_monitor",
            "red_flags",
            "follow_up_questions",
            "recommended_next_steps",
        ]:
            add(payload.get(key))

        prescription_analysis = payload.get("prescription_analysis")
        if isinstance(prescription_analysis, dict):
            add(prescription_analysis.get("overall_assessment"))
            for item in prescription_analysis.get("medication_breakdown") or []:
                if isinstance(item, dict):
                    add(item.get("ai_analysis"))

        report_analysis = payload.get("report_analysis")
        if isinstance(report_analysis, dict):
            add(report_analysis.get("overall_assessment"))
            for item in report_analysis.get("lab_findings") or []:
                if isinstance(item, dict):
                    add(item.get("ai_analysis"))

        return collected

    def _align_llm_report_analysis_to_source(
        self,
        report_analysis: dict[str, Any],
        report_findings: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        payload = report_analysis if isinstance(report_analysis, dict) else {}
        source_findings = self._normalize_report_findings(report_findings)
        if not source_findings:
            return payload

        llm_findings = payload.get("lab_findings") or []
        llm_lookup: dict[tuple[str, str | None], dict[str, Any]] = {}
        ordered_llm: list[dict[str, Any]] = []
        if isinstance(llm_findings, list):
            for item in llm_findings:
                if not isinstance(item, dict):
                    continue
                normalized_name = normalize_report_test_name(str(item.get("test_name") or "").strip())
                observed_value = str(item.get("observed_value") or "").strip() or None
                if normalized_name:
                    llm_lookup[(normalized_name, observed_value)] = item
                    llm_lookup.setdefault((normalized_name, None), item)
                ordered_llm.append(item)

        merged_findings: list[dict[str, Any]] = []
        for index, finding in enumerate(source_findings[:12]):
            test_name = normalize_report_test_name(str(finding.get("test_name") or "").strip())
            observed_value = str(finding.get("observed_value") or "").strip() or None
            llm_item = (
                llm_lookup.get((test_name, observed_value))
                or llm_lookup.get((test_name, None))
                or (ordered_llm[index] if index < len(ordered_llm) else None)
            )
            merged_findings.append(
                {
                    **finding,
                    "ai_analysis": (
                        llm_item.get("ai_analysis")
                        if isinstance(llm_item, dict)
                        else finding.get("ai_analysis")
                    ),
                }
            )

        return {
            **payload,
            "lab_findings": merged_findings,
            "overall_assessment": payload.get("overall_assessment"),
        }

    def _symptom_analysis_needs_language_repair(self, payload: dict[str, Any], language: str) -> bool:
        normalized_language = normalize_response_language(language)
        texts = self._collect_symptom_analysis_patient_facing_text(payload)
        if not texts:
            return False
        if normalized_language == "en":
            return any(self._contains_bangla_chars(text) for text in texts)
        if normalized_language == "bn":
            return any(
                self._contains_latin_letters(text) and not self._contains_bangla_chars(text)
                for text in texts
            )
        return False

    async def _repair_symptom_analysis_language_if_needed(
        self,
        payload: dict[str, Any],
        language: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload

        normalized_language = normalize_response_language(language)
        if not self._symptom_analysis_needs_language_repair(payload, normalized_language):
            return payload

        prompt = textwrap.dedent(
            f"""\
            TASK: Repair the language of this medical JSON output.

            Rewrite ONLY the patient-facing JSON values into the requested language.
            Keep the same JSON structure, medical meaning, severity, urgency, and specialty intent.
            Do not add new medical claims, new test values, or new medicines.
            Preserve JSON keys, numbers, medicine brand names, lab values, and reference ranges.
            Return JSON only.

            Requested language: {normalized_language}

            JSON:
            {json.dumps(payload, ensure_ascii=False, default=str)}
            """
        )

        try:
            repaired = await self.llm_client.complete_json(
                prompt=prompt,
                system_prompt=(
                    "You normalize the language of structured medical JSON. "
                    "Only repair patient-facing values that are in the wrong language."
                ),
                language=normalized_language,
            )
        except Exception:
            return payload

        if not isinstance(repaired, dict):
            return payload
        logger.info("Symptom LLM language repair applied language=%s", normalized_language)
        return self._merge_repaired_symptom_analysis_language(payload, repaired)

    def _merge_repaired_symptom_analysis_language(
        self,
        original: dict[str, Any],
        repaired: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(original or {})

        for key in [
            "recommended_specializations",
            "triage_note",
            "profile_summary",
            "additional_information_assessment",
            "clinical_impression",
            "likely_concerns",
            "immediate_actions",
            "immediate_suggestions",
            "red_flags_to_watch",
            "concerning_things_to_monitor",
            "red_flags",
            "follow_up_questions",
            "recommended_next_steps",
        ]:
            if key in repaired:
                merged[key] = repaired.get(key)

        original_prescription = original.get("prescription_analysis")
        repaired_prescription = repaired.get("prescription_analysis")
        if isinstance(original_prescription, dict) and isinstance(repaired_prescription, dict):
            merged_prescription = dict(original_prescription)
            if "overall_assessment" in repaired_prescription:
                merged_prescription["overall_assessment"] = repaired_prescription.get("overall_assessment")
            repaired_breakdown = repaired_prescription.get("medication_breakdown") or []
            original_breakdown = original_prescription.get("medication_breakdown") or []
            if isinstance(original_breakdown, list):
                merged_breakdown: list[dict[str, Any]] = []
                for index, item in enumerate(original_breakdown):
                    if not isinstance(item, dict):
                        continue
                    merged_item = dict(item)
                    repaired_item = repaired_breakdown[index] if index < len(repaired_breakdown) else None
                    if isinstance(repaired_item, dict):
                        if "ai_analysis" in repaired_item:
                            merged_item["ai_analysis"] = repaired_item.get("ai_analysis")
                        if "condition_treated" in repaired_item:
                            merged_item["condition_treated"] = repaired_item.get("condition_treated")
                    merged_breakdown.append(merged_item)
                merged_prescription["medication_breakdown"] = merged_breakdown
            merged["prescription_analysis"] = merged_prescription

        original_report = original.get("report_analysis")
        repaired_report = repaired.get("report_analysis")
        if isinstance(original_report, dict) and isinstance(repaired_report, dict):
            merged_report = dict(original_report)
            if "overall_assessment" in repaired_report:
                merged_report["overall_assessment"] = repaired_report.get("overall_assessment")
            repaired_findings = repaired_report.get("lab_findings") or []
            original_findings = original_report.get("lab_findings") or []
            if isinstance(original_findings, list):
                merged_findings: list[dict[str, Any]] = []
                for index, item in enumerate(original_findings):
                    if not isinstance(item, dict):
                        continue
                    merged_item = dict(item)
                    repaired_item = repaired_findings[index] if index < len(repaired_findings) else None
                    if isinstance(repaired_item, dict) and "ai_analysis" in repaired_item:
                        merged_item["ai_analysis"] = repaired_item.get("ai_analysis")
                    merged_findings.append(merged_item)
                merged_report["lab_findings"] = merged_findings
            merged["report_analysis"] = merged_report

        return merged

    @staticmethod
    def _extract_additional_information(symptoms: list[str]) -> list[str]:
        additional: list[str] = []
        prefix = "additional problem:"
        for item in symptoms:
            text = str(item).strip()
            if not text:
                continue
            lower = text.lower()
            if lower.startswith(prefix):
                extracted = text[len(prefix) :].strip()
                if extracted:
                    additional.append(extracted)
        return additional

    def _build_additional_information_assessment(
        self,
        additional_information: list[str],
        language: str = "en",
    ) -> str:
        return ""

    def _build_default_clinical_impression(
        self,
        primary_category: str,
        urgency: str,
        severity: int,
        triage_note: str,
        language: str = "en",
    ) -> str:
        category_text = self._category_display(primary_category, language)
        urgency_text = self._urgency_display(urgency, language)
        triage_text = str(triage_note or "").strip()
        if not triage_text:
            triage_text = self._default_outpatient_triage_note(language)
        if self._is_bangla(language):
            return (
                f"উপসর্গের ধরণ সবচেয়ে বেশি {category_text} সমস্যার সঙ্গে সামঞ্জস্যপূর্ণ। "
                f"বর্তমান তথ্য অনুযায়ী অগ্রাধিকার {urgency_text} এবং তীব্রতা {severity}/10। "
                f"{triage_text}"
            )
        return (
            f"Symptom pattern is most consistent with a {category_text} concern profile. "
            f"Estimated urgency is {urgency_text} with severity {severity}/10 based on current inputs. "
            f"{triage_text}"
        )

    @staticmethod
    def _build_default_likely_concerns(
        keyword_hits: list[str],
        symptom_descriptions: list[str],
    ) -> list[str]:
        concerns: list[str] = []
        if keyword_hits:
            concerns.extend([str(item).strip() for item in keyword_hits if str(item).strip()])
        if not concerns:
            concerns.extend([str(item).strip() for item in symptom_descriptions if str(item).strip()])
        deduped: list[str] = []
        for item in concerns:
            lowered = item.lower()
            if lowered in {entry.lower() for entry in deduped}:
                continue
            deduped.append(item)
            if len(deduped) >= 6:
                break
        return deduped

    def _build_default_immediate_actions(
        self,
        urgency: str,
        triage_note: str,
        language: str = "en",
    ) -> list[str]:
        if self._is_bangla(language):
            actions = [
                "পরামর্শের আগে উপসর্গ কখন শুরু হয়েছে, কীভাবে বদলাচ্ছে, কী কারণে বাড়ে বা কমে তা সংক্ষেপে লিখে রাখুন।",
                "চিকিৎসক পুরো অবস্থা দেখার আগে নিজে থেকে নতুন ওষুধ শুরু বা ডোজ বাড়াবেন না।",
            ]
        else:
            actions = [
                "Keep a brief record of symptom timing, progression, triggers, and anything that provides relief before the consultation.",
                "Avoid starting extra medicines or increasing doses on your own until a clinician has reviewed the full picture.",
            ]
        urgency_value = str(urgency or "").strip().lower()
        if urgency_value in {"high", "emergency"}:
            actions.insert(
                0,
                "আজই সরাসরি মূল্যায়নের ব্যবস্থা করুন। উপসর্গ বেড়ে গেলে বা হঠাৎ খুব খারাপ লাগলে জরুরি সেবা নিন।"
                if self._is_bangla(language)
                else "Arrange same-day in-person assessment. Use emergency services immediately if symptoms escalate or you feel acutely unwell.",
            )
        elif urgency_value in {"moderate", "urgent"}:
            actions.insert(
                0,
                "আগামী ২৪ থেকে ৭২ ঘণ্টার মধ্যে জরুরি বিশেষজ্ঞ পরামর্শ নিন যাতে উপসর্গ বাড়ার আগেই মূল্যায়ন করা যায়।"
                if self._is_bangla(language)
                else "Arrange an urgent specialist review within the next 24 to 72 hours so the symptoms can be assessed before they progress.",
            )
        else:
            actions.insert(
                0,
                "কেন্দ্রিক ক্লিনিক্যাল মূল্যায়ন ও চিকিৎসা পরিকল্পনার জন্য পরবর্তী উপযুক্ত আউটপেশেন্ট পরামর্শ নিন।"
                if self._is_bangla(language)
                else "Book the next appropriate outpatient consultation for a focused clinical assessment and treatment plan.",
            )
        triage_text = str(triage_note or "").strip()
        if triage_text:
            actions.append(triage_text)
        return actions[:5]

    def _build_default_red_flags(self, category: str, severity: int, language: str = "en") -> list[str]:
        default_flags = [
            "ব্যথা, দুর্বলতা, শ্বাসকষ্ট বা সামগ্রিক অবস্থা দ্রুত খারাপ হলে দ্রুত চিকিৎসা নিন।"
            if self._is_bangla(language)
            else "Seek urgent medical attention if pain, weakness, breathing difficulty, or the overall condition is rapidly worsening.",
            "অবিরাম বমি, অজ্ঞান হওয়া, বিভ্রান্তি বা তরল ধরে রাখতে না পারলে দ্রুত চিকিৎসা নিন।"
            if self._is_bangla(language)
            else "Prompt medical review is warranted for persistent vomiting, fainting, confusion, or inability to keep fluids down.",
        ]
        category_key = str(category or "").strip().lower()
        category_flags: dict[str, list[str]] = {
            "cardiac": [
                "বুকের চাপ চোয়াল বা হাতে ছড়ালে, বিশেষ করে ঘাম বা শ্বাসকষ্ট থাকলে, জরুরি মূল্যায়ন প্রয়োজন।"
                if self._is_bangla(language)
                else "Urgent assessment is needed for chest pressure spreading to the jaw or arm, especially with sweating or breathlessness.",
                "অজ্ঞান হওয়া, মাথা ঘোরাসহ নতুন ধড়ফড়ানি বা না কমা শ্বাসকষ্ট হলে দ্রুত চিকিৎসা নিন।"
                if self._is_bangla(language)
                else "Seek prompt review for fainting, new palpitations with dizziness, or shortness of breath that is not settling.",
            ],
            "neurology": [
                "হঠাৎ একপাশ দুর্বল হওয়া, মুখ বেঁকে যাওয়া বা জড়ানো কথাকে জরুরি অবস্থা হিসেবে ধরুন।"
                if self._is_bangla(language)
                else "Treat sudden one-sided weakness, facial droop, or slurred speech as an emergency.",
                "খিঁচুনি, হঠাৎ তীব্র মাথাব্যথা, বিভ্রান্তি বা দৃষ্টিশক্তি কমে যাওয়াকে জরুরি অবস্থা হিসেবে ধরুন।"
                if self._is_bangla(language)
                else "Treat seizure, a sudden severe headache, confusion, or vision loss as an emergency.",
            ],
            "gastrointestinal": [
                "পায়খানায় রক্ত, কালো পায়খানা বা তীব্র অবিরাম পেটব্যথা হলে দ্রুত চিকিৎসা নিন।"
                if self._is_bangla(language)
                else "Please seek urgent assessment for blood in the stool, black stool, or severe continuous abdominal pain.",
                "পানিশূন্যতাসহ অবিরাম বমি বা পেট দ্রুত ফুলতে থাকলে দ্রুত চিকিৎসা নিন।"
                if self._is_bangla(language)
                else "Prompt review is warranted for persistent vomiting with dehydration or progressive abdominal distension.",
            ],
            "oncology": [
                "দ্রুত বড় হতে থাকা গাঁট, অকারণ উল্লেখযোগ্য ওজন কমে যাওয়া বা অবিরাম রক্তপাত হলে দ্রুত পর্যালোচনা দরকার।"
                if self._is_bangla(language)
                else "Urgent review is appropriate for a rapidly enlarging mass, unexplained significant weight loss, or persistent bleeding.",
                "তীব্র ক্লান্তি অন্য সিস্টেমিক উপসর্গের সঙ্গে বাড়তে থাকলে আগেভাগে ক্লিনিক্যাল পর্যালোচনার ব্যবস্থা করুন।"
                if self._is_bangla(language)
                else "Please arrange earlier clinical review for severe fatigue that is worsening alongside other systemic symptoms.",
            ],
            "respiratory": [
                "শ্বাসকষ্ট বাড়া, ঠোঁট নীল হয়ে যাওয়া বা বিশ্রামে বুকে চাপ লাগাকে জরুরি ধরে নিন।"
                if self._is_bangla(language)
                else "Treat worsening breathlessness, bluish lips, or chest tightness at rest as urgent.",
                "উচ্চ জ্বরের সঙ্গে বিভ্রান্তি বা দীর্ঘক্ষণ অক্সিজেন কম থাকলে দ্রুত মূল্যায়ন নিন।"
                if self._is_bangla(language)
                else "Seek prompt assessment for high fever with confusion or persistently low oxygen levels.",
            ],
            "urology": [
                "কোমর-পাশের ব্যথা বা প্রস্রাবে ব্যথার সঙ্গে জ্বর বা কাঁপুনি থাকলে দ্রুত চিকিৎসা পর্যালোচনা দরকার।"
                if self._is_bangla(language)
                else "Early medical review is needed for fever or chills with flank pain or painful urination.",
                "প্রস্রাব করতে না পারা, প্রস্রাব খুব কম হওয়া বা প্রস্রাবে রক্তের সঙ্গে ব্যথা বাড়লে দ্রুত চিকিৎসা নিন।"
                if self._is_bangla(language)
                else "Seek urgent care if you are unable to pass urine, urine output becomes very low, or blood in the urine is accompanied by worsening pain.",
            ],
            "dermatology": [
                "নতুন ওষুধ বা খাবারের পর দ্রুত ছড়ানো র‍্যাশ, মুখ ফুলে যাওয়া বা শ্বাসকষ্ট হলে এটিকে জরুরি ধরে নিন।"
                if self._is_bangla(language)
                else "Treat a rapidly spreading rash, facial swelling, or breathing difficulty after a new medicine or food as urgent.",
                "ত্বক উঠে যাওয়া, মুখে ঘা বা ব্যাপক ব্যথাযুক্ত র‍্যাশ হলে দ্রুত চিকিৎসা নিন।"
                if self._is_bangla(language)
                else "Seek prompt review for skin peeling, mouth sores, or a widespread painful rash.",
            ],
            "endocrinology": [
                "রক্তে শর্করা খুব বেশি বা খুব কম হওয়ার লক্ষণ, বিশেষ করে বিভ্রান্তি, তীব্র দুর্বলতা বা পানিশূন্যতা থাকলে দ্রুত পর্যালোচনা দরকার।"
                if self._is_bangla(language)
                else "Urgent review is appropriate for symptoms of very high or very low blood sugar, especially confusion, severe weakness, or dehydration.",
                "অবিরাম বমি, অস্বাভাবিক ঝিমুনি বা দ্রুত শ্বাসের সঙ্গে বিপাকীয় অসামঞ্জস্যের সন্দেহ হলে দ্রুত চিকিৎসা নিন।"
                if self._is_bangla(language)
                else "Seek prompt care for persistent vomiting, marked drowsiness, or rapid breathing with suspected metabolic imbalance.",
            ],
        }
        selected = category_flags.get(category_key, default_flags)
        if severity >= 8:
            return selected[:2] + default_flags[:1]
        return selected[:2]

    def _build_default_follow_up_questions(
        self,
        symptoms: list[str],
        diagnosis: str | None = None,
        medications: list[dict] | None = None,
        report_findings: list[dict] | None = None,
        document_summary: str | None = None,
        language: str = "en",
    ) -> list[str]:
        clean_symptoms = [str(item).strip() for item in symptoms if str(item).strip()]
        symptom_text = self._normalize_text(" ".join(clean_symptoms))
        diagnosis_text = str(diagnosis or "").strip()
        med_names = [
            str(item.get("name") or item.get("medication_name") or "").strip()
            for item in (medications or [])
            if isinstance(item, dict) and str(item.get("name") or item.get("medication_name") or "").strip()
        ]
        normalized_findings = self._normalize_report_findings(report_findings)
        abnormal_finding_names = [
            str(item.get("test_name") or "").strip()
            for item in normalized_findings
            if str(item.get("status") or "").strip().lower() in {"abnormal", "borderline"}
            and str(item.get("test_name") or "").strip()
        ]
        kidney_finding_names = [
            item
            for item in abnormal_finding_names
            if self._contains_any(
                self._normalize_text(item),
                ["creatinine", "urea", "renal", "kidney", "sodium", "potassium", "electrolyte"],
            )
        ]
        document_context_text = self._normalize_text(
            " ".join(
                [
                    diagnosis_text,
                    str(document_summary or "").strip(),
                    " ".join(med_names[:4]),
                    " ".join(abnormal_finding_names[:3]),
                ]
            )
        )
        questions: list[str] = []
        seen_intents: set[str] = set()
        seen_text: set[str] = set()

        def add(intent: str, question: str) -> None:
            text = self._localize_follow_up_question(str(question or "").strip(), language)
            if not text:
                return
            if intent in seen_intents:
                return
            key = text.lower()
            if key in seen_text:
                return
            seen_intents.add(intent)
            seen_text.add(key)
            questions.append(text)

        combined_context_text = self._normalize_text(
            " ".join(
                clean_symptoms
                + [diagnosis_text]
                + abnormal_finding_names
                + [str(document_summary or "").strip()]
            )
        )
        has_pain_pattern = self._contains_any(
            symptom_text,
            ["pain", "ache", "cramp", "burning", "pressure", "tightness"],
        )
        has_renal_pattern = self._contains_any(
            combined_context_text,
            [
                "kidney",
                "renal",
                "stone",
                "calculi",
                "urology",
                "urolithiasis",
                "flank",
                "urine",
                "urinary",
                "hematuria",
                "dysuria",
                "nephrolithotomy",
            ],
        )
        has_fever_pattern = self._contains_any(
            combined_context_text,
            ["fever", "temperature", "chill", "chills", "shivering"],
        )
        has_nausea_pattern = self._contains_any(
            combined_context_text,
            ["nausea", "vomiting", "vomit"],
        )
        has_duration_context = any(
            token in combined_context_text
            for token in [
                "today",
                "yesterday",
                "hour",
                "hours",
                "day",
                "days",
                "week",
                "weeks",
                "month",
                "months",
                "since",
            ]
        )

        if has_renal_pattern:
            if has_duration_context:
                add(
                    "onset_course",
                    "Since the kidney pain or fever started, have the symptoms been getting worse, improving, or coming in waves?",
                )
            else:
                add(
                    "onset_course",
                    "When did the kidney pain and fever start, and have they been getting worse, improving, or coming in waves?",
                )
            if has_pain_pattern:
                add(
                    "pain_detail",
                    "Where exactly is the pain, does it move toward the groin, and how severe is it on a 0 to 10 scale?",
                )
            add(
                "urinary_changes",
                "Have you had burning urine, blood in urine, reduced urine output, urgency, or difficulty passing urine?",
            )
            if has_fever_pattern or kidney_finding_names:
                add(
                    "fever_systemic",
                    "What temperature have you measured, and have you had chills, shivering, or felt markedly unwell with it?",
                )
            add(
                "associated_symptoms",
                "Have you had nausea or vomiting, and are you able to keep fluids down?",
            )
            if self._contains_any(
                self._normalize_text(diagnosis_text),
                ["stone", "calculi", "urolithiasis", "nephrolithotomy"],
            ) or self._contains_any(document_context_text, ["usg", "ultrasound", "ct", "scan", "x ray", "xray"]):
                add(
                    "imaging_history",
                    "Have you had a recent ultrasound or CT scan, or a previous stone episode, and what did it show?",
                )
            elif kidney_finding_names:
                highlighted_findings = ", ".join(kidney_finding_names[:2])
                add(
                    "lab_correlation",
                    f"Since the {highlighted_findings} results were abnormal, have you noticed swelling, poor appetite, increasing weakness, or less urine than usual?",
                )
            if len(questions) < 5 and (med_names or diagnosis_text):
                add(
                    "medication_response",
                    "Have you taken any pain medicine or prescribed treatment for this, and did it help even temporarily?",
                )
            return questions[:6]

        if has_duration_context:
            add("onset_course", "Since these symptoms started, have they been constant, coming and going, or clearly getting worse?")
        else:
            add("onset_course", "When exactly did these symptoms start, and have they been constant or coming and going?")

        if has_pain_pattern:
            add("pain_detail", "Where is the discomfort worst right now, does it spread anywhere, and how severe is it on a 0 to 10 scale?")

        if abnormal_finding_names:
            highlighted_findings = ", ".join(abnormal_finding_names[:2])
            add(
                "lab_correlation",
                f"Have you noticed symptoms that may relate to the {highlighted_findings} result, such as weakness, dizziness, swelling, or appetite change?"
            )
        elif normalized_findings or document_summary:
            add("lab_correlation", "Were any recent report values marked high or low, and did your current symptoms begin before or after those results?")

        has_cardiac_pattern = self._contains_any(
            symptom_text,
            ["chest pain", "chest pressure", "palpitation", "heart", "syncope"],
        )
        if self._contains_any(
            symptom_text,
            ["chest pain", "chest pressure", "palpitation", "heart", "syncope"],
        ):
            add("pain_detail", "Is the chest discomfort triggered by exertion or stress, and does it spread to your arm, jaw, back, or shoulder?")
            add("associated_symptoms", "Have you had sweating, nausea, palpitations, fainting, or shortness of breath with it?")

        if self._contains_any(
            symptom_text,
            ["cough", "breath", "breathless", "shortness of breath", "wheeze", "wheezing", "phlegm", "sputum"],
        ) and not has_cardiac_pattern:
            add("triggers_relief", "Is the cough or breathing problem worse at night, with walking, or when lying flat?")
            add("associated_symptoms", "Have you had wheezing, fever, chest tightness, or low oxygen readings with this episode?")

        if self._contains_any(
            symptom_text,
            ["stomach", "abdominal", "abdomen", "vomit", "vomiting", "nausea", "diarrhea", "constipation", "stool"],
        ):
            add("associated_symptoms", "Is the abdominal problem related to meals or bowel movements, and have you had vomiting, diarrhea, constipation, or black stool?")

        if self._contains_any(
            symptom_text,
            ["headache", "dizzy", "dizziness", "weakness", "numb", "speech", "vision", "seizure"],
        ):
            add("associated_symptoms", "Did the headache or neurological symptom start suddenly or gradually, and have you had weakness, numbness, speech change, or vision problems?")

        if self._contains_any(
            symptom_text,
            ["kidney", "renal", "stone", "flank", "urine", "urinary", "urology", "dysuria", "hematuria"],
        ):
            add("urinary_changes", "Does the pain move from your side or back toward the groin, and have you had burning urine, blood in urine, fever, or reduced urine output?")

        if self._contains_any(
            symptom_text,
            ["rash", "itch", "itching", "skin", "hives", "blister", "swelling", "eruption"],
        ):
            add("onset_course", "When did the skin change start, where did it begin, and is it itchy, painful, blistering, or spreading?")

        if self._contains_any(
            symptom_text,
            ["diabetes", "thyroid", "sugar", "glucose", "endocrine", "thirst", "urination", "weight loss", "weight gain"],
        ) or self._contains_any(document_context_text, ["diabetes", "thyroid", "glucose", "hba1c"]):
            add("associated_symptoms", "Have you noticed increased thirst, frequent urination, unusual sweating, tremor, or recent weight or appetite change?")

        if med_names or diagnosis_text or self._contains_any(document_context_text, ["prescription", "medication", "tablet", "capsule"]):
            medicine_label = med_names[0] if len(med_names) == 1 else (
                "আপনার নির্ধারিত ওষুধগুলো" if self._is_bangla(language) else "your prescribed medicines"
            )
            add(
                "medication_response",
                (
                    f"{medicine_label} শুরু করার পর উপসর্গ কমেছে, বেড়েছে, নাকি কোনো পার্শ্বপ্রতিক্রিয়া হয়েছে?"
                    if self._is_bangla(language)
                    else f"Since starting {medicine_label}, have the symptoms improved, worsened, or caused any side effects?"
                )
            )

        if diagnosis_text:
            add(
                "diagnosis_change",
                (
                    f"এটি {diagnosis_text}-এর সঙ্গে সম্পর্কিত হতে পারে বলা হওয়ার পর থেকে কি কোনো পরিবর্তন হয়েছে?"
                    if self._is_bangla(language)
                    else f"Has anything changed since you were told this may be related to {diagnosis_text}?"
                ),
            )

        add("triggers_relief", "What clearly makes the main symptom worse or better, such as movement, food, deep breathing, rest, or stress?")
        add("medication_response", "Have you taken any treatment so far, and did it help even temporarily?")
        add("red_flags", "Are you having any warning signs right now such as fever, bleeding, fainting, severe breathlessness, or rapidly worsening pain?")
        return questions[:6]

    @staticmethod
    def _is_low_value_follow_up_question(question: str) -> bool:
        text = DoctorRecommendationService._normalize_text(str(question or ""))
        if not text:
            return True
        generic_patterns = [
            "anything else",
            "tell me more",
            "can you elaborate",
            "any other symptoms",
            "additional information",
            "anything more",
        ]
        return any(pattern in text for pattern in generic_patterns)

    @staticmethod
    def _follow_up_question_intent(question: str) -> str:
        text = DoctorRecommendationService._normalize_text(str(question or ""))
        if not text:
            return "general"

        intent_patterns = [
            ("onset_course", ["when did", "since these symptoms started", "coming and going", "getting worse", "coming in waves"]),
            ("pain_detail", ["0 to 10 scale", "where is the discomfort", "where exactly is the pain", "does it spread", "toward the groin"]),
            ("urinary_changes", ["urine", "urinary", "passing urine", "blood in urine", "burning urine", "reduced urine output"]),
            ("fever_systemic", ["temperature", "fever", "chills", "shivering"]),
            ("associated_symptoms", ["nausea", "vomiting", "wheezing", "shortness of breath", "tightness", "weakness", "appetite change"]),
            ("lab_correlation", ["report values", "results were abnormal", "result, such as", "result such as"]),
            ("imaging_history", ["imaging", "ultrasound", "ct scan", "x ray", "stone episode"]),
            ("medication_response", ["starting your", "taken any treatment", "prescribed medicines", "medicine change", "did it help"]),
            ("diagnosis_change", ["related to"]),
            ("triggers_relief", ["worse or better", "triggered by", "worse at night"]),
            ("red_flags", ["warning signs right now"]),
        ]
        for intent, patterns in intent_patterns:
            if any(pattern in text for pattern in patterns):
                return intent
        return "general"

    def _ensure_doctor_style_follow_up_questions(
        self,
        questions: list[str],
        language: str = "en",
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        seen_intents: set[str] = set()
        for raw in questions or []:
            base_text = str(raw or "").strip()
            if not base_text:
                continue

            lowered = base_text.lower()
            text = base_text
            if "what imaging studies do i need" in lowered or ("imaging" in lowered and "do i need" in lowered):
                text = "Have you had any recent imaging studies (ultrasound, CT, or X-ray), and what were the results?"
            elif "lifestyle changes i should consider" in lowered or ("lifestyle" in lowered and "should i" in lowered):
                text = "Have there been any recent diet, hydration, or lifestyle changes that affect your symptoms?"
            elif "what medications should i" in lowered or ("medication" in lowered and "should i" in lowered):
                text = "What medications are you taking now, and did any medicine change your symptoms?"
            elif "changes in urination" in lowered:
                text = "Have you noticed burning urine, blood in urine, reduced urine output, or difficulty passing urine?"
            elif "current temperature" in lowered:
                text = "What temperature have you measured, and have you had chills or shivering with it?"
            elif "is the pain constant or does it come and go" in lowered:
                text = "Is the pain steady, or does it come in waves, and is it becoming more severe?"

            text = text.replace(" do I ", " do you ").replace(" should I ", " should you ")
            text = text.replace(" my ", " your ").replace(" I ", " you ")

            if not text.endswith("?"):
                text = f"{text.rstrip('.')}?"

            intent = DoctorRecommendationService._follow_up_question_intent(text)
            text = self._localize_follow_up_question(text, language)
            key = text.lower()
            if key in seen:
                continue
            if intent != "general" and intent in seen_intents:
                continue
            seen.add(key)
            seen_intents.add(intent)
            normalized.append(text)
            if len(normalized) >= 6:
                break
        return normalized

    @staticmethod
    def _split_text_sentences(value: str) -> list[str]:
        text = DoctorRecommendationService._clean_generated_text(value)
        if not text:
            return []
        sentences = re.split(r"(?<=[.!?])\s+", text)
        cleaned = [segment.strip(" -") for segment in sentences if segment.strip(" -")]
        return cleaned or ([text] if text else [])

    def _condense_generated_text(
        self,
        value: Any,
        *,
        fallback: str = "",
        max_sentences: int = 1,
        max_words: int = 24,
    ) -> str:
        sentences = self._split_text_sentences(value)
        candidates = [item for item in sentences if not self._is_low_value_follow_up_question(item)]
        text = " ".join((candidates or sentences)[: max(1, max_sentences)]).strip()
        if not text:
            text = self._clean_generated_text(fallback)
        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words]).rstrip(" ,;:.")
        if not text:
            return ""
        if text[-1] not in ".!?":
            text = f"{text}."
        return text

    def _sanitize_short_list(
        self,
        value: Any,
        *,
        max_items: int,
        max_words: int,
    ) -> list[str]:
        items = self._coerce_string_list(value)
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            condensed = self._condense_generated_text(item, max_sentences=1, max_words=max_words)
            if not condensed:
                continue
            key = condensed.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(condensed)
            if len(cleaned) >= max_items:
                break
        return cleaned

    def _sanitize_question_list(self, value: Any) -> list[str]:
        questions = self._coerce_string_list(value)
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in questions:
            condensed = self._condense_generated_text(item, max_sentences=1, max_words=22)
            if not condensed:
                continue
            if not condensed.endswith("?"):
                condensed = f"{condensed.rstrip('.')}?"
            key = condensed.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(condensed)
            if len(cleaned) >= 6:
                break
        return cleaned

    def _sanitize_doctor_reasons(self, reasons: list[str]) -> list[str]:
        cleaned = self._sanitize_short_list(reasons, max_items=3, max_words=16)
        generic_noise = {
            "best doctor.",
            "best match.",
            "highly recommended.",
            "available soon.",
        }
        return [item for item in cleaned if item.lower() not in generic_noise][:3]

    def _sanitize_doctor_fit_summary(self, value: str) -> str:
        return self._condense_generated_text(
            value,
            fallback="",
            max_sentences=1,
            max_words=18,
        )

    def _merge_contextual_clinical_impression(
        self,
        existing: Any,
        context_sentence: str,
        language: str = "en",
    ) -> str:
        current = str(existing or "").strip()
        context = str(context_sentence or "").strip()
        if not current:
            return context
        if not context:
            return current
        if context.lower() in current.lower():
            return current
        if current[-1] not in ".!?":
            current = f"{current}."
        return f"{current} {context}"

    def _build_default_recommended_next_steps(
        self,
        recommended_specializations: list[str],
        urgency: str,
        language: str = "en",
    ) -> list[str]:
        next_steps: list[str] = []
        urgency_value = str(urgency or "").strip().lower()
        if urgency_value == "high":
            next_steps.append(
                "অবিলম্বে সরাসরি মূল্যায়নকে অগ্রাধিকার দিন; হঠাৎ অবনতি হলে জরুরি সেবা নিন।"
                if self._is_bangla(language)
                else "Prioritize immediate in-person evaluation; use emergency services for acute deterioration."
            )
        elif urgency_value == "moderate":
            next_steps.append(
                "আগামী ২৪ থেকে ৭২ ঘণ্টার মধ্যে বিশেষজ্ঞ পরামর্শের ব্যবস্থা করুন।"
                if self._is_bangla(language)
                else "Arrange specialist consultation within 24 to 72 hours."
            )
        else:
            next_steps.append(
                "রুটিন আউটপেশেন্ট বিশেষজ্ঞ পরামর্শের ব্যবস্থা করুন।"
                if self._is_bangla(language)
                else "Arrange routine outpatient specialist consultation."
            )

        spec = merge_specialties(recommended_specializations, include_fallback=False, limit=3)
        if spec:
            next_steps.append(
                f"লক্ষ্য বিশেষজ্ঞ বিভাগ: {', '.join(spec[:2])}।"
                if self._is_bangla(language)
                else f"Target specialist area: {', '.join(spec[:2])}."
            )
        next_steps.append(
            "পরামর্শে সাম্প্রতিক প্রেসক্রিপশন, রিপোর্ট এবং উপসর্গের সময়রেখা সঙ্গে আনুন।"
            if self._is_bangla(language)
            else "Bring recent prescriptions, reports, and symptom timeline to the consultation."
        )
        return next_steps[:4]

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed != parsed:  # NaN check without importing math
            return None
        return parsed

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            cleaned = [
                DoctorRecommendationService._clean_generated_text(item)
                for item in value
            ]
            return [item for item in cleaned if item]
        if isinstance(value, str):
            cleaned = DoctorRecommendationService._clean_generated_text(value)
            if cleaned:
                return [cleaned]
        return []

    @staticmethod
    def _coerce_analysis_context(preferences: dict | None) -> dict[str, Any]:
        if not isinstance(preferences, dict):
            return {}
        value = preferences.get("analysis_context")
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _merge_unique_strings(*collections: list[str], limit: int = 10) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for collection in collections:
            for item in collection:
                text = str(item).strip()
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(text)
                if len(merged) >= limit:
                    return merged
        return merged

    @staticmethod
    def _normalize_report_findings(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            test_name = normalize_report_test_name(str(item.get("test_name") or "").strip())
            if not test_name:
                continue
            ai_analysis = str(item.get("ai_analysis") or "").strip() or None
            if is_low_value_report_analysis(ai_analysis, test_name):
                ai_analysis = None
            normalized.append(
                {
                    "test_name": test_name,
                    "observed_value": str(item.get("observed_value") or "").strip() or None,
                    "reference_range": str(item.get("reference_range") or "").strip() or None,
                    "status": str(item.get("status") or "unknown").strip().lower() or "unknown",
                    "ai_analysis": ai_analysis,
                    "source_document": str(item.get("source_document") or "").strip() or None,
                }
            )
        return normalized[:15]

    def _build_default_prescription_analysis(
        self,
        medications: list[dict] | None,
        diagnosis: str | None,
        instructions: str | None,
        warnings: list[str] | None,
        language: str = "en",
    ) -> dict[str, Any]:
        meds = medications or []
        medication_breakdown: list[dict[str, Any]] = []
        for med in meds[:10]:
            name = self._clean_generated_text(med.get("name") or med.get("medication_name"))
            if not name:
                continue

            treated = self._clean_generated_text(med.get("purpose") or med.get("condition_treated")) or None
            why_prescribed = self._clean_generated_text(med.get("why_prescribed")) or self._infer_medication_rationale(
                name,
                treated,
                diagnosis,
            )
            how_it_works = self._clean_generated_text(med.get("how_it_works")) or None
            key_instructions = self._clean_generated_text(med.get("key_instructions") or instructions) or None
            things_to_know = self._sanitize_short_list(
                med.get("things_to_know"),
                max_items=4,
                max_words=16,
            )
            ai_analysis = self._condense_generated_text(
                med.get("ai_analysis"),
                fallback=why_prescribed or "",
                max_sentences=2,
                max_words=36,
            ) or None
            suggested_for = self._build_medication_suggested_for(
                suggested_for=med.get("suggested_for"),
                condition_treated=treated,
                why_prescribed=why_prescribed,
                ai_analysis=ai_analysis,
                language=language,
            )
            medication_breakdown.append(
                {
                    "medication_name": name,
                    "generic_name": self._clean_generated_text(med.get("generic_name")) or None,
                    "drug_class": self._clean_generated_text(med.get("drug_class")) or None,
                    "condition_treated": treated,
                    "why_prescribed": why_prescribed,
                    "how_it_works": how_it_works,
                    "key_instructions": key_instructions,
                    "things_to_know": things_to_know,
                    "suggested_for": suggested_for,
                    "ai_analysis": suggested_for,
                }
            )

        return {
            "medication_breakdown": medication_breakdown,
            "overall_assessment": None,
            "interaction_alerts": [],
            "contraindication_flags": self._sanitize_short_list(
                warnings or [],
                max_items=6,
                max_words=20,
            ),
        }

    def _build_default_report_analysis(
        self,
        report_findings: list[dict] | None,
        document_summary: str | None,
        language: str = "en",
    ) -> dict[str, Any]:
        normalized_findings = self._normalize_report_findings(report_findings)
        lab_findings: list[dict[str, Any]] = []
        for finding in normalized_findings[:12]:
            test_name = normalize_report_test_name(finding["test_name"])
            observed_value = str(finding.get("observed_value") or "").strip()
            reference_range = str(finding.get("reference_range") or "").strip()
            status = str(finding.get("status") or "unknown").strip().lower() or "unknown"

            ai_analysis = self._sanitize_report_finding_analysis(
                finding.get("ai_analysis"),
                test_name=test_name,
                observed_value=observed_value,
                reference_range=reference_range,
                status=status,
                language=language,
            )

            lab_findings.append(
                {
                    "test_name": test_name,
                    "observed_value": observed_value or None,
                    "reference_range": reference_range or None,
                    "status": status,
                    "ai_analysis": ai_analysis or "",
                    "source_document": finding.get("source_document"),
                }
            )

        noteworthy_findings = [
            finding
            for finding in lab_findings
            if self._is_report_status_noteworthy(finding.get("status"))
        ]
        return {
            "lab_findings": lab_findings,
            "overall_assessment": self._clean_generated_text(document_summary) or None,
            "patient_action_summary": [],
            "noteworthy_findings": noteworthy_findings,
        }

    def _build_default_medication_brief_analysis(
        self,
        name: str,
        treated: str | None,
        diagnosis: str | None,
        language: str = "en",
    ) -> str | None:
        return None

    def _build_default_report_finding_brief_analysis(
        self,
        test_name: str,
        observed_value: str | None,
        reference_range: str | None,
        status: str,
        language: str = "en",
    ) -> str:
        return ""

    @staticmethod
    def _infer_medication_rationale(
        name: str,
        treated: str | None,
        diagnosis: str | None,
    ) -> str | None:
        medication_name = str(name or "").strip() or "This medicine"
        treated_text = str(treated or "").strip()
        diagnosis_text = str(diagnosis or "").strip()

        if treated_text and diagnosis_text:
            if treated_text.casefold() == diagnosis_text.casefold():
                return f"This medicine was likely included to address {treated_text}."
            return (
                f"This medicine was likely included to address {treated_text} while the "
                f"prescriber managed the broader plan for {diagnosis_text}."
            )

        if treated_text:
            return f"This medicine was likely included to address {treated_text}."

        if diagnosis_text:
            return (
                f"The exact purpose of {medication_name} could not be confirmed from the "
                f"prescription alone and should be reviewed directly against the diagnosis "
                f"of {diagnosis_text}."
            )

        return None

    @staticmethod
    def _infer_condition_from_medication_name(name: str, diagnosis: str | None) -> str | None:
        # No hardcoded mappings - rely on AI to generate analysis dynamically
        return None

    @staticmethod
    def _infer_medication_concerns(name: str, warnings: list[str]) -> tuple[list[str], str | None]:
        normalized = str(name or "").strip().lower()
        side_effects: list[str] = []
        interaction_note = ""

        if any(token in normalized for token in ["ibuprofen", "naproxen", "diclofenac"]):
            side_effects = ["stomach irritation", "heartburn", "kidney strain in vulnerable patients"]
            interaction_note = "Use caution with ulcers, kidney disease, or other painkillers that can irritate the stomach."
        elif any(token in normalized for token in ["amoxicillin", "azithromycin", "ciprofloxacin", "doxycycline"]):
            side_effects = ["upset stomach", "diarrhea", "rash"]
            interaction_note = "Antibiotics should usually be completed as prescribed and reviewed if rash or severe diarrhea develops."
        elif any(token in normalized for token in ["cetirizine", "loratadine", "fexofenadine"]):
            side_effects = ["sleepiness", "dry mouth", "mild dizziness"]
            interaction_note = "Use caution with alcohol or other medicines that can increase drowsiness."
        elif any(token in normalized for token in ["metformin", "glimepiride", "insulin"]):
            side_effects = ["stomach upset", "low blood sugar symptoms", "reduced appetite"]
            interaction_note = "Watch for sweating, shakiness, or confusion if blood sugar drops too low."
        elif any(token in normalized for token in ["amlodipine", "losartan", "atenolol", "metoprolol"]):
            side_effects = ["dizziness", "light-headedness", "fatigue"]
            interaction_note = "Blood-pressure medicines can worsen dehydration or low blood pressure in some situations."
        elif any(token in normalized for token in ["pantoprazole", "omeprazole", "esomeprazole"]):
            side_effects = ["bloating", "nausea", "headache"]
            interaction_note = "Stomach-acid medicines are often timed around meals or used to reduce irritation from other medicines."
        elif any(token in normalized for token in ["salbutamol", "albuterol", "formoterol"]):
            side_effects = ["tremor", "palpitations", "feeling jittery"]
            interaction_note = "Seek review if breathing symptoms worsen despite treatment."

        if warnings:
            warning_text = "; ".join(warnings[:3])
            interaction_note = f"{interaction_note} Document precautions: {warning_text}".strip()

        return side_effects[:4], interaction_note or None

    def _build_external_preview_reasons(
        self,
        candidate: dict[str, Any],
        symptom_analysis: dict[str, Any],
        language: str = "en",
    ) -> list[str]:
        reasons: list[str] = []
        primary_category = str(symptom_analysis.get("primary_category") or "general").strip() or "general"
        urgency = str(symptom_analysis.get("urgency") or "low").strip() or "low"
        symptoms = self._coerce_string_list(symptom_analysis.get("symptom_descriptions"))[:3]

        doctor_specs = self._coerce_string_list(candidate.get("specialization"))
        recommended_specs = self._coerce_string_list(symptom_analysis.get("recommended_specializations"))
        normalized_recommended = {self._normalize_text(item) for item in recommended_specs}
        overlapping_specs = [
            spec
            for spec in doctor_specs
            if self._normalize_text(spec) in normalized_recommended
        ]

        if overlapping_specs:
            reasons.append(
                (
                    f"বিশেষজ্ঞতার মিল: {', '.join(overlapping_specs[:2])} আপনার {self._category_display(primary_category, language)} উপসর্গের সঙ্গে মানানসই।"
                    if self._is_bangla(language)
                    else f"Specialization match: {', '.join(overlapping_specs[:2])} aligns with your {primary_category} symptom profile."
                )
            )
        elif doctor_specs:
            reasons.append(
                (
                    f"{', '.join(doctor_specs[:2])}-এ ডাক্তারের অভিজ্ঞতা আপনার {self._category_display(primary_category, language)} উপসর্গের জন্য প্রাসঙ্গিক।"
                    if self._is_bangla(language)
                    else f"Doctor focus in {', '.join(doctor_specs[:2])} is relevant to the reported {primary_category} symptoms."
                )
            )

        experience_years = self._coerce_float(candidate.get("experience_years"))
        if experience_years and experience_years >= 1:
            exp_label = int(experience_years) if experience_years.is_integer() else round(experience_years, 1)
            reasons.append(
                (
                    f"{exp_label} বছরের অভিজ্ঞতা {self._urgency_display(urgency, language)} অগ্রাধিকারের এই সমস্যার লক্ষ্যভিত্তিক মূল্যায়নে সহায়ক হতে পারে।"
                    if self._is_bangla(language)
                    else f"{exp_label} years of experience can support targeted evaluation for {urgency} priority concerns."
                )
            )

        if symptoms:
            reasons.append(
                (
                    f"বিবেচিত উপসর্গ: {', '.join(symptoms[:2])}; এগুলো এই বিশেষজ্ঞ পথকে সমর্থন করে।"
                    if self._is_bangla(language)
                    else f"Symptom signals considered: {', '.join(symptoms[:2])}, supporting this specialist route."
                )
            )

        if not reasons:
            reasons.append(
                "বর্তমান উপসর্গের প্রোফাইল ও জরুরিতা বিবেচনায় এই বিশেষজ্ঞকে উপযুক্ত মনে হয়েছে।"
                if self._is_bangla(language)
                else "Selected as a suitable specialist based on the current symptom profile and urgency."
            )
        return reasons[:3]

    def _build_external_fit_summary(
        self,
        candidate: dict[str, Any],
        symptom_analysis: dict[str, Any],
        language: str = "en",
    ) -> str:
        primary_category = str(symptom_analysis.get("primary_category") or "general").strip() or "general"
        urgency = str(symptom_analysis.get("urgency") or "low").strip() or "low"
        symptoms = self._coerce_string_list(symptom_analysis.get("symptom_descriptions"))[:2]
        doctor_specs = self._coerce_string_list(candidate.get("specialization"))
        spec_hint = doctor_specs[0] if doctor_specs else "specialist"
        symptom_hint = f" for {', '.join(symptoms)}" if symptoms else ""
        if self._is_bangla(language):
            symptom_text = f" ({', '.join(symptoms)})" if symptoms else ""
            return (
                f"{spec_hint} বিশেষজ্ঞ সেবা আপনার {self._category_display(primary_category, language)} সমস্যার"
                f"{symptom_text} সঙ্গে মানানসই এবং বর্তমান {self._urgency_display(urgency, language)} অগ্রাধিকারের সঙ্গে সামঞ্জস্যপূর্ণ।"
            )
        return (
            f"Recommended because {spec_hint} care aligns with your {primary_category} concerns{symptom_hint} "
            f"and current {urgency} urgency level."
        )
