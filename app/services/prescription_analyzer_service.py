from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import logging
import re
import time
from typing import Any

from app.ai.medical_normalization import (
    is_low_value_report_analysis,
    medication_concepts,
    normalize_report_test_name,
)
from app.ai.medical_prompts import (
    PRESCRIPTION_VISION_ANALYSIS_PROMPT,
    normalize_response_language,
)
from app.ai.openai_response_utils import clamp_confidence
from app.ai.vision_client import VisionClient

logger = logging.getLogger(__name__)


# ── Structured stage tracking ──────────────────────────────────────


@dataclass
class StageResult:
    """Tracks the outcome of a single pipeline stage with clear success/failure metadata."""

    stage: str  # "vision"
    status: str  # "success", "skipped", "failed", "partial"
    confidence: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    skip_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in ("success", "partial")

    @property
    def meaningful(self) -> bool:
        return self.succeeded and PrescriptionAnalyzerService._is_meaningful_analysis(self.data)


# ── Confidence thresholds ──────────────────────────────────────────

MIN_CONF_FLOOR = 0.20                # Absolute minimum confidence for weak results
VISION_MEANINGFUL_BOOST = 0.65       # Minimum confidence when Vision provides meaningful data
MAX_CONFIDENCE_CAP = 0.99            # Never report 1.0 confidence


