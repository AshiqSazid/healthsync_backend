from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.doctor_recommendation_service import DoctorRecommendationService


def _contains_bangla(text: str) -> bool:
    return any("\u0980" <= char <= "\u09ff" for char in str(text or ""))


def _make_doctor(
    *,
    doctor_id: str,
    name: str,
    specialization: list[str],
    experience_years: int = 10,
    average_rating: float = 4.5,
    available_slots: list[str] | None = None,
    conditions_treated: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=doctor_id,
        user=SimpleNamespace(username=name),
        specialization=specialization,
        hospital_id=None,
        experience_years=experience_years,
        average_rating=average_rating,
        available_slots=available_slots or ["09:00"],
        conditions_treated=conditions_treated or [],
    )


def test_prioritize_specialty_recommendations_keeps_existing_specialist_first() -> None:
    service = DoctorRecommendationService()

    analysis = {
        "primary_category": "general",
        "severity": 4,
        "urgency": "low",
        "recommended_specializations": ["general physician"],
        "triage_note": "Outpatient review is reasonable.",
        "clinical_impression": "Mild lab variation without severe warning signs.",
        "recommended_next_steps": ["Arrange routine review."],
    }
    medical_history = {"previous_specializations": ["Kidney Specialist"]}

    updated = service._prioritize_specialty_recommendations(analysis, medical_history)

    assert updated["recommended_specializations"][0] == "Nephrology"
    assert "Internal Medicine" not in updated["recommended_specializations"]


def test_finalize_symptom_analysis_output_removes_weak_general_fallbacks() -> None:
    service = DoctorRecommendationService()

    finalized = service._finalize_symptom_analysis_output(
        {
            "primary_category": "respiratory",
            "severity": 5,
            "urgency": "moderate",
            "recommended_specializations": [
                "general physician",
                "pulmonologist",
                "respiratory medicine",
            ],
            "triage_note": "Persistent cough and wheeze should be reviewed by a chest specialist soon. Please monitor closely.",
            "clinical_impression": "Persistent respiratory symptom pattern with no immediate emergency sign but specialist review is appropriate.",
            "recommended_next_steps": ["Arrange specialist review soon."],
        }
    )

    assert finalized["recommended_specializations"] == ["Pulmonology"]
    assert len(finalized["recommended_next_steps"]) >= 1


def test_finalize_symptom_analysis_output_preserves_localized_specialty_display_and_tracks_canonical() -> None:
    service = DoctorRecommendationService()

    finalized = service._finalize_symptom_analysis_output(
        {
            "primary_category": "gastrointestinal",
            "severity": 4,
            "urgency": "low",
            "recommended_specializations": ["গ্যাস্ট্রোএন্টেরোলজি"],
            "triage_note": "রিপোর্টটি বিশেষজ্ঞকে দেখানো উচিত।",
        },
        language="bn",
    )

    assert finalized["recommended_specializations"] == ["গ্যাস্ট্রোএন্টেরোলজি"]
    assert finalized["recommended_specializations_canonical"] == ["Gastroenterology"]


def test_calculate_condition_match_normalizes_case() -> None:
    service = DoctorRecommendationService()
    doctor = _make_doctor(
        doctor_id="kidney",
        name="Kidney Doctor",
        specialization=["Nephrology"],
        conditions_treated=["hypertension", "ckd"],
    )

    score = service._calculate_condition_match(
        doctor,
        {"chronic_conditions": ["Hypertension", "CKD"]},
    )

    assert score == 1.0


