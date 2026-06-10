import asyncio
from functools import lru_cache
from io import BytesIO
from typing import Annotated, Any, Awaitable, Callable
import json
import logging
from pathlib import Path
import re
import time

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.api.deps import get_current_active_user, ip_rate_limit
from app.ai.medical_prompts import normalize_response_language
from app.core.config import settings
from app.db.session import get_db
from app.models.recommendation import DoctorRecommendation
from app.models.user import User
from app.schemas.recommendation import (
    ExternalDoctorPreviewRequest,
    ExternalDoctorPreviewResponse,
    RecommendationRecordResponse,
    RecommendationRequest,
    RecommendationResponse,
    ReportFindingExplanationRequest,
    ReportFindingExplanationResponse,
)
from app.services.document_analysis_cache_service import DocumentAnalysisCacheService
from app.services.doctor_recommendation_service import DoctorRecommendationService
from app.services.prescription_analyzer_service import PrescriptionAnalyzerService
from app.services.storage_service import StorageService

router = APIRouter()
logger = logging.getLogger(__name__)


@lru_cache
def get_doctor_recommendation_service() -> DoctorRecommendationService:
    return DoctorRecommendationService()


@lru_cache
def get_prescription_analyzer_service() -> PrescriptionAnalyzerService:
    return PrescriptionAnalyzerService()


@lru_cache
def get_storage_service() -> StorageService | None:
    try:
        return StorageService()
    except RuntimeError as exc:
        logger.warning("Storage service initialization deferred: %s", exc)
        return None


@lru_cache
def get_document_analysis_cache_service() -> DocumentAnalysisCacheService:
    return DocumentAnalysisCacheService()


def _build_public_doctor_payload(payload: dict) -> dict:
    return {
        "id": payload.get("id"),
        "doctor_id": payload.get("doctor_id"),
        "doctorId": payload.get("doctorId") or payload.get("doctor_id"),
        "name": payload.get("name"),
        "specialization": payload.get("specialization", []),
        "hospital_id": payload.get("hospital_id"),
        "experience_years": payload.get("experience_years", 0),
        "average_rating": payload.get("average_rating", 0.0),
        "image_url": payload.get("image_url"),
        "imageUrl": payload.get("imageUrl"),
        "imagePath": payload.get("imagePath"),
        "fileMetadata": payload.get("fileMetadata"),
        "avatar": payload.get("avatar"),
        "credentials": payload.get("credentials"),
        "servesFor": payload.get("servesFor", []),
        "about": payload.get("about", ""),
        "education": payload.get("education", []),
        "locations": payload.get("locations", []),
        "hospitalName": payload.get("hospitalName"),
        "hospitalAddress": payload.get("hospitalAddress"),
        "contactNumber": payload.get("contactNumber"),
        "isActive": payload.get("isActive"),
        "match_score": payload.get("match_score", 0.0),
        "rank": payload.get("rank"),
        "reasons": payload.get("reasons", []),
        "fit_summary": payload.get("fit_summary", ""),
        "reasoning_source": payload.get("reasoning_source", "rules"),
        "details": payload.get("details", {}),
    }


def _build_patient_profile(symptom_analysis: dict) -> dict:
    analysis = symptom_analysis or {}
    return {
        "primary_category": analysis.get("primary_category", "general"),
        "severity": analysis.get("severity", 0),
        "urgency": analysis.get("urgency", "low"),
        "symptoms": analysis.get("symptom_descriptions", []),
        "recommended_specializations": analysis.get("recommended_specializations", []),
        "keyword_hits": analysis.get("keyword_hits", []),
        "triage_note": analysis.get("triage_note", ""),
        "profile_summary": analysis.get("profile_summary", ""),
        "analysis_source": analysis.get("analysis_source", "rules"),
        "additional_information": analysis.get("additional_information", []),
        "additional_information_assessment": analysis.get("additional_information_assessment", ""),
        "clinical_impression": analysis.get("clinical_impression", ""),
        "likely_concerns": analysis.get("likely_concerns", []),
        "immediate_actions": analysis.get("immediate_actions", []),
        "red_flags_to_watch": analysis.get("red_flags_to_watch", []),
        "follow_up_questions": analysis.get("follow_up_questions", []),
        "recommended_next_steps": analysis.get("recommended_next_steps", []),
    }


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse_symptoms_json(symptoms_json: str) -> list[str]:
    try:
        symptoms = json.loads(symptoms_json)
        if not isinstance(symptoms, list):
            raise ValueError
        parsed = [str(item).strip() for item in symptoms if str(item).strip()]
    except Exception as exc:
        raise HTTPException(status_code=400, detail="symptoms_json must be a JSON array of strings") from exc

    if not parsed:
        raise HTTPException(status_code=400, detail="At least one symptom is required")
    return parsed


