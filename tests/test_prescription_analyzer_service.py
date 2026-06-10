from app.ai.medical_normalization import medication_concepts
from app.services.prescription_analyzer_service import (
    PrescriptionAnalyzerService,
    StageResult,
)
import pytest
from unittest.mock import AsyncMock


def test_normalize_document_type_infers_from_visible_structure() -> None:
    service = PrescriptionAnalyzerService()

    assert (
        service._normalize_document_type(
            "unknown",
            medications=[{"name": "ECOSPRIN"}],
            report_findings=[],
        )
        == "prescription"
    )
    assert (
        service._normalize_document_type(
            "unknown",
            medications=[],
            report_findings=[{"test_name": "Hemoglobin"}],
        )
        == "report"
    )
    assert (
        service._normalize_document_type(
            "report",
            medications=[{"name": "ECOSPRIN"}],
            report_findings=[],
        )
        == "prescription"
    )


def test_normalize_date_parses_supported_formats_and_drops_future_values() -> None:
    service = PrescriptionAnalyzerService()

    assert service._normalize_date("15/11/25") == "2025-11-15"
    assert service._normalize_date("05 May 2024") == "2024-05-05"
    assert service._normalize_date("2099-01-01") is None


def test_merge_vision_stage_moves_follow_up_text_out_of_instructions() -> None:
    service = PrescriptionAnalyzerService()

    merged = service._merge_vision_stage(
        StageResult(
            stage="vision",
            status="success",
            confidence=0.8,
            data={
                "document_type": "unknown",
                "medications": [{"name": "ECOSPRIN", "dosage": "75 mg"}],
                "instructions": "Please Come After 3 Months",
                "follow_up": None,
                "confidence_score": 0.8,
            },
        )
    )

    assert merged["document_type"] == "prescription"
    assert merged["follow_up"] == "Please Come After 3 Months"
    assert merged["instructions"] is None
    assert merged["analysis_source"] == "openai_vision"


def test_merge_vision_stage_removes_duplicate_follow_up_instruction_text() -> None:
    service = PrescriptionAnalyzerService()

    merged = service._merge_vision_stage(
        StageResult(
            stage="vision",
            status="success",
            confidence=0.8,
            data={
                "document_type": "prescription",
                "medications": [{"name": "ECOSPRIN", "dosage": "75 mg"}],
                "instructions": "Follow up: Please Come After 3 Months",
                "follow_up": "Come After 3 Months",
                "confidence_score": 0.8,
            },
        )
    )

    assert merged["follow_up"] == "Come After 3 Months"
    assert merged["instructions"] is None


def test_merge_vision_stage_keeps_analysis_summary_empty_without_ai_text() -> None:
    service = PrescriptionAnalyzerService()

    merged = service._merge_vision_stage(
        StageResult(
            stage="vision",
            status="success",
            confidence=0.8,
            data={
                "document_type": "report",
                "report_findings": [
                    {"test_name": "ALT (SGPT)", "observed_value": "42.7", "status": "abnormal"}
                ],
                "confidence_score": 0.8,
            },
        ),
        language="bn",
    )

    assert merged["analysis_summary"] is None


def test_build_rule_based_analysis_keeps_analysis_summary_empty_without_ai() -> None:
    service = PrescriptionAnalyzerService()

    result = service._build_rule_based_analysis(
        """
        BIOCHEMISTRY
        ALT (SGPT) 42.7 U/L
        Bilirubin 0.5 mg/dL
        """
    )

    assert result["analysis_summary"] is None