def test_sanitize_report_analysis_replaces_fragmentary_blurbs_and_normalizes_labels() -> None:
    service = DoctorRecommendationService()

    report_analysis = service._sanitize_report_analysis(
        {
            "lab_findings": [
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
            "overall_assessment": "Kidney-related abnormalities need follow-up.",
        }
    )

    first = report_analysis["lab_findings"][0]
    second = report_analysis["lab_findings"][1]

    assert first["test_name"] == "Blood Urea"
    assert first["ai_analysis"] == ""
    assert second["test_name"] == "Serum Creatinine"
    assert second["ai_analysis"] == ""


def test_sanitize_prescription_analysis_keeps_clinical_reasoning_fields() -> None:
    service = DoctorRecommendationService()

    prescription_analysis = service._sanitize_prescription_analysis(
        {
            "medication_breakdown": [
                {
                    "medication_name": "Pantoprazole 40 mg",
                    "condition_treated": "gastric irritation",
                    "why_prescribed": "Likely prescribed to reduce acid-related stomach irritation from concurrent medicines.",
                    "how_it_works": "Reduces acid production in the stomach to help healing and symptom control.",
                    "key_instructions": "Take after food",
                    "things_to_know": ["May cause mild nausea"],
                    "ai_analysis": (
                        "Pantoprazole is likely being used to protect the stomach lining. "
                        "It helps reduce acid while the main treatment plan continues."
                    ),
                }
            ],
            "interaction_alerts": [
                {
                    "drugs": ["Pantoprazole", "Clopidogrel"],
                    "severity": "moderate",
                    "alert": "Possible interaction that may reduce antiplatelet effect.",
                    "action": "Discuss whether timing adjustment or alternative acid suppression is needed.",
                }
            ],
            "contraindication_flags": ["Use caution with severe kidney disease"],
        }
    )

    med = prescription_analysis["medication_breakdown"][0]
    assert med["condition_treated"] == "gastric irritation"
    assert med["why_prescribed"].startswith("Likely prescribed to reduce acid-related stomach irritation")
    assert med["how_it_works"].startswith("Reduces acid production")
    assert med["key_instructions"] == "Take after food."
    assert med["things_to_know"] == ["May cause mild nausea."]
    assert prescription_analysis["interaction_alerts"][0]["severity"] == "moderate"
    assert prescription_analysis["contraindication_flags"] == ["Use caution with severe kidney disease."]


def test_sanitize_report_analysis_exposes_noteworthy_findings_and_action_summary() -> None:
    service = DoctorRecommendationService()

    report_analysis = service._sanitize_report_analysis(
        {
            "lab_findings": [
                {
                    "test_name": "ALT (SGPT)",
                    "observed_value": "42.7",
                    "status": "abnormal",
                    "ai_analysis": "ALT is mildly above range and may indicate liver irritation.",
                },
                {
                    "test_name": "Bilirubin",
                    "observed_value": "0.8",
                    "status": "normal",
                    "ai_analysis": "Bilirubin is within the expected range.",
                },
            ],
            "patient_action_summary": [
                "Review this liver profile with your treating clinician.",
                "Avoid alcohol until your doctor confirms the trend is stable.",
            ],
            "overall_assessment": "",
        }
    )

    assert report_analysis["overall_assessment"]
    assert report_analysis["patient_action_summary"] == [
        "Review this liver profile with your treating clinician.",
        "Avoid alcohol until your doctor confirms the trend is stable.",
    ]
    assert len(report_analysis["noteworthy_findings"]) == 1
    assert report_analysis["noteworthy_findings"][0]["test_name"] == "ALT (SGPT)"


def test_build_default_follow_up_questions_prioritizes_renal_case_details() -> None:
    service = DoctorRecommendationService()

    questions = service._build_default_follow_up_questions(
        ["I have got pain on my right kidney and fever"],
        diagnosis="Right Renal Calculi",
        medications=[{"name": "HTZ 25 mg"}],
        report_findings=[
            {"test_name": "Bi. Urea", "status": "abnormal"},
            {"test_name": "S. Creatinine", "status": "abnormal"},
            {"test_name": "Sodium", "status": "abnormal"},
        ],
        document_summary="Elevated creatinine and urea indicate possible kidney dysfunction.",
    )

    intents = [service._follow_up_question_intent(question) for question in questions]
    joined = " ".join(question.lower() for question in questions)

    assert 4 <= len(questions) <= 6
    assert len(intents) == len(set(intents))
    assert "temperature" in joined or "fever" in joined
    assert "urine" in joined
    assert "0 to 10" in joined or "groin" in joined
    assert any(intent == "onset_course" for intent in intents)


def test_build_default_follow_up_questions_localizes_to_bangla() -> None:
    service = DoctorRecommendationService()

    questions = service._build_default_follow_up_questions(
        ["I have got pain on my right kidney and fever"],
        diagnosis="Right Renal Calculi",
        medications=[{"name": "HTZ 25 mg"}],
        language="bn",
    )

    assert questions
    assert any(_contains_bangla(question) for question in questions)
    assert any("প্রস্রাব" in question or "ব্যথা" in question for question in questions)


def test_ensure_doctor_style_follow_up_questions_dedupes_by_intent() -> None:
    service = DoctorRecommendationService()

    questions = service._ensure_doctor_style_follow_up_questions(
        [
            "When did these symptoms start, and have they been constant or coming and going?",
            "Since these symptoms started, have they been constant, coming and going, or clearly getting worse?",
            "Have you noticed any changes in urination?",
            "What is your current temperature?",
        ]
    )

    intents = [service._follow_up_question_intent(question) for question in questions]

    assert intents.count("onset_course") == 1
    assert any(intent == "urinary_changes" for intent in intents)
    assert any(intent == "fever_systemic" for intent in intents)


def test_default_medication_brief_analysis_returns_none_without_ai_content() -> None:
    service = DoctorRecommendationService()

    analysis = service._build_default_medication_brief_analysis("ATOVA 10 mg", None, None)

    assert analysis is None


def test_sanitizers_strip_literal_null_placeholders_from_ai_text() -> None:
    service = DoctorRecommendationService()

    prescription_analysis = service._sanitize_prescription_analysis(
        {
            "medication_breakdown": [
                {
                    "medication_name": "Cap. Roxim 200mg",
                    "condition_treated": "null",
                    "ai_analysis": "null",
                }
            ],
            "overall_assessment": "null",
        }
    )
    report_analysis = service._sanitize_report_analysis(
        {
            "lab_findings": [
                {
                    "test_name": "ALT (SGPT)",
                    "observed_value": "42.7",
                    "status": "abnormal",
                    "ai_analysis": "ALT is mildly above range and should be reviewed.",
                }
            ],
            "overall_assessment": "null Document appears to be a medical report.",
        }
    )

    assert "null" not in prescription_analysis["medication_breakdown"][0]["ai_analysis"].lower()
    assert report_analysis["overall_assessment"] == "Document appears to be a medical report."


def test_build_default_report_analysis_keeps_structure_without_localized_fallback_copy() -> None:
    service = DoctorRecommendationService()

    report_analysis = service._build_default_report_analysis(
        [
            {
                "test_name": "S. Creatinine",
                "observed_value": "131.0 µmol/L",
                "status": "abnormal",
            }
        ],
        None,
        language="bn",
    )

    assert report_analysis["overall_assessment"] is None
    assert report_analysis["lab_findings"][0]["ai_analysis"] == ""
    assert report_analysis["patient_action_summary"] == []
    assert report_analysis["noteworthy_findings"][0]["test_name"] == "Serum Creatinine"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("symptoms", "expected_specialty"),
    [
        (["flank pain", "blood in urine"], "Urology"),
        (["chest pain on exertion", "palpitations"], "Cardiology"),
        (["cough for 10 days", "wheezing"], "Pulmonology"),
        (["fatigue for two days"], "Internal Medicine"),
    ],
)
async def test_rule_based_symptom_analysis_stays_conservative_for_representative_cases(
    monkeypatch: pytest.MonkeyPatch,
    symptoms: list[str],
    expected_specialty: str,
) -> None:
    service = DoctorRecommendationService()
    monkeypatch.setattr(service, "_analyze_symptoms_with_llm", AsyncMock(return_value=None))

    analysis = await service._analyze_symptoms(symptoms)

    assert analysis["recommended_specializations"][0] == expected_specialty