def _parse_preferences_json(preferences_json: str) -> dict[str, Any]:
    try:
        preferences = json.loads(preferences_json) if preferences_json else {}
        if not isinstance(preferences, dict):
            return {}
        return preferences
    except Exception:
        return {}


def _create_upload_clone(file_name: str, content_type: str | None, file_bytes: bytes) -> UploadFile:
    headers = Headers({"content-type": content_type or "application/octet-stream"})
    return UploadFile(
        file=BytesIO(file_bytes),
        filename=file_name,
        headers=headers,
    )


def _format_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event_name}\ndata: {serialized}\n\n"


async def _analyze_uploaded_document(
    file: UploadFile,
    analyzer_service: PrescriptionAnalyzerService,
    storage_service: StorageService,
    cache_service: DocumentAnalysisCacheService,
    db: Session | None,
    document_kind: str,
    storage_user_id: str = "public-preview",
    language: str = "en",
) -> dict[str, Any]:
    file_name = file.filename or ""
    suffix = Path(file_name).suffix.lower() or ".tmp"
    normalized_language = normalize_response_language(language)
    file_bytes = await file.read()
    await file.seek(0)
    if not file_bytes:
        raise RuntimeError("Uploaded file is empty and cannot be processed.")

    content_hash = cache_service.hash_bytes(file_bytes)
    vision_model = settings.OPENAI_VISION_MODEL
    prompt_version = settings.OPENAI_VISION_PROMPT_VERSION
    cache_lookup_started_at = time.monotonic()
    cached_payload = cache_service.get_cached_analysis(
        db=db,
        content_hash=content_hash,
        document_kind=document_kind,
        language=normalized_language,
        vision_model=vision_model,
        prompt_version=prompt_version,
    )
    cache_lookup_duration_ms = int((time.monotonic() - cache_lookup_started_at) * 1000)
    cache_hit = isinstance(cached_payload, dict) and bool(cached_payload)

    upload_file = _create_upload_clone(file_name, file.content_type, file_bytes)
    upload_started_at = time.monotonic()
    upload_task = asyncio.create_task(storage_service.upload_file(upload_file, storage_user_id))

    parsed: dict[str, Any] = {}
    vision_duration_ms = 0
    if cache_hit:
        parsed = dict(cached_payload or {})
        logger.info(
            "Document analysis cache hit kind=%s extension=%s hash=%s lookup_ms=%d",
            document_kind,
            suffix,
            content_hash[:12],
            cache_lookup_duration_ms,
        )
    else:
        processing_path = ""
        vision_started_at = time.monotonic()
        try:
            processing_path = StorageService._write_processing_bytes(file_bytes, suffix)
            parsed = await analyzer_service.analyze_prescription_image(
                processing_path,
                language=normalized_language,
            )
            cache_service.upsert_cached_analysis(
                db=db,
                content_hash=content_hash,
                document_kind=document_kind,
                language=normalized_language,
                vision_model=vision_model,
                prompt_version=prompt_version,
                analysis_payload=parsed,
            )
        finally:
            if processing_path:
                await StorageService.cleanup_processing_file(processing_path, True)
        vision_duration_ms = int((time.monotonic() - vision_started_at) * 1000)
        logger.info(
            "Document analysis cache miss kind=%s extension=%s hash=%s lookup_ms=%d vision_ms=%d",
            document_kind,
            suffix,
            content_hash[:12],
            cache_lookup_duration_ms,
            vision_duration_ms,
        )

    try:
        file_url = await upload_task
    finally:
        await upload_file.close()
    upload_duration_ms = int((time.monotonic() - upload_started_at) * 1000)

    extracted_conditions = await analyzer_service.extract_medical_conditions(parsed)
    reported_symptoms = [
        str(item).strip()
        for item in (parsed.get("reported_symptoms") or [])
        if str(item).strip()
    ]
    logger.info(
        (
            "Document processing completed kind=%s extension=%s hash=%s "
            "upload_ms=%d cache_lookup_ms=%d vision_ms=%d cache_hit=%s"
        ),
        document_kind,
        suffix,
        content_hash[:12],
        upload_duration_ms,
        cache_lookup_duration_ms,
        vision_duration_ms,
        cache_hit,
    )
    return {
        "file_name": file_name,
        "file_url": file_url,
        "parsed": parsed,
        "extracted_conditions": extracted_conditions,
        "reported_symptoms": reported_symptoms,
        "content_hash": content_hash,
        "cache_hit": cache_hit,
        "vision_model": vision_model,
        "prompt_version": prompt_version,
        "timings": {
            "upload_ms": upload_duration_ms,
            "cache_lookup_ms": cache_lookup_duration_ms,
            "vision_ms": vision_duration_ms,
        },
    }