class PrescriptionAnalyzerService:
    def __init__(self) -> None:
        self.vision_client = VisionClient()

    async def analyze_prescription_image(self, image_path: str, language: str = "en") -> dict[str, Any]:
        logger.info("Starting prescription analysis for: %s", image_path)
        logger.info("Using OpenAI vision as the primary document analysis path")
        normalized_language = normalize_response_language(language)
        vision_stage = await self._run_vision_stage(
            image_path=image_path,
            forced_reason="vision_primary_direct_upload",
            language=normalized_language,
        )
        merged = self._merge_vision_stage(vision_stage, language=normalized_language)
        merged["pipeline"] = self._build_pipeline_metadata([vision_stage])
        return merged

    # ── Stage runners ──────────────────────────────────────────────

    async def _run_vision_stage(
        self,
        image_path: str,
        forced_reason: str,
        language: str,
    ) -> StageResult:
        logger.info("Triggering vision analysis — reason: %s", forced_reason)
        t0 = time.monotonic()
        try:
            result = await self.vision_client.analyze_image(
                image_path, PRESCRIPTION_VISION_ANALYSIS_PROMPT, language=language
            )
            duration = int((time.monotonic() - t0) * 1000)

            vision_status = result.get("status", "")
            if vision_status.startswith("vision_") and vision_status != "vision_api_success":
                return StageResult(
                    stage="vision",
                    status="failed",
                    error=f"Vision API status: {vision_status}",
                    data=result,
                    duration_ms=duration,
                )

            conf = clamp_confidence(result.get("confidence_score"), default=0.0)
            normalized = self._normalize_analysis_dict(result)
            return StageResult(
                stage="vision",
                status="success" if self._is_meaningful_analysis(normalized) else "partial",
                confidence=conf,
                data=normalized,
                duration_ms=duration,
            )
        except Exception as exc:
            logger.error("Vision analysis failed: %s", exc)
            return StageResult(
                stage="vision",
                status="failed",
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

    # ── Merge logic ────────────────────────────────────────────────

    def _merge_vision_stage(self, vision_stage: StageResult, language: str = "en") -> dict[str, Any]:
        vision = self._normalize_analysis_dict(vision_stage.data if vision_stage.succeeded else {})

        confidence_score = vision_stage.confidence if vision_stage.succeeded else 0.0
        if vision_stage.meaningful:
            confidence_score = max(confidence_score, VISION_MEANINGFUL_BOOST)

        medications = vision.get("medications") or []
        report_findings = vision.get("report_findings") or []
        document_type = self._normalize_document_type(
            vision.get("document_type"),
            medications=medications,
            report_findings=report_findings,
        )
        instructions = self._to_str_or_none(vision.get("instructions"))
        follow_up = self._to_str_or_none(vision.get("follow_up"))
        if not follow_up and self._looks_like_follow_up(instructions):
            follow_up = instructions
            instructions = None
        elif follow_up and self._looks_like_follow_up(instructions):
            normalized_instruction = re.sub(r"^(follow[\s-]*up\s*[:\-]?\s*)", "", instructions, flags=re.IGNORECASE)
            normalized_follow_up = re.sub(r"^(follow[\s-]*up\s*[:\-]?\s*)", "", follow_up, flags=re.IGNORECASE)
            normalized_instruction = re.sub(r"^\s*please\s+", "", normalized_instruction, flags=re.IGNORECASE)
            normalized_follow_up = re.sub(r"^\s*please\s+", "", normalized_follow_up, flags=re.IGNORECASE)
            if normalized_instruction.strip().lower() == normalized_follow_up.strip().lower():
                instructions = None

        merged = {
            "document_type": document_type,
            "medications": medications,
            "diagnosis": vision.get("diagnosis"),
            "reported_symptoms": vision.get("reported_symptoms") or [],
            "doctor_name": vision.get("doctor_name"),
            "doctor_specialization": vision.get("doctor_specialization"),
            "doctor_registration_id": vision.get("doctor_registration_id"),
            "patient_name": vision.get("patient_name"),
            "patient_age": vision.get("patient_age"),
            "patient_sex": vision.get("patient_sex"),
            "prescription_date": self._normalize_date(self._to_str_or_none(vision.get("prescription_date"))),
            "instructions": instructions,
            "follow_up": follow_up,
            "warnings": vision.get("warnings") or [],
            "report_findings": report_findings,
            "analysis_summary": vision.get("analysis_summary"),
            "extraction_notes": vision.get("extraction_notes"),
            "confidence_score": min(confidence_score, MAX_CONFIDENCE_CAP),
        }

        # Final confidence floor for truly empty results
        if not self._is_meaningful_analysis(merged):
            merged["confidence_score"] = min(
                float(merged.get("confidence_score") or 0.0), MIN_CONF_FLOOR
            )

        if vision_stage.succeeded:
            merged["vision_status"] = "used"
            merged["analysis_source"] = "openai_vision"
        else:
            merged["analysis_source"] = "rules"

        return merged

    def _build_pipeline_metadata(self, stages: list[StageResult]) -> dict[str, Any]:
        """Build transparent metadata about what each pipeline stage did."""
        total_ms = sum(s.duration_ms for s in stages)
        stage_summaries = []
        for s in stages:
            summary: dict[str, Any] = {
                "stage": s.stage,
                "status": s.status,
                "confidence": round(s.confidence, 3),
                "duration_ms": s.duration_ms,
            }
            if s.error:
                summary["error"] = s.error
            if s.skip_reason:
                summary["skip_reason"] = s.skip_reason
            stage_summaries.append(summary)

        return {
            "stages": stage_summaries,
            "total_duration_ms": total_ms,
            "stages_used": [s.stage for s in stages if s.succeeded],
            "stages_failed": [s.stage for s in stages if s.status == "failed"],
            "stages_skipped": [s.stage for s in stages if s.status == "skipped"],
        }

    # ── Existing methods (unchanged logic, cleaned up) ─────────────

    async def extract_medical_conditions(self, parsed_data: dict) -> list[str]:
        conditions: list[str] = []
        diagnosis = parsed_data.get("diagnosis")
        if diagnosis:
            conditions.extend([part.strip().lower() for part in re.split(r"[,;/]", diagnosis) if part.strip()])

        chronic_medications = await self.identify_chronic_medications(parsed_data.get("medications") or [])
        conditions.extend(chronic_medications)
        return sorted(set(conditions))

    async def identify_chronic_medications(self, medications: list[dict]) -> list[str]:
        found: list[str] = []
        for med in medications:
            med_name = (med.get("name") or "").lower()
            concepts = medication_concepts(med_name, med.get("purpose"))
            if any(token in concepts for token in {"metformin", "insulin"}):
                found.append("diabetes")
            if any(token in concepts for token in {"amlodipine", "losartan", "cilnidipine", "hydrochlorothiazide"}):
                found.append("hypertension")
            if any(token in concepts for token in {"atorvastatin", "fenofibrate"}):
                found.append("hyperlipidemia")
            if "levothyroxine" in concepts:
                found.append("thyroid disorder")
        return sorted(set(found))

    def _build_rule_based_analysis(self, text: str) -> dict[str, Any]:
        medications = self._extract_medications(text)
        diagnosis = self._extract_section(text, ["diagnosis", "diagnosed", "impression"])
        doctor_name = self._extract_doctor_name(text)
        instructions = self._extract_section(text, ["instruction", "advice"])
        reported_symptoms = self._extract_reported_symptoms(text)
        report_findings = self._extract_report_findings(text)
        warnings = self._extract_warnings(text)
        document_type = self._detect_document_type(
            text=text,
            medications=medications,
            report_findings=report_findings,
        )

        confidence = 0.45
        if medications:
            confidence += 0.25
        if diagnosis:
            confidence += 0.15
        if reported_symptoms:
            confidence += 0.05
        if doctor_name:
            confidence += 0.1
        if report_findings:
            confidence += 0.2

        return {
            "document_type": document_type,
            "medications": medications,
            "diagnosis": diagnosis,
            "reported_symptoms": reported_symptoms,
            "doctor_name": doctor_name,
            "doctor_specialization": None,
            "prescription_date": self._extract_date(text),
            "instructions": instructions,
            "follow_up": self._extract_section(text, ["follow", "next visit"]),
            "warnings": warnings,
            "report_findings": report_findings,
            "analysis_summary": None,
            "confidence_score": min(confidence, 0.95),
        }

    def _normalize_analysis_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        raw_meds = payload.get("medications") or []
        normalized_meds: list[dict[str, str | None]] = []
        if isinstance(raw_meds, list):
            for med in raw_meds:
                if isinstance(med, str):
                    name = med.strip()
                    if self._is_valid_medication_name(name):
                        normalized_meds.append(
                            {
                                "name": name,
                                "dosage": None,
                                "frequency": None,
                                "duration": None,
                                "route": None,
                                "purpose": None,
                            }
                        )
                    continue
                if not isinstance(med, dict):
                    continue
                name = str(med.get("name") or "").strip()
                if not self._is_valid_medication_name(name):
                    continue
                normalized_meds.append(
                    {
                        "name": name,
                        "dosage": self._to_str_or_none(med.get("dosage")),
                        "frequency": self._to_str_or_none(med.get("frequency")),
                        "duration": self._to_str_or_none(med.get("duration")),
                        "route": self._to_str_or_none(med.get("route")),
                        "purpose": self._to_str_or_none(med.get("purpose")),
                    }
                )

        confidence_raw = payload.get("confidence_score")
        confidence = clamp_confidence(confidence_raw, default=0.0)

        doctor_specialization = self._to_str_or_none(payload.get("doctor_specialization"))
        doctor_name = self._sanitize_doctor_name(
            payload.get("doctor_name"),
            doctor_specialization=doctor_specialization,
        )
        reported_symptoms = self._coerce_reported_symptoms(payload.get("reported_symptoms"))
        report_findings = self._normalize_report_findings(payload.get("report_findings"))
        medications = normalized_meds
        document_type = self._normalize_document_type(
            payload.get("document_type"),
            medications=medications,
            report_findings=report_findings,
        )
        warnings = self._coerce_string_list(payload.get("warnings"))
        analysis_summary = self._to_str_or_none(payload.get("analysis_summary"))

        return {
            "document_type": document_type,
            "medications": medications,
            "diagnosis": self._to_str_or_none(payload.get("diagnosis")),
            "reported_symptoms": reported_symptoms,
            "doctor_name": doctor_name,
            "doctor_specialization": doctor_specialization,
            "doctor_registration_id": self._to_str_or_none(payload.get("doctor_registration_id")),
            "patient_name": self._to_str_or_none(payload.get("patient_name")),
            "patient_age": self._to_str_or_none(payload.get("patient_age")),
            "patient_sex": self._to_str_or_none(payload.get("patient_sex")),
            "prescription_date": self._normalize_date(self._to_str_or_none(payload.get("prescription_date"))),
            "instructions": self._to_str_or_none(payload.get("instructions")),
            "follow_up": self._to_str_or_none(payload.get("follow_up")),
            "warnings": warnings,
            "report_findings": report_findings,
            "analysis_summary": analysis_summary,
            "extraction_notes": self._to_str_or_none(payload.get("extraction_notes")),
            "confidence_score": confidence,
        }

    @staticmethod
    def _to_str_or_none(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _extract_medications(self, text: str) -> list[dict[str, str | None]]:
        meds: list[dict[str, str | None]] = []
        if not text:
            return meds

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        pattern = re.compile(
            r"([A-Za-z][A-Za-z0-9\- ]{2,}?)(?:\s+(\d+(?:\.\d+)?\s?(?:mg|ml|mcg|g)))?",
            re.IGNORECASE,
        )
        dose_pattern = re.compile(r"\b\d+(?:\.\d+)?\s?(?:mg|ml|mcg|g)\b", re.IGNORECASE)
        dosage_form_pattern = re.compile(
            r"\b(tab|tablet|cap|capsule|syrup|inj|injection|drop|drops|cream|ointment|suspension)\b",
            re.IGNORECASE,
        )
        for line in lines:
            lower = line.lower()
            if self._is_noise_line(lower) or self._is_medication_instruction_line(lower):
                continue

            cleaned = re.sub(r"^[\-\u2022*]+\s*", "", line).strip()
            cleaned = re.sub(r"^\d+\s*[.)-]?\s*", "", cleaned).strip()
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:")
            if not cleaned:
                continue

            dosage_match = dose_pattern.search(cleaned)
            if dosage_match is None and not dosage_form_pattern.search(cleaned):
                continue

            match = pattern.search(cleaned)
            if not match:
                continue
            if "(" in cleaned:
                name = cleaned
            elif dosage_match is not None:
                name = cleaned[: dosage_match.start()].strip(" -:")
            else:
                dosage_form_match = dosage_form_pattern.search(cleaned)
                if dosage_form_match is not None:
                    name = cleaned[: dosage_form_match.start()].strip(" -:")
                else:
                    name = match.group(1).strip()
            if not self._is_valid_medication_name(name):
                continue
            dosage = (match.group(2) or (dosage_match.group(0) if dosage_match else "")).strip() or None
            meds.append(
                {
                    "name": name,
                    "dosage": dosage,
                    "frequency": None,
                    "duration": None,
                    "route": None,
                    "purpose": None,
                }
            )
        return meds[:10]

    def _extract_report_findings(self, text: str) -> list[dict[str, str | None]]:
        if not text:
            return []

        findings: list[dict[str, str | None]] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            lower = line.lower()
            if self._is_noise_line(lower):
                continue
            if not self._looks_like_report_line(line):
                continue

            cleaned = re.sub(r"\s+", " ", line).strip(" -:")
            match = re.match(
                r"^(?P<name>[A-Za-z][A-Za-z0-9()/%+,\- ]{2,}?)\s*(?:[:\-]| {2,})\s*(?P<value>.+)$",
                cleaned,
            )
            if match:
                name = match.group("name").strip()
                remainder = match.group("value").strip()
            else:
                tokens = cleaned.split()
                if len(tokens) < 2:
                    continue
                pivot = next((index for index, token in enumerate(tokens) if self._token_has_measurement(token)), None)
                if pivot is None or pivot == 0:
                    continue
                name = " ".join(tokens[:pivot]).strip()
                remainder = " ".join(tokens[pivot:]).strip()

            if not name or len(name) < 2:
                continue
            name = normalize_report_test_name(name)

            observed_value = self._extract_observed_value(remainder)
            reference_range = self._extract_reference_range(remainder)
            status = self._infer_report_status(cleaned)
            findings.append(
                {
                    "test_name": name,
                    "observed_value": observed_value,
                    "reference_range": reference_range,
                    "status": status,
                    "ai_analysis": None,
                }
            )

        deduped: list[dict[str, str | None]] = []
        seen: set[str] = set()
        for item in findings:
            key = f"{str(item.get('test_name') or '').lower()}::{str(item.get('observed_value') or '').lower()}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= 12:
                break
        return deduped

    def _extract_warnings(self, text: str) -> list[str]:
        if not text:
            return []
        markers = [
            "after food",
            "before food",
            "with food",
            "empty stomach",
            "avoid alcohol",
            "avoid driving",
            "drowsy",
            "bed rest",
            "complete the course",
            "if symptoms worsen",
            "return immediately",
            "follow up",
        ]
        warnings: list[str] = []
        for line in [line.strip() for line in text.splitlines() if line.strip()]:
            lower = line.lower()
            if self._is_noise_line(lower):
                continue
            if any(marker in lower for marker in markers):
                warnings.append(re.sub(r"\s+", " ", line).strip())
        return self._coerce_string_list(warnings)[:8]

    def _extract_section(self, text: str, keywords: list[str]) -> str | None:
        for line in text.splitlines():
            lower = line.lower()
            if self._is_noise_line(lower):
                continue
            if any(keyword in lower for keyword in keywords):
                return line.strip()
        return None

    def _extract_doctor_name(self, text: str) -> str | None:
        for line in text.splitlines():
            lower = line.lower()
            if self._is_noise_line(lower):
                continue
            if re.search(r"\b(dr\.?|doctor|prof\.?|consultant)\b", lower):
                sanitized = self._sanitize_doctor_name(line, doctor_specialization=None)
                if sanitized:
                    return sanitized
        return None

    def _extract_reported_symptoms(self, text: str) -> list[str]:
        if not text:
            return []

        symptom_terms = [
            "cough",
            "phlegm",
            "sputum",
            "breathless",
            "breathlessness",
            "shortness of breath",
            "wheeze",
            "wheezing",
            "fever",
            "chest tightness",
            "chest congestion",
            "sore throat",
            "runny nose",
            "blocked nose",
            "night cough",
            "sleep disturbance",
            "pain",
            "vomiting",
            "nausea",
            "diarrhea",
            "constipation",
            "headache",
            "dizziness",
            "weakness",
            "fatigue",
            "blood in urine",
            "blood in stool",
        ]
        complaint_markers = [
            "chief complaint",
            "presenting complaint",
            "complaint",
            "symptom",
            "history of present illness",
            "hpi",
            "c/o",
        ]

        collected: list[str] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            lower = line.lower()
            if self._is_noise_line(lower):
                continue

            if any(marker in lower for marker in complaint_markers):
                candidate = line.split(":", 1)[1].strip() if ":" in line else line
                for chunk in re.split(r",|;|/|\band\b", candidate, flags=re.IGNORECASE):
                    normalized = self._normalize_symptom_candidate(chunk)
                    if not normalized:
                        continue
                    normalized_lower = normalized.lower()
                    if any(term in normalized_lower for term in symptom_terms):
                        collected.append(normalized)
                continue

            if any(term in lower for term in symptom_terms):
                if re.search(r"\b\d+\s?(mg|ml|mcg)\b", lower):
                    continue
                normalized = self._normalize_symptom_candidate(line)
                if normalized:
                    collected.append(normalized)

        deduped: list[str] = []
        seen: set[str] = set()
        for item in collected:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= 8:
                break
        return deduped

    def _extract_date(self, text: str) -> str | None:
        date_pattern = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
        match = date_pattern.search(text)
        return match.group(1) if match else None

    def _normalize_report_findings(self, value: Any) -> list[dict[str, str | None]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, str | None]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            test_name = normalize_report_test_name(self._to_str_or_none(item.get("test_name")))
            if not test_name:
                continue
            ai_analysis = self._to_str_or_none(item.get("ai_analysis"))
            if is_low_value_report_analysis(ai_analysis, test_name):
                ai_analysis = None
            normalized.append(
                {
                    "test_name": test_name,
                    "observed_value": self._to_str_or_none(item.get("observed_value")),
                    "reference_range": self._to_str_or_none(item.get("reference_range")),
                    "unit": self._to_str_or_none(item.get("unit")),
                    "status": self._normalize_status(item.get("status")),
                    "ai_analysis": ai_analysis,
                }
            )
        return normalized[:15]

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _normalize_document_type(
        self,
        value: Any,
        medications: list[dict[str, Any]],
        report_findings: list[dict[str, Any]],
    ) -> str:
        text = str(value or "").strip().lower()
        detected = self._detect_document_type(
            text="",
            medications=medications,
            report_findings=report_findings,
        )
        if text not in {"prescription", "report", "mixed", "unknown"}:
            return detected
        if text == "unknown":
            return detected
        if detected == "unknown":
            return text
        if text != detected:
            if detected == "mixed":
                return detected
            has_meds = bool(medications)
            has_findings = bool(report_findings)
            if text == "mixed" and ((has_meds and not has_findings) or (has_findings and not has_meds)):
                return detected
            if text == "prescription" and has_findings and not has_meds:
                return detected
            if text == "report" and has_meds and not has_findings:
                return detected
        return text

    def _detect_document_type(
        self,
        text: str,
        medications: list[dict[str, Any]],
        report_findings: list[dict[str, Any]],
    ) -> str:
        has_meds = bool(medications)
        has_findings = bool(report_findings)
        lowered = str(text or "").lower()
        if has_meds and has_findings:
            return "mixed"
        if has_meds:
            return "prescription"
        if has_findings:
            return "report"
        if any(token in lowered for token in ["haemoglobin", "hemoglobin", "wbc", "rbc", "creatinine", "glucose", "platelet"]):
            return "report"
        if any(token in lowered for token in ["rx", "tablet", "capsule", "take", "dosage", "prescription"]):
            return "prescription"
        return "unknown"

    def _build_analysis_summary(
        self,
        document_type: str,
        diagnosis: str | None,
        medications: list[dict[str, Any]],
        report_findings: list[dict[str, Any]],
        reported_symptoms: list[str],
        language: str = "en",
    ) -> str | None:
        return None

    @staticmethod
    def _normalize_date(value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None

        normalized = re.sub(r"\s+", " ", text.replace(",", " ")).strip()
        formats = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d/%m/%y",
            "%d-%m-%Y",
            "%d-%m-%y",
            "%d %b %Y",
            "%d %B %Y",
            "%d %b %y",
            "%d %B %y",
        ]
        parsed_date: date | None = None
        for fmt in formats:
            try:
                parsed_date = datetime.strptime(normalized, fmt).date()
                break
            except ValueError:
                continue

        if parsed_date is None:
            return None
        if parsed_date > date.today():
            return None
        return parsed_date.isoformat()

    @staticmethod
    def _looks_like_follow_up(value: str | None) -> bool:
        text = str(value or "").strip().lower()
        if not text:
            return False
        if any(token in text for token in ["follow up", "follow-up", "next visit", "come after"]):
            return True
        return bool(re.search(r"\b(after|within)\s+\d+\s+(day|days|week|weeks|month|months|year|years)\b", text))

    @staticmethod
    def _looks_like_report_line(line: str) -> bool:
        lower = line.lower()
        if re.search(r"\b\d", line) is None:
            return False
        report_keywords = [
            "hemoglobin",
            "haemoglobin",
            "wbc",
            "rbc",
            "platelet",
            "glucose",
            "creatinine",
            "urea",
            "bilirubin",
            "sgpt",
            "alt",
            "ast",
            "tsh",
            "t3",
            "t4",
            "cholesterol",
            "triglyceride",
            "sodium",
            "potassium",
            "hb",
            "esr",
            "crp",
            "psa",
            "report",
            "result",
        ]
        return any(keyword in lower for keyword in report_keywords)

    @staticmethod
    def _token_has_measurement(token: str) -> bool:
        return bool(re.search(r"\d", token))

    @staticmethod
    def _extract_observed_value(text: str) -> str | None:
        match = re.search(
            r"([<>]?\s*\d+(?:\.\d+)?(?:\s*(?:mg/dl|g/dl|mmol/l|iu/l|u/l|cells/\w+|x10\^?\d+/\w+|%|gm/dl|mg/l|ml/min|ng/ml|pg/ml|fl|meq/l|umol/l|µmol/l))?)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
        return None

    @staticmethod
    def _extract_reference_range(text: str) -> str | None:
        match = re.search(
            r"(\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?(?:\s*(?:mg/dl|g/dl|mmol/l|iu/l|u/l|%|gm/dl|mg/l|ml/min|ng/ml|pg/ml|fl|meq/l|umol/l|µmol/l))?)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
        return None

    @staticmethod
    def _normalize_status(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"normal", "borderline", "abnormal", "critical", "managed", "unknown"}:
            return text
        if text in {"high", "low", "positive", "reactive"}:
            return "abnormal"
        if text in {"negative", "non-reactive"}:
            return "normal"
        return "unknown"

    def _infer_report_status(self, text: str) -> str:
        lower = text.lower()
        if any(term in lower for term in ["high", "low", "positive", "reactive", "abnormal", "critical"]):
            return "abnormal"
        if "borderline" in lower:
            return "borderline"
        if any(term in lower for term in ["normal", "negative", "non-reactive", "within range"]):
            return "normal"
        return "unknown"

    def _coerce_reported_symptoms(self, value: Any) -> list[str]:
        candidates: list[str] = []
        if isinstance(value, list):
            candidates = [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, str) and value.strip():
            candidates = [
                part.strip()
                for part in re.split(r"\n|,|;|/|\band\b", value, flags=re.IGNORECASE)
                if part.strip()
            ]

        if not candidates:
            return []

        symptoms: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            normalized = self._normalize_symptom_candidate(item)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            symptoms.append(normalized)
            if len(symptoms) >= 8:
                break
        return symptoms

    @staticmethod
    def _normalize_symptom_candidate(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(
            r"^(chief complaint|presenting complaint|complaint|symptoms?|hpi|c\/o)\s*[:\-]?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        text = re.sub(r"\s+", " ", text).strip(" -:")
        if len(text) < 3:
            return ""
        blocked = ["doctor", "dr.", "prof.", "consultant", "mbbs", "md", "fcps"]
        lowered = text.lower()
        if any(token in lowered for token in blocked) and not any(
            term in lowered
            for term in ["pain", "cough", "breath", "fever", "vomit", "nausea", "dizziness", "weakness"]
        ):
            return ""
        return text

    def _sanitize_doctor_name(self, value: Any, doctor_specialization: str | None = None) -> str | None:
        text = self._to_str_or_none(value)
        if not text:
            return None

        raw = re.sub(r"\s+", " ", text).strip()
        raw_lower = raw.lower()
        clean = raw
        clean = re.sub(
            r"^(doctor|dr\.?|prescribing doctor|consultant|prof\.?)\s*[:\-]?\s*",
            "",
            clean,
            flags=re.IGNORECASE,
        ).strip()
        lower = clean.lower()
        if not clean:
            return None

        if any(lower.startswith(prefix) for prefix in ["patient", "name", "mr ", "mrs ", "ms ", "miss "]):
            return None

        doctor_markers = ["dr", "prof", "consultant", "mbbs", "md", "fcps", "specialist"]
        has_doctor_marker = any(marker in raw_lower for marker in doctor_markers) or any(
            marker in lower for marker in doctor_markers
        )
        has_specialization_context = bool(str(doctor_specialization or "").strip())

        if not has_doctor_marker and not has_specialization_context:
            return None

        token_count = len([token for token in re.split(r"[\s,.\-]+", clean) if token])
        if token_count < 2 and not has_doctor_marker:
            return None
        return clean

    @staticmethod
    def _is_noise_line(lower_text: str) -> bool:
        noise_terms = [
            "ocr engine",
            "ocr extraction failed",
            "install tesseract",
            "unavailable",
            "prompt_used",
            "image_path",
            "vision_",
        ]
        return any(term in lower_text for term in noise_terms)

    @staticmethod
    def _is_medication_instruction_line(lower_text: str) -> bool:
        if re.match(r"^\s*\d\s*[+x-]\s*\d\s*[+x-]\s*\d\b", lower_text):
            return True
        if re.match(r"^\s*(before|after|with|empty stomach|if insomnia|if needed|as needed)\b", lower_text):
            return True
        return False

    @staticmethod
    def _is_valid_medication_name(name: str) -> bool:
        text = (name or "").strip()
        if len(text) < 3:
            return False

        lower = text.lower()
        blocked_terms = [
            "ocr engine",
            "ocr extraction",
            "install tesseract",
            "unavailable",
            "pdf ocr",
            "error",
            "image_path",
            "prompt_used",
            "vision",
            "api",
            "json",
        ]
        if any(term in lower for term in blocked_terms):
            return False

        alpha_count = sum(1 for char in text if char.isalpha())
        if alpha_count < 3:
            return False
        if alpha_count / max(len(text), 1) < 0.35:
            return False
        return True

    @staticmethod
    def _is_meaningful_analysis(payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        meds = payload.get("medications") or []
        diagnosis = str(payload.get("diagnosis") or "").strip()
        reported_symptoms = payload.get("reported_symptoms") or []
        doctor_name = str(payload.get("doctor_name") or "").strip()
        instructions = str(payload.get("instructions") or "").strip()
        follow_up = str(payload.get("follow_up") or "").strip()
        report_findings = payload.get("report_findings") or []
        analysis_summary = str(payload.get("analysis_summary") or "").strip()
        return bool(
            meds
            or diagnosis
            or reported_symptoms
            or doctor_name
            or instructions
            or follow_up
            or report_findings
            or analysis_summary
        )