def test_normalize_analysis_dict_preserves_units_and_extended_fields() -> None:
    service = PrescriptionAnalyzerService()

    normalized = service._normalize_analysis_dict(
        {
            "document_type": "report",
            "doctor_registration_id": "ABC123",
            "patient_name": "MR. MD SAIFUL ISLAM",
            "patient_age": "62Y",
            "patient_sex": "Male",
            "extraction_notes": "Typed report",
            "report_findings": [
                {
                    "test_name": "Hemoglobin",
                    "observed_value": "13.9 g/dL",
                    "reference_range": "12-17 g/dL",
                    "unit": "g/dL",
                    "status": "normal",
                    "ai_analysis": "Normal result.",
                }
            ],
            "medications": [
                {
                    "name": "RIVOTRIL",
                    "dosage": "0.5 mg",
                    "purpose": "If insomnia",
                }
            ],
            "confidence_score": 0.8,
        }
    )

    assert normalized["doctor_registration_id"] == "ABC123"
    assert normalized["patient_name"] == "MR. MD SAIFUL ISLAM"
    assert normalized["extraction_notes"] == "Typed report"
    assert normalized["report_findings"][0]["unit"] == "g/dL"
    assert normalized["medications"][0]["purpose"] == "If insomnia"


def test_normalize_analysis_dict_expands_report_prefixes_and_discards_fragmentary_analysis() -> None:
    service = PrescriptionAnalyzerService()

    normalized = service._normalize_analysis_dict(
        {
            "document_type": "report",
            "report_findings": [
                {
                    "test_name": "Bi. Urea",
                    "observed_value": "25.0 mmol/L",
                    "status": "abnormal",
                    "ai_analysis": "Bi.",
                },
                {
                    "test_name": "S. Creatinine",
                    "observed_value": "131.0 µmol/L",
                    "status": "abnormal",
                    "ai_analysis": "S.",
                },
            ],
            "confidence_score": 0.8,
        }
    )

    assert normalized["report_findings"][0]["test_name"] == "Blood Urea"
    assert normalized["report_findings"][0]["ai_analysis"] is None
    assert normalized["report_findings"][1]["test_name"] == "Serum Creatinine"
    assert normalized["report_findings"][1]["ai_analysis"] is None


def test_extract_medications_skips_frequency_lines_and_keeps_real_medicines() -> None:
    service = PrescriptionAnalyzerService()

    medications = service._extract_medications(
        """ATOVA 10 mg Tab.
0+0+1 - Before Meal
ZYMET 325 MG TAB (PANCREATIC ENZYME)
1+1+1 - After Meal
"""
    )

    assert [item["name"] for item in medications] == [
        "ATOVA",
        "ZYMET 325 MG TAB (PANCREATIC ENZYME)",
    ]
    assert [item["dosage"] for item in medications] == ["10 mg", "325 MG"]


def test_medication_concepts_prefers_explicit_pancreatic_enzyme_hint_over_brand_prior() -> None:
    concepts = medication_concepts("ZYMET 325 MG TAB (PANCREATIC ENZYME)")

    assert "pancreatic enzyme" in concepts
    assert "metformin" not in concepts


@pytest.mark.asyncio
async def test_identify_chronic_medications_uses_known_brand_aliases() -> None:
    service = PrescriptionAnalyzerService()

    conditions = await service.identify_chronic_medications(
        [
            {"name": "CILIDIP-10MG", "purpose": None},
            {"name": "HTZ 25 mg", "purpose": None},
            {"name": "ATOVA 10 mg", "purpose": None},
        ]
    )

    assert "hypertension" in conditions
    assert "hyperlipidemia" in conditions


@pytest.mark.asyncio
async def test_analyze_prescription_image_uses_direct_vision_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PrescriptionAnalyzerService()
    vision_stage = StageResult(
        stage="vision",
        status="success",
        confidence=0.91,
        data={
            "document_type": "prescription",
            "medications": [{"name": "ECOSPRIN", "dosage": "75 mg"}],
            "confidence_score": 0.91,
        },
    )
    vision_stage_mock = AsyncMock(return_value=vision_stage)

    monkeypatch.setattr(service, "_run_vision_stage", vision_stage_mock)

    result = await service.analyze_prescription_image("/tmp/demo.png")

    assert result["analysis_source"] == "openai_vision"
    assert result["document_type"] == "prescription"
    assert vision_stage_mock.await_count == 1
    assert vision_stage_mock.await_args.kwargs["forced_reason"] == "vision_primary_direct_upload"
    assert result["pipeline"]["stages_used"] == ["vision"]