def _build_prescription_context(file_analysis: dict[str, Any]) -> dict[str, Any]:
    parsed = file_analysis.get("parsed") or {}
    return {
        "file_name": file_analysis.get("file_name", ""),
        "file_url": file_analysis.get("file_url"),
        "document_type": parsed.get("document_type", "unknown"),
        "diagnosis": parsed.get("diagnosis"),
        "extracted_conditions": file_analysis.get("extracted_conditions", []),
        "confidence_score": parsed.get("confidence_score", 0.0),
        "doctor_name": parsed.get("doctor_name"),
        "doctor_specialization": parsed.get("doctor_specialization"),
        "prescription_date": parsed.get("prescription_date"),
        "instructions": parsed.get("instructions"),
        "follow_up": parsed.get("follow_up"),
        "reported_symptoms": file_analysis.get("reported_symptoms", []),
        "medications": parsed.get("medications", []),
        "warnings": parsed.get("warnings", []),
        "analysis_summary": parsed.get("analysis_summary"),
        "vision_status": parsed.get("vision_status"),
        "analysis_source": parsed.get("analysis_source", "rules"),
    }


def _select_report_summary(parsed: dict[str, Any]) -> str | None:
    direct_summary = str(parsed.get("analysis_summary") or "").strip()
    if direct_summary:
        return direct_summary

    extraction_notes = str(parsed.get("extraction_notes") or "").strip()
    if not extraction_notes:
        return None

    normalized = re.sub(r"[^a-z0-9]+", " ", extraction_notes.lower()).strip()
    if normalized in {
        "typed report",
        "typed prescription",
        "handwritten report",
        "handwritten prescription",
    }:
        return None
    if len(normalized.split()) < 4 and not any(char.isdigit() for char in normalized):
        return None
    return extraction_notes


def _build_report_file_context(file_analysis: dict[str, Any]) -> dict[str, Any]:
    parsed = file_analysis.get("parsed") or {}
    report_findings: list[dict[str, Any]] = []
    for item in parsed.get("report_findings") or []:
        if not isinstance(item, dict):
            continue
        report_findings.append(
            {
                **item,
                "source_document": file_analysis.get("file_name", ""),
            }
        )

    return {
        "file_name": file_analysis.get("file_name", ""),
        "file_url": file_analysis.get("file_url"),
        "document_type": parsed.get("document_type", "unknown"),
        "confidence_score": parsed.get("confidence_score", 0.0),
        "analysis_summary": _select_report_summary(parsed),
        "reported_symptoms": file_analysis.get("reported_symptoms", []),
        "report_findings": report_findings,
        "vision_status": parsed.get("vision_status"),
        "analysis_source": parsed.get("analysis_source", "rules"),
    }