@pytest.mark.asyncio
async def test_rule_based_symptom_analysis_keeps_text_fields_empty_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DoctorRecommendationService()
    monkeypatch.setattr(service, "_analyze_symptoms_with_llm", AsyncMock(return_value=None))

    analysis = await service._analyze_symptoms(
        ["flank pain", "blood in urine"],
        language="bn",
    )

    assert analysis["analysis_source"] == "rules"
    assert analysis["triage_note"] == ""
    assert analysis["additional_information_assessment"] == ""
    assert analysis["recommended_next_steps"] == []
    assert 4 <= len(analysis["follow_up_questions"]) <= 6
    assert all(_contains_bangla(question) for question in analysis["follow_up_questions"])


@pytest.mark.asyncio
async def test_analyze_symptoms_document_only_context_uses_llm_without_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DoctorRecommendationService()
    llm_payload = {
        "confidence_score": 0.22,
        "primary_category": "gastrointestinal",
        "severity": 4,
        "urgency": "soon",
        "recommended_specializations": ["Gastroenterology"],
        "triage_note": "Follow-up with Gastroenterology is appropriate for diverticular disease review.",
        "clinical_impression": (
            "Diverticular disease follow-up with mild liver enzyme abnormality should stay under digestive specialist review."
        ),
        "follow_up_questions": [
            "Have you had abdominal pain, constipation, fever, or blood in the stool recently?"
        ],
        "immediate_suggestions": [
            "Please review the digestive symptoms with the treating specialist."
        ],
        "concerning_things_to_monitor": [
            "New rectal bleeding or worsening abdominal pain."
        ],
        "prescription_analysis": {
            "medication_breakdown": [
                {
                    "medication_name": "Ispahusk Plus",
                    "condition_treated": "bowel regularity",
                    "ai_analysis": "Ispahusk Plus adds fiber to support bowel regularity in diverticular disease.",
                },
                {
                    "medication_name": "Cap. Roxim 200mg",
                    "condition_treated": "infection coverage",
                    "ai_analysis": "Roxim is cefixime-family antibiotic coverage when bacterial infection is being considered.",
                },
            ],
            "overall_assessment": "Current medicines support diverticular follow-up.",
        },
        "report_analysis": {
            "lab_findings": [
                {
                    "test_name": "ALT (SGPT)",
                    "observed_value": "42.7",
                    "status": "abnormal",
                    "ai_analysis": "ALT is mildly above the listed range and should be reviewed with the treating digestive specialist.",
                }
            ],
            "overall_assessment": "ALT is mildly elevated; the rest of the shown liver profile is reassuring.",
        },
    }
    service.llm_client.complete_json = AsyncMock(return_value=llm_payload)

    analysis = await service._analyze_symptoms(
        [],
        medications=[
            {"name": "Ispahusk Plus"},
            {"name": "Cap. Roxim 200mg"},
        ],
        diagnosis="Diverticulum",
        report_findings=[
            {"test_name": "ALT (SGPT)", "observed_value": "42.7", "status": "abnormal"},
            {"test_name": "Bilirubin", "observed_value": "0.5", "status": "normal"},
        ],
        document_summary="Liver function test with mild ALT elevation.",
        doctor_specialization="Hepatobiliary Pancreatic Surgery",
    )

    assert analysis["analysis_source"] == "openai"
    assert analysis["recommended_specializations"][0] == "Gastroenterology"
    assert "Internal Medicine" not in analysis["recommended_specializations"]
    assert analysis["follow_up_questions"]
    assert analysis["immediate_actions"] == [
        "Please review the digestive symptoms with the treating specialist."
    ]
    assert analysis["red_flags_to_watch"] == [
        "New rectal bleeding or worsening abdominal pain."
    ]
    assert analysis["prescription_analysis"]["medication_breakdown"][0]["ai_analysis"]