def _combine_report_contexts(report_entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not report_entries:
        return None

    aggregated_findings: list[dict[str, Any]] = []
    summaries: list[str] = []
    report_files: list[dict[str, Any]] = []
    for entry in report_entries:
        report_files.append(entry)
        summaries.extend(_coerce_string_list(entry.get("analysis_summary")))
        for finding in entry.get("report_findings") or []:
            if isinstance(finding, dict):
                aggregated_findings.append(finding)

    deduped_findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for finding in aggregated_findings:
        key = (
            f"{str(finding.get('source_document') or '').lower()}::"
            f"{str(finding.get('test_name') or '').lower()}::"
            f"{str(finding.get('observed_value') or '').lower()}"
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_findings.append(finding)

    return {
        "files": report_files,
        "report_findings": deduped_findings,
        "analysis_summary": " ".join(dict.fromkeys(summaries)).strip() or None,
    }


def _is_noteworthy_report_status(status: Any) -> bool:
    return str(status or "").strip().lower() in {"abnormal", "borderline", "critical"}


def _is_low_value_report_overall_assessment(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return True

    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if not normalized:
        return True

    low_value_phrases = {
        "no specific lab findings were provided in the report",
        "no specific lab findings were provided",
        "no lab findings were provided in the report",
        "no lab findings were provided",
        "no specific lab values were provided in the report",
        "no report findings were provided in the report",
        "no report findings were provided",
    }
    if normalized in low_value_phrases:
        return True

    tokens = set(normalized.split())
    return (
        "no" in tokens
        and "provided" in tokens
        and ({"lab", "finding"} <= tokens or {"report", "finding"} <= tokens)
    )


def _ensure_report_analysis_present(
    symptom_analysis: dict[str, Any],
    report_context: dict[str, Any] | None,
    *,
    language: str,
) -> dict[str, Any]:
    if not report_context:
        return symptom_analysis

    normalized_language = normalize_response_language(language)
    updated = dict(symptom_analysis or {})
    report_analysis = (
        dict(updated.get("report_analysis"))
        if isinstance(updated.get("report_analysis"), dict)
        else {}
    )
    raw_findings = (
        report_context.get("report_findings")
        if isinstance(report_context.get("report_findings"), list)
        else []
    )
    normalized_findings: list[dict[str, Any]] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown").strip().lower() or "unknown"
        ai_analysis = str(item.get("ai_analysis") or "").strip() if _is_noteworthy_report_status(status) else ""
        normalized_findings.append(
            {
                "test_name": (
                    str(item.get("test_name") or "").strip()
                    or ("ল্যাব ফলাফল" if normalized_language == "bn" else "Lab finding")
                ),
                "observed_value": str(item.get("observed_value") or "").strip() or None,
                "reference_range": str(item.get("reference_range") or "").strip() or None,
                "status": status,
                "ai_analysis": ai_analysis,
            }
        )

    existing_findings = (
        report_analysis.get("lab_findings")
        if isinstance(report_analysis.get("lab_findings"), list)
        else []
    )
    if not existing_findings and normalized_findings:
        report_analysis["lab_findings"] = normalized_findings
    elif not isinstance(report_analysis.get("lab_findings"), list):
        report_analysis["lab_findings"] = []

    report_analysis["noteworthy_findings"] = [
        finding
        for finding in (report_analysis.get("lab_findings") or [])
        if _is_noteworthy_report_status((finding or {}).get("status"))
    ]

    if not isinstance(report_analysis.get("patient_action_summary"), list):
        report_analysis["patient_action_summary"] = []
    else:
        report_analysis["patient_action_summary"] = [
            str(item).strip()
            for item in report_analysis.get("patient_action_summary") or []
            if str(item).strip()
        ][:3]

    context_summary = str(report_context.get("analysis_summary") or "").strip()
    has_any_report_findings = bool(report_analysis.get("lab_findings") or normalized_findings)
    overall_assessment = str(report_analysis.get("overall_assessment") or "").strip()
    if not has_any_report_findings and context_summary:
        overall_assessment = context_summary
    elif _is_low_value_report_overall_assessment(overall_assessment):
        overall_assessment = ""
    if not overall_assessment:
        overall_assessment = context_summary
    if not overall_assessment:
        overall_assessment = (
            "রিপোর্ট আপলোড হয়েছে, কিন্তু স্পষ্ট স্ট্রাকচার্ড মান বের করা যায়নি। পরিষ্কার কপি দিয়ে আবার আপলোড করলে বিশ্লেষণ উন্নত হবে।"
            if normalized_language == "bn"
            else "Report uploaded, but clear structured values could not be extracted. Re-uploading a clearer copy can improve analysis."
        )
    report_analysis["overall_assessment"] = overall_assessment

    updated["report_analysis"] = report_analysis
    return updated


async def _collect_uploaded_document_contexts(
    *,
    db: Session,
    analyzer_service: PrescriptionAnalyzerService,
    storage_service: StorageService,
    cache_service: DocumentAnalysisCacheService,
    prescription_file: UploadFile | None,
    report_files: list[UploadFile],
    legacy_file: UploadFile | None,
    language: str,
    emit_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    prescription_context: dict[str, Any] | None = None
    report_entries: list[dict[str, Any]] = []
    extracted_conditions: list[str] = []
    recent_diagnoses: list[str] = []
    reported_symptoms: list[str] = []
    medications: list[dict[str, Any]] = []
    document_summaries: list[str] = []
    prescription_instructions = None
    document_warnings: list[str] = []
    stage_timings: dict[str, dict[str, int]] = {}

    async def _run_document_analysis(
        current_file: UploadFile,
        document_kind: str,
        label: str,
    ) -> tuple[str, dict[str, Any]]:
        return (
            label,
            await _analyze_uploaded_document(
                current_file,
                analyzer_service=analyzer_service,
                storage_service=storage_service,
                cache_service=cache_service,
                db=db,
                document_kind=document_kind,
                language=language,
            ),
        )

    tasks: list[asyncio.Task[tuple[str, dict[str, Any]]]] = []
    if prescription_file is not None:
        tasks.append(
            asyncio.create_task(
                _run_document_analysis(
                    prescription_file,
                    document_kind="prescription",
                    label="prescription",
                )
            )
        )
    for index, report_file in enumerate(report_files or []):
        tasks.append(
            asyncio.create_task(
                _run_document_analysis(
                    report_file,
                    document_kind="report",
                    label=f"report:{index}",
                )
            )
        )
    if legacy_file is not None:
        tasks.append(
            asyncio.create_task(
                _run_document_analysis(
                    legacy_file,
                    document_kind="legacy",
                    label="legacy",
                )
            )
        )

    if not tasks:
        return {
            "prescription_context": None,
            "report_context": None,
            "extracted_conditions": [],
            "recent_diagnoses": [],
            "reported_symptoms": [],
            "medications": [],
            "prescription_instructions": None,
            "document_warnings": [],
            "document_summary": None,
            "timings": {},
        }

    for completed in asyncio.as_completed(tasks):
        label, analysis = await completed
        parsed = analysis.get("parsed") or {}
        stage_timings[label] = dict(analysis.get("timings") or {})
        extracted_conditions.extend(analysis.get("extracted_conditions") or [])
        reported_symptoms.extend(analysis.get("reported_symptoms") or [])
        if parsed.get("diagnosis"):
            recent_diagnoses.append(str(parsed.get("diagnosis")))
        summary_candidate = (
            _select_report_summary(parsed)
            if label.startswith("report:") or str(parsed.get("document_type") or "").strip().lower() == "report"
            else str(parsed.get("analysis_summary") or "").strip() or None
        )
        if summary_candidate:
            document_summaries.append(summary_candidate)

        if label == "prescription":
            prescription_context = _build_prescription_context(analysis)
            medications = parsed.get("medications") or []
            prescription_instructions = prescription_context.get("instructions")
            document_warnings.extend(_coerce_string_list(prescription_context.get("warnings")))
            if parsed.get("report_findings"):
                report_entries.append(_build_report_file_context(analysis))
            if emit_event is not None:
                await emit_event("prescription_context", {"prescription_context": prescription_context})
                if parsed.get("report_findings"):
                    await emit_event(
                        "report_context",
                        {"report_context": _combine_report_contexts(report_entries)},
                    )
            continue

        if label.startswith("report:"):
            report_entries.append(_build_report_file_context(analysis))
            if emit_event is not None:
                await emit_event(
                    "report_context",
                    {"report_context": _combine_report_contexts(report_entries)},
                )
            continue

        # Legacy upload can include prescription-like and/or report-like content.
        has_prescription_like_content = bool(
            parsed.get("medications")
            or parsed.get("instructions")
            or str(parsed.get("document_type") or "").strip().lower() in {"prescription", "mixed"}
        )
        has_report_like_content = bool(
            parsed.get("report_findings")
            or str(parsed.get("document_type") or "").strip().lower() in {"report", "mixed"}
        )
        if has_prescription_like_content:
            prescription_context = _build_prescription_context(analysis)
            medications = parsed.get("medications") or medications
            prescription_instructions = prescription_context.get("instructions")
            document_warnings.extend(_coerce_string_list(prescription_context.get("warnings")))
            if emit_event is not None:
                await emit_event("prescription_context", {"prescription_context": prescription_context})
        if has_report_like_content:
            report_entries.append(_build_report_file_context(analysis))
            if emit_event is not None:
                await emit_event(
                    "report_context",
                    {"report_context": _combine_report_contexts(report_entries)},
                )

    deduped_conditions = sorted(
        {
            str(item).strip().lower()
            for item in extracted_conditions
            if str(item).strip()
        }
    )
    cleaned_diagnoses = [str(item).strip() for item in recent_diagnoses if str(item).strip()]
    cleaned_reported_symptoms = [str(item).strip() for item in reported_symptoms if str(item).strip()]
    document_summary = " ".join(
        dict.fromkeys([item.strip() for item in document_summaries if item and item.strip()])
    ).strip() or None
    report_context = _combine_report_contexts(report_entries)
    return {
        "prescription_context": prescription_context,
        "report_context": report_context,
        "extracted_conditions": deduped_conditions,
        "recent_diagnoses": cleaned_diagnoses,
        "reported_symptoms": cleaned_reported_symptoms,
        "medications": medications,
        "prescription_instructions": prescription_instructions,
        "document_warnings": document_warnings,
        "document_summary": document_summary,
        "timings": stage_timings,
    }


async def _build_public_suggested_care_response(
    *,
    db: Session,
    service: DoctorRecommendationService,
    analyzer_service: PrescriptionAnalyzerService,
    storage_service: StorageService | None,
    cache_service: DocumentAnalysisCacheService,
    symptoms: list[str],
    preferences: dict[str, Any],
    language: str,
    prescription_file: UploadFile | None,
    report_files: list[UploadFile],
    legacy_file: UploadFile | None,
    include_llm_reasons: bool = False,
    emit_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    emit_deferred_doctor_reasons: bool = False,
) -> dict[str, Any]:
    normalized_language = normalize_response_language(language)
    if prescription_file is None and not report_files and legacy_file is None:
        doctors, analysis = await service.suggest_doctors_preview(
            db=db,
            symptoms=symptoms,
            preferences=preferences,
            language=normalized_language,
            include_llm_reasons=include_llm_reasons,
        )
        doctor_list = [_build_public_doctor_payload(item) for item in doctors]
        best_doctor = doctor_list[0] if doctor_list else None
        response_data = {
            "doctor": best_doctor,
            "doctors": doctor_list,
            "patient_profile": _build_patient_profile(analysis),
            "symptom_analysis": analysis,
            "prescription_context": None,
            "report_context": None,
        }
        if emit_event is not None:
            await emit_event(
                "symptom_analysis",
                {
                    "patient_profile": response_data["patient_profile"],
                    "symptom_analysis": analysis,
                },
            )
            await emit_event(
                "doctors",
                {"doctor": best_doctor, "doctors": doctor_list},
            )
            if emit_deferred_doctor_reasons and doctor_list:
                deferred_updates = await service.generate_deferred_doctor_reasoning_updates(
                    symptom_analysis=analysis,
                    doctors=doctor_list,
                    language=normalized_language,
                )
                if deferred_updates:
                    await emit_event("doctor_reasons", {"doctor_reasons": deferred_updates})
        return response_data

    document_started_at = time.monotonic()
    if storage_service is None:
        raise RuntimeError(
            "Storage backend is unavailable while processing uploaded files. "
            "Set STORAGE_BACKEND to a configured remote backend for production."
        )
    document_context = await _collect_uploaded_document_contexts(
        db=db,
        analyzer_service=analyzer_service,
        storage_service=storage_service,
        cache_service=cache_service,
        prescription_file=prescription_file,
        report_files=report_files,
        legacy_file=legacy_file,
        language=normalized_language,
        emit_event=emit_event,
    )
    logger.info(
        "Document context aggregation completed duration_ms=%d",
        int((time.monotonic() - document_started_at) * 1000),
    )

    ranking_started_at = time.monotonic()
    doctors, analysis = await service.suggest_doctors_preview(
        db=db,
        symptoms=symptoms,
        preferences=preferences,
        external_medical_conditions=document_context["extracted_conditions"],
        external_recent_diagnoses=document_context["recent_diagnoses"],
        external_symptom_context=document_context["reported_symptoms"],
        prescription_medications=document_context["medications"],
        prescription_instructions=document_context["prescription_instructions"],
        document_warnings=document_context["document_warnings"],
        report_findings=(document_context["report_context"] or {}).get("report_findings"),
        document_summary=document_context["document_summary"],
        language=normalized_language,
        include_llm_reasons=include_llm_reasons,
    )
    analysis = _ensure_report_analysis_present(
        analysis,
        document_context["report_context"],
        language=normalized_language,
    )
    logger.info(
        "Symptom analysis + doctor ranking completed duration_ms=%d",
        int((time.monotonic() - ranking_started_at) * 1000),
    )

    doctor_list = [_build_public_doctor_payload(item) for item in doctors]
    best_doctor = doctor_list[0] if doctor_list else None
    response_data = {
        "doctor": best_doctor,
        "doctors": doctor_list,
        "patient_profile": _build_patient_profile(analysis),
        "symptom_analysis": analysis,
        "prescription_context": document_context["prescription_context"],
        "report_context": document_context["report_context"],
    }
    if emit_event is not None:
        await emit_event(
            "symptom_analysis",
            {
                "patient_profile": response_data["patient_profile"],
                "symptom_analysis": analysis,
            },
        )
        await emit_event(
            "doctors",
            {"doctor": best_doctor, "doctors": doctor_list},
        )
        if emit_deferred_doctor_reasons and doctor_list:
            deferred_updates = await service.generate_deferred_doctor_reasoning_updates(
                symptom_analysis=analysis,
                doctors=doctor_list,
                language=normalized_language,
            )
            if deferred_updates:
                await emit_event("doctor_reasons", {"doctor_reasons": deferred_updates})
    return response_data


@router.post("/suggest-doctors", response_model=RecommendationResponse)
async def suggest_doctors(
    payload: RecommendationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    service: Annotated[DoctorRecommendationService, Depends(get_doctor_recommendation_service)],
) -> RecommendationResponse:
    try:
        recommendation, doctors = await service.recommend_doctors(
            db=db,
            user_id=current_user.id,
            symptoms=payload.symptoms,
            prescription_ids=payload.prescription_ids,
            preferences=payload.preferences,
            symptom_checker_session_id=payload.symptom_checker_session_id,
            language=payload.language,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RecommendationResponse(recommendation_id=recommendation.id, doctors=doctors)


@router.post("/public-suggest-doctors")
async def public_suggest_doctors(
    payload: RecommendationRequest,
    db: Annotated[Session, Depends(get_db)],
    service: Annotated[DoctorRecommendationService, Depends(get_doctor_recommendation_service)],
    _rate_limit: Annotated[None, Depends(ip_rate_limit(max_requests=2, endpoint="public_suggest_doctors"))],
) -> dict:
    started_at = time.monotonic()
    try:
        doctors, analysis = await service.suggest_doctors_preview(
            db=db,
            symptoms=payload.symptoms,
            prescription_ids=payload.prescription_ids,
            preferences=payload.preferences,
            language=payload.language,
        )
        doctor_list = [_build_public_doctor_payload(item) for item in doctors]
        best_doctor = doctor_list[0] if doctor_list else None
        return {
            "doctor": best_doctor,
            "doctors": doctor_list,
            "patient_profile": _build_patient_profile(analysis),
            "symptom_analysis": analysis,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        logger.info(
            "public_suggest_doctors completed duration_ms=%d symptom_count=%d has_prescriptions=%s",
            int((time.monotonic() - started_at) * 1000),
            len(payload.symptoms or []),
            bool(payload.prescription_ids),
        )


@router.post("/public-doctor-ai-previews", response_model=ExternalDoctorPreviewResponse)
async def public_doctor_ai_previews(
    payload: ExternalDoctorPreviewRequest,
    service: Annotated[DoctorRecommendationService, Depends(get_doctor_recommendation_service)],
    _rate_limit: Annotated[None, Depends(ip_rate_limit(max_requests=2, endpoint="public_doctor_previews"))],
) -> ExternalDoctorPreviewResponse:
    symptoms = [str(item).strip() for item in payload.symptoms if str(item).strip()]
    if not symptoms:
        raise HTTPException(status_code=400, detail="At least one symptom is required")

    doctor_payload = [item.model_dump() for item in payload.doctors]
    previews, analysis_source = await service.generate_external_doctor_previews(
        symptoms=symptoms,
        doctors=doctor_payload,
        limit=payload.limit,
        language=payload.language,
    )
    return ExternalDoctorPreviewResponse(previews=previews, analysis_source=analysis_source)


@router.post("/public-suggest-doctors-with-prescription")
async def public_suggest_doctors_with_prescription(
    db: Annotated[Session, Depends(get_db)],
    service: Annotated[DoctorRecommendationService, Depends(get_doctor_recommendation_service)],
    storage_service: Annotated[StorageService | None, Depends(get_storage_service)],
    cache_service: Annotated[DocumentAnalysisCacheService, Depends(get_document_analysis_cache_service)],
    _rate_limit: Annotated[None, Depends(ip_rate_limit(max_requests=2, endpoint="public_prescription_suggest"))],
    prescription_file: UploadFile | None = File(None),
    report_files: list[UploadFile] = File(default=[]),
    file: UploadFile | None = File(None),
    symptoms_json: str = Form(...),
    preferences_json: str = Form("{}"),
    language: str = Form("en"),
) -> dict:
    started_at = time.monotonic()
    parsed_symptom_count = 0
    try:
        symptoms = _parse_symptoms_json(symptoms_json)
        preferences = _parse_preferences_json(preferences_json)
        normalized_language = normalize_response_language(language)
        parsed_symptom_count = len(symptoms)
        legacy_file = file if prescription_file is None and not report_files else None
        analyzer_service = get_prescription_analyzer_service()
        response_data = await _build_public_suggested_care_response(
            db=db,
            service=service,
            analyzer_service=analyzer_service,
            storage_service=storage_service,
            cache_service=cache_service,
            symptoms=symptoms,
            preferences=preferences,
            language=normalized_language,
            prescription_file=prescription_file,
            report_files=report_files,
            legacy_file=legacy_file,
            include_llm_reasons=False,
        )
        return response_data
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error while processing uploaded medical documents for public doctor suggestions")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while processing uploaded medical documents",
        ) from exc
    finally:
        logger.info(
            "public_suggest_doctors_with_prescription completed duration_ms=%d symptom_count=%d prescription_present=%s report_count=%d legacy_file_present=%s",
            int((time.monotonic() - started_at) * 1000),
            parsed_symptom_count,
            prescription_file is not None,
            len(report_files or []),
            file is not None and prescription_file is None and not report_files,
        )


@router.post("/public-suggest-doctors-with-prescription/stream")
async def public_suggest_doctors_with_prescription_stream(
    db: Annotated[Session, Depends(get_db)],
    service: Annotated[DoctorRecommendationService, Depends(get_doctor_recommendation_service)],
    storage_service: Annotated[StorageService | None, Depends(get_storage_service)],
    cache_service: Annotated[DocumentAnalysisCacheService, Depends(get_document_analysis_cache_service)],
    _rate_limit: Annotated[
        None,
        Depends(ip_rate_limit(max_requests=2, endpoint="public_prescription_suggest_stream")),
    ],
    prescription_file: UploadFile | None = File(None),
    report_files: list[UploadFile] = File(default=[]),
    file: UploadFile | None = File(None),
    symptoms_json: str = Form(...),
    preferences_json: str = Form("{}"),
    language: str = Form("en"),
) -> StreamingResponse:
    symptoms = _parse_symptoms_json(symptoms_json)
    preferences = _parse_preferences_json(preferences_json)
    normalized_language = normalize_response_language(language)
    analyzer_service = get_prescription_analyzer_service()
    legacy_file = file if prescription_file is None and not report_files else None

    async def event_stream() -> Any:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        stream_started_at = time.monotonic()
        first_event_ms: int | None = None

        async def emit_event(event_name: str, payload: dict[str, Any]) -> None:
            nonlocal first_event_ms
            if first_event_ms is None:
                first_event_ms = int((time.monotonic() - stream_started_at) * 1000)
            await queue.put(_format_sse_event(event_name, payload))

        async def worker() -> None:
            try:
                await emit_event(
                    "start",
                    {
                        "status": "processing",
                        "language": normalized_language,
                        "symptom_count": len(symptoms),
                    },
                )
                response_data = await _build_public_suggested_care_response(
                    db=db,
                    service=service,
                    analyzer_service=analyzer_service,
                    storage_service=storage_service,
                    cache_service=cache_service,
                    symptoms=symptoms,
                    preferences=preferences,
                    language=normalized_language,
                    prescription_file=prescription_file,
                    report_files=report_files,
                    legacy_file=legacy_file,
                    include_llm_reasons=False,
                    emit_event=emit_event,
                    emit_deferred_doctor_reasons=True,
                )
                await emit_event("done", response_data)
            except HTTPException as exc:
                await emit_event(
                    "error",
                    {"status_code": exc.status_code, "detail": exc.detail},
                )
            except RuntimeError as exc:
                await emit_event("error", {"status_code": 503, "detail": str(exc)})
            except Exception:
                logger.exception("Unexpected error while streaming suggested care response")
                await emit_event(
                    "error",
                    {"status_code": 500, "detail": "Internal server error while streaming recommendations"},
                )
            finally:
                await queue.put(None)
                logger.info(
                    "public_suggest_doctors_with_prescription_stream completed duration_ms=%d first_event_ms=%s symptom_count=%d",
                    int((time.monotonic() - stream_started_at) * 1000),
                    first_event_ms if first_event_ms is not None else "none",
                    len(symptoms),
                )

        worker_task = asyncio.create_task(worker())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            if not worker_task.done():
                worker_task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/public-report-finding-explanation",
    response_model=ReportFindingExplanationResponse,
)
async def public_report_finding_explanation(
    payload: ReportFindingExplanationRequest,
    service: Annotated[DoctorRecommendationService, Depends(get_doctor_recommendation_service)],
    _rate_limit: Annotated[
        None,
        Depends(ip_rate_limit(max_requests=10, endpoint="public_report_finding_explanation")),
    ],
) -> ReportFindingExplanationResponse:
    try:
        explanation = await service.explain_report_finding(
            test_name=payload.test_name,
            observed_value=payload.observed_value,
            reference_range=payload.reference_range,
            status=payload.status,
            language=payload.language,
            context=payload.context,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ReportFindingExplanationResponse(explanation=explanation)


@router.get("/history", response_model=list[RecommendationRecordResponse])
def get_recommendation_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[DoctorRecommendation]:
    return (
        db.query(DoctorRecommendation)
        .filter(DoctorRecommendation.user_id == current_user.id)
        .order_by(DoctorRecommendation.created_at.desc())
        .all()
    )


@router.get("/{recommendation_id}", response_model=RecommendationRecordResponse)
def get_recommendation(
    recommendation_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DoctorRecommendation:
    row = db.query(DoctorRecommendation).filter(DoctorRecommendation.id == recommendation_id).first()
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return row


@router.post("/{recommendation_id}/feedback")
def add_recommendation_feedback(
    recommendation_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    feedback: dict = Body(...),
) -> dict:
    row = db.query(DoctorRecommendation).filter(DoctorRecommendation.id == recommendation_id).first()
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    criteria = dict(row.recommendation_criteria or {})
    criteria["user_feedback"] = feedback
    row.recommendation_criteria = criteria
    db.add(row)
    db.commit()
    db.refresh(row)

    return {"recommendation_id": row.id, "feedback_saved": True}