@pytest.mark.asyncio
async def test_analyze_symptoms_with_llm_repairs_mismatched_language_fields() -> None:
    service = DoctorRecommendationService()
    raw_payload = {
        "confidence_score": 0.72,
        "primary_category": "gastrointestinal",
        "severity": 4,
        "urgency": "low",
        "recommended_specializations": ["Gastroenterology"],
        "triage_note": "Please follow up with a specialist.",
        "clinical_impression": "This result needs digestive review.",
        "follow_up_questions": [
            "আপনার কি পেটের ব্যথা হচ্ছে?",
            "আপনার কি জন্ডিস হয়েছে?",
        ],
        "recommended_next_steps": ["See a gastroenterologist."],
        "report_analysis": {
            "lab_findings": [
                {
                    "test_name": "Bilirubin",
                    "observed_value": "0.5",
                    "status": "normal",
                    "ai_analysis": "আপনার বিলিরুবিন স্বাভাবিক আছে।",
                }
            ],
            "overall_assessment": "আপনার রিপোর্টে বড় কোনো সমস্যা দেখা যাচ্ছে না।",
        },
    }
    repaired_payload = {
        **raw_payload,
        "follow_up_questions": [
            "Are you having abdominal pain?",
            "Have you noticed yellowing of the skin or eyes?",
        ],
        "report_analysis": {
            "lab_findings": [
                {
                    "test_name": "Liver Function Test",
                    "observed_value": "0.5",
                    "status": "normal",
                    "ai_analysis": "Your bilirubin level is within the normal range.",
                }
            ],
            "overall_assessment": "Your report does not show a major issue.",
        },
    }
    service.llm_client.complete_json = AsyncMock(side_effect=[raw_payload, repaired_payload])

    analysis = await service._analyze_symptoms([], document_summary="ALT mildly elevated.", language="en")

    assert analysis["analysis_source"] == "openai"
    assert 4 <= len(analysis["follow_up_questions"]) <= 6
    assert all(not _contains_bangla(question) for question in analysis["follow_up_questions"])
    assert analysis["report_analysis"]["lab_findings"][0]["test_name"] == "Bilirubin"
    assert analysis["report_analysis"]["lab_findings"][0]["ai_analysis"] == ""


@pytest.mark.asyncio
async def test_analyze_symptoms_preserves_source_report_labels_when_llm_renames_them() -> None:
    service = DoctorRecommendationService()
    service.llm_client.complete_json = AsyncMock(
        return_value={
            "confidence_score": 0.74,
            "primary_category": "gastrointestinal",
            "severity": 4,
            "urgency": "low",
            "recommended_specializations": ["গ্যাস্ট্রোএন্টেরোলজি"],
            "triage_note": "গ্যাস্ট্রোএন্টেরোলজির পরামর্শ নিন।",
            "clinical_impression": "ALT সামান্য বেশি।",
            "follow_up_questions": ["আপনার কি পেটের অস্বস্তি আছে?"],
            "report_analysis": {
                "lab_findings": [
                    {
                        "test_name": "Liver Function Test",
                        "observed_value": "0.5",
                        "status": "normal",
                        "ai_analysis": "বিলিরুবিন স্বাভাবিক আছে।",
                    },
                    {
                        "test_name": "ALT (SGPT)",
                        "observed_value": "42.7",
                        "status": "abnormal",
                        "ai_analysis": "ALT একটু বেশি।",
                    },
                ],
                "overall_assessment": "একটি মান অস্বাভাবিক।",
            },
        }
    )

    analysis = await service._analyze_symptoms(
        [],
        report_findings=[
            {"test_name": "Bilirubin", "observed_value": "0.5", "status": "normal"},
            {"test_name": "ALT (SGPT)", "observed_value": "42.7", "status": "abnormal"},
        ],
        language="bn",
    )

    assert analysis["recommended_specializations"] == ["গ্যাস্ট্রোএন্টেরোলজি"]
    assert analysis["recommended_specializations_canonical"] == ["Gastroenterology"]
    assert analysis["report_analysis"]["lab_findings"][0]["test_name"] == "Bilirubin"
    assert analysis["report_analysis"]["lab_findings"][1]["test_name"] == "ALT (SGPT)"


@pytest.mark.asyncio
async def test_score_and_rank_prefers_specialty_match_and_continuity_of_care(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DoctorRecommendationService()
    llm_rationale_mock = AsyncMock(return_value={})
    monkeypatch.setattr(service, "_generate_doctor_rationales_with_llm", llm_rationale_mock)

    candidates = [
        _make_doctor(
            doctor_id="kidney",
            name="Kidney Doctor",
            specialization=["Nephrology"],
            experience_years=12,
            average_rating=4.4,
            conditions_treated=["hypertension"],
        ),
        _make_doctor(
            doctor_id="general",
            name="General Doctor",
            specialization=["General Medicine"],
            experience_years=18,
            average_rating=4.9,
            conditions_treated=["hypertension"],
        ),
    ]
    symptom_analysis = {
        "primary_category": "general",
        "severity": 4,
        "urgency": "moderate",
        "recommended_specializations": ["Nephrology"],
        "symptom_descriptions": ["mild lab abnormality"],
        "recommended_next_steps": ["Arrange follow-up."],
    }
    medical_history = {
        "previous_specializations": ["Kidney Specialist"],
        "chronic_conditions": ["hypertension"],
    }

    ranked = await service._score_and_rank(candidates, symptom_analysis, medical_history, preferences=None)

    assert ranked[0]["doctor_id"] == "kidney"
    assert ranked[0]["reasoning_source"] == "rules"
    assert llm_rationale_mock.await_count == 1


@pytest.mark.asyncio
async def test_analyze_symptoms_with_llm_low_confidence_returns_none_without_crashing() -> None:
    service = DoctorRecommendationService()
    service.llm_client.complete_json = AsyncMock(
        return_value={
            "confidence_score": 0.2,
            "primary_category": "general",
            "severity": 3,
            "urgency": "low",
        }
    )

    result = await service._analyze_symptoms_with_llm(["fatigue"])

    assert result is None


@pytest.mark.asyncio
async def test_generate_external_doctor_previews_falls_back_to_rules_when_llm_signal_is_weak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DoctorRecommendationService()
    service.llm_client.complete_json = AsyncMock(
        return_value={
            "confidence_score": 0.2,
            "primary_category": "general",
            "severity": 3,
            "urgency": "low",
        }
    )
    monkeypatch.setattr(service, "_generate_doctor_rationales_with_llm", AsyncMock(return_value={}))

    previews, analysis_source = await service.generate_external_doctor_previews(
        symptoms=["fatigue"],
        doctors=[
            {
                "doctor_id": "doc-1",
                "name": "Dr. General",
                "specialization": ["General Medicine"],
                "experience_years": 12,
                "average_rating": 4.7,
            }
        ],
    )

    assert analysis_source == "rules"
    assert "doc-1" in previews
    assert previews["doc-1"]["reasons"] == []
    assert previews["doc-1"]["fit_summary"] == ""


@pytest.mark.asyncio
async def test_fetch_public_doctor_candidates_uses_in_process_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DoctorRecommendationService()
    candidate = _make_doctor(
        doctor_id="doc-1",
        name="Dr. Cached",
        specialization=["Cardiology"],
    )
    loader = AsyncMock(return_value=[candidate])

    monkeypatch.setattr(service, "_load_public_doctor_candidates", loader)
    monkeypatch.setattr(service, "_public_doctor_candidates_cache", None)
    monkeypatch.setattr(service, "_public_doctor_candidates_cache_expires_at", 0.0)
    monkeypatch.setattr(service, "_public_doctor_candidates_pending_task", None)
    monkeypatch.setattr(
        "app.services.doctor_recommendation_service.settings.PUBLIC_DOCTOR_API_CACHE_TTL_SECONDS",
        300.0,
        raising=False,
    )

    first = await service._fetch_public_doctor_candidates()
    second = await service._fetch_public_doctor_candidates()

    assert [item.id for item in first] == ["doc-1"]
    assert [item.id for item in second] == ["doc-1"]
    assert loader.await_count == 1
