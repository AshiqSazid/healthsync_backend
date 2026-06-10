# from __future__ import annotations

# from collections.abc import Iterable
# import re


# SPECIALTY_LABELS: dict[str, str] = {
#     "allergy": "Allergy and Immunology",
#     "cardiac": "Cardiology",
#     "dermatology": "Dermatology",
#     "endocrinology": "Endocrinology",
#     "ent": "ENT",
#     "gastroenterology": "Gastroenterology",
#     "internal_medicine": "Internal Medicine",
#     "nephrology": "Nephrology",
#     "neurology": "Neurology",
#     "obgyn": "Obstetrics & Gynecology",
#     "oncology": "Clinical Oncology",
#     "ophthalmology": "Ophthalmology",
#     "orthopedics": "Orthopedic Surgery",
#     "pathology": "Pathology",
#     "pediatrics": "Pediatrics",
#     "psychiatry": "Psychiatry",
#     "pulmonology": "Pulmonology",
#     "rheumatology": "Rheumatology",
#     "urology": "Urology",
# }

# SPECIALTY_ALIASES: dict[str, str] = {
#     "allergy": "allergy",
#     "allergy and immunology": "allergy",
#     "cardiac": "cardiac",
#     "cardiac surgery": "cardiac",
#     "cardiologist": "cardiac",
#     "cardiology": "cardiac",
#     "chest medicine": "pulmonology",
#     "chest specialist": "pulmonology",
#     "clinical oncology": "oncology",
#     "consultant pathologist": "pathology",
#     "dermatologist": "dermatology",
#     "dermatology": "dermatology",
#     "diabetes specialist": "endocrinology",
#     "endocrinologist": "endocrinology",
#     "endocrinology": "endocrinology",
#     "ent": "ent",
#     "ent specialist": "ent",
#     "eye specialist": "ophthalmology",
#     "gastroenterologist": "gastroenterology",
#     "gastroenterology": "gastroenterology",
#     "hepatobiliary pancreatic surgery": "gastroenterology",
#     "hepatobiliary surgery": "gastroenterology",
#     "hepato biliary pancreatic surgery": "gastroenterology",
#     "hpb surgery": "gastroenterology",
#     "general medicine": "internal_medicine",
#     "general physician": "internal_medicine",
#     "heart specialist": "cardiac",
#     "internal medicine": "internal_medicine",
#     "interventional cardiology": "cardiac",
#     "kidney and urology": "urology",
#     "kidney specialist": "nephrology",
#     "kidney specialist medicine": "nephrology",
#     "kidney & urology": "urology",
#     "medical oncology": "oncology",
#     "medicine specialist": "internal_medicine",
#     "nephrologist": "nephrology",
#     "nephrology": "nephrology",
#     "neuro medicine": "neurology",
#     "neurologist": "neurology",
#     "neurology": "neurology",
#     "obstetrics and gynecology": "obgyn",
#     "obstetrician and gynecologist": "obgyn",
#     "obstetrics & gynecology": "obgyn",
#     "oncologist": "oncology",
#     "oncology": "oncology",
#     "oncoplastic breast surgery": "oncology",
#     "ophthalmologist": "ophthalmology",
#     "ophthalmology": "ophthalmology",
#     "orthopedic surgeon": "orthopedics",
#     "orthopedics": "orthopedics",
#     "pathologist": "pathology",
#     "pathology": "pathology",
#     "pediatrician": "pediatrics",
#     "pediatrics": "pediatrics",
#     "prof harun ur rashid mbbs ph d fcps frcp": "internal_medicine",
#     "psychiatrist": "psychiatry",
#     "psychiatry": "psychiatry",
#     "pulmonologist": "pulmonology",
#     "pulmonology": "pulmonology",
#     "radiotherapy": "oncology",
#     "renal specialist": "nephrology",
#     "respiratory medicine": "pulmonology",
#     "rheumatologist": "rheumatology",
#     "rheumatology": "rheumatology",
#     "skin specialist": "dermatology",
#     "stroke and neuro intervention": "neurology",
#     "surgical oncology": "oncology",
#     "urologist": "urology",
#     "urology": "urology",
#     "ইন্টার্নাল মেডিসিন বিশেষজ্ঞ": "internal_medicine",
#     "এন্ডোক্রিনোলজি": "endocrinology",
#     "অর্থোপেডিক সার্জন": "orthopedics",
#     "ইউরোলজি": "urology",
#     "ক্যান্সার বিশেষজ্ঞ": "oncology",
#     "কার্ডিওলজি": "cardiac",
#     "গ্যাস্ট্রোএন্টেরোলজি": "gastroenterology",
#     "চক্ষু বিশেষজ্ঞ": "ophthalmology",
#     "চর্মরোগ বিশেষজ্ঞ": "dermatology",
#     "জেনারেল ফিজিশিয়ান": "internal_medicine",
#     "নাক কান গলা বিশেষজ্ঞ": "ent",
#     "নাফ্রোলজি": "nephrology",
#     "নেফ্রোলজি": "nephrology",
#     "নিউরোলজি": "neurology",
#     "প্রসূতি ও স্ত্রী রোগ বিশেষজ্ঞ": "obgyn",
#     "ফুসফুলোগ বিশেষজ্ঞ": "pulmonology",
#     "মানসিক রোগ বিশেষজ্ঞ": "psychiatry",
#     "রিউমাটয়ড বিশেষজ্ঞ": "rheumatology",
#     "শিশু রোগ বিশেষজ্ঞ": "pediatrics",
#     "হৃদরোগ বিশেষজ্ঞ": "cardiac",
# }

# CATEGORY_FALLBACK_SPECIALTIES: dict[str, str] = {
#     "cardiac": "Cardiology",
#     "dermatology": "Dermatology",
#     "endocrinology": "Endocrinology",
#     "gastrointestinal": "Gastroenterology",
#     "general": "Internal Medicine",
#     "neurology": "Neurology",
#     "oncology": "Clinical Oncology",
#     "respiratory": "Pulmonology",
#     "urology": "Urology",
# }

# GENERAL_SPECIALTIES = {"Internal Medicine"}

# REPORT_TEST_PREFIX_EXPANSIONS: dict[str, str] = {
#     "s": "Serum",
#     "serum": "Serum",
#     "bi": "Blood",
#     "blood": "Blood",
#     "u": "Urine",
#     "urine": "Urine",
# }

# LOW_VALUE_REPORT_ANALYSIS_TOKENS = {
#     "analysis",
#     "blood",
#     "bi",
#     "finding",
#     "report",
#     "result",
#     "s",
#     "serum",
#     "test",
# }

# MEDICATION_GENERIC_HINTS: dict[str, str] = {
#     "aspirin": "aspirin",
#     "atorvastatin": "atorvastatin",
#     "cilnidipine": "cilnidipine",
#     "clonazepam": "clonazepam",
#     "clopidogrel": "clopidogrel",
#     "domperidone": "domperidone",
#     "esomeprazole": "esomeprazole",
#     "hydrochlorothiazide": "hydrochlorothiazide",
#     "metformin": "metformin",
#     "multivitamin": "multivitamin",
#     "pancreatic enzyme": "pancreatic enzyme",
# }

# MEDICATION_GENERIC_ALIASES: dict[str, str] = {
#     "atova": "atorvastatin",
#     "bextram": "multivitamin",
#     "bextram silver": "multivitamin",
#     "cilidip": "cilnidipine",
#     "clob": "clopidogrel",
#     "clo8": "clopidogrel",
#     "ecosprin": "aspirin",
#     "htz": "hydrochlorothiazide",
#     "maxpro": "esomeprazole",
#     "omidon": "domperidone",
#     "rivotril": "clonazepam",
#     "zymet": "metformin",
# }


# def normalize_text(value: str) -> str:
#     clean = str(value or "").strip().lower()
#     for char in [",", ".", ";", ":", "(", ")", "[", "]", "{", "}", "/"]:
#         clean = clean.replace(char, " ")
#     clean = clean.replace("&", " and ")
#     clean = clean.replace("-", " ")
#     return " ".join(clean.split())


# def normalize_report_test_name(value: str | None) -> str:
#     text = str(value or "").strip()
#     if not text:
#         return ""

#     clean = re.sub(r"\s+", " ", text).strip(" -:;,")
#     match = re.match(r"^(?P<prefix>[A-Za-z]{1,8})(?:\.)?\s+(?P<rest>.+)$", clean)
#     if not match:
#         return clean

#     prefix = normalize_text(match.group("prefix"))
#     rest = re.sub(r"\s+", " ", match.group("rest")).strip(" -:;,")
#     expanded = REPORT_TEST_PREFIX_EXPANSIONS.get(prefix)
#     if not expanded or not rest:
#         return clean
#     return f"{expanded} {rest}"


# def is_low_value_report_analysis(value: str | None, test_name: str | None = None) -> bool:
#     text = re.sub(r"\s+", " ", str(value or "").strip())
#     if not text:
#         return True

#     normalized = normalize_text(text)
#     if not normalized:
#         return True

#     normalized_test_name = normalize_text(normalize_report_test_name(test_name or ""))
#     tokens = normalized.split()
#     if normalized in LOW_VALUE_REPORT_ANALYSIS_TOKENS:
#         return True
#     if len(tokens) == 1 and (tokens[0] in LOW_VALUE_REPORT_ANALYSIS_TOKENS or len(tokens[0]) <= 4):
#         return True
#     if len(tokens) < 3 and not any(char.isdigit() for char in normalized):
#         return True

#     if normalized_test_name:
#         if normalized == normalized_test_name:
#             return True
#         test_tokens = normalized_test_name.split()
#         if len(tokens) == 1 and tokens[0] in set(test_tokens):
#             return True
#         if len(tokens) <= 2 and normalized in {
#             f"{normalized_test_name} analysis",
#             f"{normalized_test_name} result",
#             f"{normalized_test_name} finding",
#         }:
#             return True

#     return False


# def specialty_domain(value: str | None) -> str | None:
#     normalized = normalize_text(value or "")
#     if not normalized:
#         return None
#     if normalized in SPECIALTY_ALIASES:
#         return SPECIALTY_ALIASES[normalized]
#     for alias, domain in SPECIALTY_ALIASES.items():
#         if alias in normalized or normalized in alias:
#             return domain
#     return None


# def canonical_specialty(value: str | None) -> str | None:
#     domain = specialty_domain(value)
#     return SPECIALTY_LABELS.get(domain) if domain else None


# def canonical_specialties(
#     values: Iterable[str],
#     *,
#     primary_category: str | None = None,
#     include_fallback: bool = False,
#     limit: int = 6,
#     drop_general_when_specific: bool = True,
# ) -> list[str]:
#     ordered: list[str] = []
#     seen_domains: set[str] = set()

#     for item in values:
#         domain = specialty_domain(item)
#         if not domain or domain in seen_domains:
#             continue
#         seen_domains.add(domain)
#         ordered.append(SPECIALTY_LABELS[domain])
#         if len(ordered) >= limit:
#             break

#     fallback = CATEGORY_FALLBACK_SPECIALTIES.get(normalize_text(primary_category or ""))
#     if include_fallback and fallback and fallback not in ordered and len(ordered) < limit:
#         ordered.append(fallback)

#     if drop_general_when_specific and len(ordered) > 1:
#         ordered = [item for item in ordered if item not in GENERAL_SPECIALTIES] or ordered[:1]

#     return ordered[:limit]


# def merge_specialties(
#     *collections: Iterable[str],
#     primary_category: str | None = None,
#     include_fallback: bool = False,
#     limit: int = 6,
#     drop_general_when_specific: bool = True,
# ) -> list[str]:
#     merged: list[str] = []
#     for collection in collections:
#         merged.extend([str(item).strip() for item in collection if str(item).strip()])
#     return canonical_specialties(
#         merged,
#         primary_category=primary_category,
#         include_fallback=include_fallback,
#         limit=limit,
#         drop_general_when_specific=drop_general_when_specific,
#     )


# def specialty_matches(left: str | None, right: str | None) -> bool:
#     left_domain = specialty_domain(left)
#     right_domain = specialty_domain(right)
#     return bool(left_domain and right_domain and left_domain == right_domain)


# def medication_concepts(name: str | None, purpose: str | None = None) -> list[str]:
#     concepts: list[str] = []
#     normalized_name = normalize_text(name or "")
#     normalized_purpose = normalize_text(purpose or "")

#     if normalized_name:
#         concepts.append(normalized_name)

#     explicit_hints = [
#         concept
#         for phrase, concept in MEDICATION_GENERIC_HINTS.items()
#         if phrase in normalized_name or phrase in normalized_purpose
#     ]
#     concepts.extend(explicit_hints)

#     for alias, generic in MEDICATION_GENERIC_ALIASES.items():
#         if alias in normalized_name:
#             if explicit_hints and generic not in explicit_hints:
#                 continue
#             concepts.append(generic)

#     if "pancreatic enzyme" in normalized_purpose:
#         concepts.append("pancreatic enzyme")

#     deduped: list[str] = []
#     seen: set[str] = set()
#     for item in concepts:
#         if item in seen:
#             continue
#         seen.add(item)
#         deduped.append(item)
#     return deduped
from __future__ import annotations

from collections.abc import Iterable
import re


SPECIALTY_LABELS: dict[str, str] = {
    "allergy": "Allergy and Immunology",
    "anesthesiology": "Anesthesiology",
    "cardiac": "Cardiology",
    "cardiothoracic": "Cardiothoracic Surgery",
    "dentistry": "Dentistry",
    "dermatology": "Dermatology",
    "emergency": "Emergency Medicine",
    "endocrinology": "Endocrinology",
    "ent": "ENT",
    "family_medicine": "Family Medicine",
    "gastroenterology": "Gastroenterology",
    "general_surgery": "General Surgery",
    "geriatrics": "Geriatrics",
    "hematology": "Hematology",
    "hepatology": "Hepatology",
    "infectious_disease": "Infectious Disease",
    "internal_medicine": "Internal Medicine",
    "nephrology": "Nephrology",
    "neurology": "Neurology",
    "neurosurgery": "Neurosurgery",
    "nutrition": "Nutrition and Dietetics",
    "obgyn": "Obstetrics & Gynecology",
    "oncology": "Clinical Oncology",
    "ophthalmology": "Ophthalmology",
    "oral_maxillofacial": "Oral and Maxillofacial Surgery",
    "orthopedics": "Orthopedic Surgery",
    "pain_medicine": "Pain Medicine",
    "pathology": "Pathology",
    "pediatrics": "Pediatrics",
    "physical_medicine": "Physical Medicine and Rehabilitation",
    "plastic_surgery": "Plastic Surgery",
    "psychiatry": "Psychiatry",
    "pulmonology": "Pulmonology",
    "radiology": "Radiology",
    "rheumatology": "Rheumatology",
    "sports_medicine": "Sports Medicine",
    "urology": "Urology",
    "vascular_surgery": "Vascular Surgery",
}

SPECIALTY_ALIASES: dict[str, str] = {
    # Allergy / Immunology
    "allergy": "allergy",
    "allergy and immunology": "allergy",
    "allergist": "allergy",
    "immunologist": "allergy",
    "clinical immunology": "allergy",
    # Anesthesiology
    "anesthesiology": "anesthesiology",
    "anaesthesiology": "anesthesiology",
    "anesthesiologist": "anesthesiology",
    "anaesthetist": "anesthesiology",
    # Cardiology
    "cardiac": "cardiac",
    "cardiologist": "cardiac",
    "cardiology": "cardiac",
    "heart specialist": "cardiac",
    "interventional cardiology": "cardiac",
    "electrophysiology": "cardiac",
    "pediatric cardiology": "cardiac",
    "heart failure specialist": "cardiac",
    # Cardiothoracic
    "cardiac surgery": "cardiothoracic",
    "cardiothoracic surgery": "cardiothoracic",
    "thoracic surgery": "cardiothoracic",
    "cvts": "cardiothoracic",
    # Dentistry
    "dentist": "dentistry",
    "dental surgeon": "dentistry",
    "dentistry": "dentistry",
    "orthodontist": "dentistry",
    "endodontist": "dentistry",
    "periodontist": "dentistry",
    "prosthodontist": "dentistry",
    # Dermatology
    "dermatologist": "dermatology",
    "dermatology": "dermatology",
    "skin specialist": "dermatology",
    "cosmetic dermatology": "dermatology",
    "venereology": "dermatology",
    "dermatovenereology": "dermatology",
    # Emergency
    "emergency medicine": "emergency",
    "emergency physician": "emergency",
    "er doctor": "emergency",
    "casualty": "emergency",
    # Endocrinology
    "endocrinologist": "endocrinology",
    "endocrinology": "endocrinology",
    "diabetes specialist": "endocrinology",
    "diabetologist": "endocrinology",
    "thyroid specialist": "endocrinology",
    "hormone specialist": "endocrinology",
    # ENT
    "ent": "ent",
    "ent specialist": "ent",
    "otolaryngology": "ent",
    "otolaryngologist": "ent",
    "otorhinolaryngology": "ent",
    "head and neck surgery": "ent",
    # Family Medicine
    "family medicine": "family_medicine",
    "family physician": "family_medicine",
    "gp": "family_medicine",
    # Gastroenterology
    "gastroenterologist": "gastroenterology",
    "gastroenterology": "gastroenterology",
    "gastro": "gastroenterology",
    "gi specialist": "gastroenterology",
    "hepatobiliary pancreatic surgery": "gastroenterology",
    "hepatobiliary surgery": "gastroenterology",
    "hepato biliary pancreatic surgery": "gastroenterology",
    "hpb surgery": "gastroenterology",
    "colorectal surgery": "gastroenterology",
    "proctology": "gastroenterology",
    # General Surgery
    "general surgery": "general_surgery",
    "general surgeon": "general_surgery",
    "surgeon": "general_surgery",
    "laparoscopic surgery": "general_surgery",
    # Geriatrics
    "geriatrics": "geriatrics",
    "geriatrician": "geriatrics",
    "elderly care": "geriatrics",
    # Hematology
    "hematology": "hematology",
    "hematologist": "hematology",
    "haematology": "hematology",
    "blood specialist": "hematology",
    "hemato oncology": "hematology",
    # Hepatology
    "hepatology": "hepatology",
    "hepatologist": "hepatology",
    "liver specialist": "hepatology",
    # Infectious Disease
    "infectious disease": "infectious_disease",
    "infectious diseases": "infectious_disease",
    "tropical medicine": "infectious_disease",
    "hiv specialist": "infectious_disease",
    # Internal Medicine
    "general medicine": "internal_medicine",
    "general physician": "internal_medicine",
    "internal medicine": "internal_medicine",
    "medicine specialist": "internal_medicine",
    "internist": "internal_medicine",
    "prof harun ur rashid mbbs ph d fcps frcp": "internal_medicine",
    # Nephrology
    "nephrologist": "nephrology",
    "nephrology": "nephrology",
    "kidney specialist": "nephrology",
    "kidney specialist medicine": "nephrology",
    "renal specialist": "nephrology",
    "renal medicine": "nephrology",
    "dialysis specialist": "nephrology",
    # Neurology
    "neurologist": "neurology",
    "neurology": "neurology",
    "neuro medicine": "neurology",
    "stroke and neuro intervention": "neurology",
    "stroke specialist": "neurology",
    "epilepsy specialist": "neurology",
    "movement disorder": "neurology",
    # Neurosurgery
    "neurosurgery": "neurosurgery",
    "neurosurgeon": "neurosurgery",
    "brain surgery": "neurosurgery",
    "spine surgery": "neurosurgery",
    # Nutrition
    "nutrition": "nutrition",
    "nutritionist": "nutrition",
    "dietician": "nutrition",
    "dietitian": "nutrition",
    "nutrition and dietetics": "nutrition",
    # OBGYN
    "obstetrics and gynecology": "obgyn",
    "obstetrician and gynecologist": "obgyn",
    "obstetrics & gynecology": "obgyn",
    "obgyn": "obgyn",
    "gynecologist": "obgyn",
    "gynaecologist": "obgyn",
    "obstetrician": "obgyn",
    "maternal fetal medicine": "obgyn",
    "fertility specialist": "obgyn",
    "reproductive medicine": "obgyn",
    # Oncology
    "clinical oncology": "oncology",
    "oncologist": "oncology",
    "oncology": "oncology",
    "oncoplastic breast surgery": "oncology",
    "medical oncology": "oncology",
    "radiation oncology": "oncology",
    "radiotherapy": "oncology",
    "surgical oncology": "oncology",
    "cancer specialist": "oncology",
    "pediatric oncology": "oncology",
    # Ophthalmology
    "ophthalmologist": "ophthalmology",
    "ophthalmology": "ophthalmology",
    "eye specialist": "ophthalmology",
    "eye surgeon": "ophthalmology",
    "retina specialist": "ophthalmology",
    "glaucoma specialist": "ophthalmology",
    # Oral / Maxillofacial
    "oral and maxillofacial surgery": "oral_maxillofacial",
    "maxillofacial surgery": "oral_maxillofacial",
    "oral surgery": "oral_maxillofacial",
    # Orthopedics
    "orthopedic surgeon": "orthopedics",
    "orthopedics": "orthopedics",
    "orthopaedics": "orthopedics",
    "orthopaedic surgeon": "orthopedics",
    "bone specialist": "orthopedics",
    "joint specialist": "orthopedics",
    "arthroscopy": "orthopedics",
    "spine specialist": "orthopedics",
    # Pain Medicine
    "pain medicine": "pain_medicine",
    "pain specialist": "pain_medicine",
    "pain management": "pain_medicine",
    # Pathology
    "pathologist": "pathology",
    "pathology": "pathology",
    "consultant pathologist": "pathology",
    "histopathology": "pathology",
    "clinical pathology": "pathology",
    "hematopathology": "pathology",
    # Pediatrics
    "pediatrician": "pediatrics",
    "pediatrics": "pediatrics",
    "paediatrics": "pediatrics",
    "paediatrician": "pediatrics",
    "child specialist": "pediatrics",
    "neonatologist": "pediatrics",
    "neonatology": "pediatrics",
    # PM&R
    "physical medicine and rehabilitation": "physical_medicine",
    "physiatrist": "physical_medicine",
    "rehabilitation medicine": "physical_medicine",
    "physiotherapy": "physical_medicine",
    "physiotherapist": "physical_medicine",
    # Plastic Surgery
    "plastic surgery": "plastic_surgery",
    "plastic surgeon": "plastic_surgery",
    "cosmetic surgery": "plastic_surgery",
    "reconstructive surgery": "plastic_surgery",
    "burn surgery": "plastic_surgery",
    # Psychiatry
    "psychiatrist": "psychiatry",
    "psychiatry": "psychiatry",
    "mental health": "psychiatry",
    "child psychiatry": "psychiatry",
    "addiction medicine": "psychiatry",
    # Pulmonology
    "pulmonologist": "pulmonology",
    "pulmonology": "pulmonology",
    "chest medicine": "pulmonology",
    "chest specialist": "pulmonology",
    "respiratory medicine": "pulmonology",
    "respirologist": "pulmonology",
    "tb specialist": "pulmonology",
    # Radiology
    "radiology": "radiology",
    "radiologist": "radiology",
    "diagnostic imaging": "radiology",
    "interventional radiology": "radiology",
    "sonologist": "radiology",
    # Rheumatology
    "rheumatologist": "rheumatology",
    "rheumatology": "rheumatology",
    "arthritis specialist": "rheumatology",
    # Sports Medicine
    "sports medicine": "sports_medicine",
    "sports injury": "sports_medicine",
    # Urology
    "urologist": "urology",
    "urology": "urology",
    "kidney and urology": "urology",
    "kidney & urology": "urology",
    "andrologist": "urology",
    "andrology": "urology",
    # Vascular
    "vascular surgery": "vascular_surgery",
    "vascular surgeon": "vascular_surgery",
    "endovascular surgery": "vascular_surgery",
    # Bengali
    "ইন্টার্নাল মেডিসিন বিশেষজ্ঞ": "internal_medicine",
    "এন্ডোক্রিনোলজি": "endocrinology",
    "অর্থোপেডিক সার্জন": "orthopedics",
    "ইউরোলজি": "urology",
    "ক্যান্সার বিশেষজ্ঞ": "oncology",
    "কার্ডিওলজি": "cardiac",
    "গ্যাস্ট্রোএন্টেরোলজি": "gastroenterology",
    "চক্ষু বিশেষজ্ঞ": "ophthalmology",
    "চর্মরোগ বিশেষজ্ঞ": "dermatology",
    "জেনারেল ফিজিশিয়ান": "internal_medicine",
    "দন্ত বিশেষজ্ঞ": "dentistry",
    "নাক কান গলা বিশেষজ্ঞ": "ent",
    "নাফ্রোলজি": "nephrology",
    "নেফ্রোলজি": "nephrology",
    "নিউরোলজি": "neurology",
    "প্রসূতি ও স্ত্রী রোগ বিশেষজ্ঞ": "obgyn",
    "ফুসফুলোগ বিশেষজ্ঞ": "pulmonology",
    "বক্ষব্যাধি বিশেষজ্ঞ": "pulmonology",
    "মানসিক রোগ বিশেষজ্ঞ": "psychiatry",
    "রক্তরোগ বিশেষজ্ঞ": "hematology",
    "রিউমাটয়ড বিশেষজ্ঞ": "rheumatology",
    "লিভার বিশেষজ্ঞ": "hepatology",
    "শিশু রোগ বিশেষজ্ঞ": "pediatrics",
    "হৃদরোগ বিশেষজ্ঞ": "cardiac",
}

# Disease / condition → specialty routing. Keys are normalized substrings.
DISEASE_TO_SPECIALTY: dict[str, str] = {
    # Cardiac
    "hypertension": "cardiac",
    "high blood pressure": "cardiac",
    "coronary artery disease": "cardiac",
    "myocardial infarction": "cardiac",
    "heart attack": "cardiac",
    "heart failure": "cardiac",
    "arrhythmia": "cardiac",
    "atrial fibrillation": "cardiac",
    "angina": "cardiac",
    "valvular heart disease": "cardiac",
    "cardiomyopathy": "cardiac",
    "pericarditis": "cardiac",
    # Endocrine
    "diabetes": "endocrinology",
    "type 1 diabetes": "endocrinology",
    "type 2 diabetes": "endocrinology",
    "hypothyroidism": "endocrinology",
    "hyperthyroidism": "endocrinology",
    "thyroid": "endocrinology",
    "goiter": "endocrinology",
    "cushing": "endocrinology",
    "addison": "endocrinology",
    "pcos": "endocrinology",
    "osteoporosis": "endocrinology",
    # Pulmonology
    "asthma": "pulmonology",
    "copd": "pulmonology",
    "bronchitis": "pulmonology",
    "pneumonia": "pulmonology",
    "tuberculosis": "pulmonology",
    "tb": "pulmonology",
    "pulmonary fibrosis": "pulmonology",
    "pulmonary embolism": "pulmonology",
    "sleep apnea": "pulmonology",
    # Gastroenterology
    "gastritis": "gastroenterology",
    "peptic ulcer": "gastroenterology",
    "gerd": "gastroenterology",
    "acid reflux": "gastroenterology",
    "ibs": "gastroenterology",
    "irritable bowel": "gastroenterology",
    "crohn": "gastroenterology",
    "ulcerative colitis": "gastroenterology",
    "pancreatitis": "gastroenterology",
    "gallstones": "gastroenterology",
    "cholecystitis": "gastroenterology",
    # Hepatology
    "hepatitis": "hepatology",
    "cirrhosis": "hepatology",
    "fatty liver": "hepatology",
    "nafld": "hepatology",
    "liver failure": "hepatology",
    # Nephrology
    "chronic kidney disease": "nephrology",
    "ckd": "nephrology",
    "acute kidney injury": "nephrology",
    "nephritis": "nephrology",
    "nephrotic syndrome": "nephrology",
    "dialysis": "nephrology",
    # Urology
    "kidney stone": "urology",
    "renal stone": "urology",
    "bph": "urology",
    "prostate enlargement": "urology",
    "uti": "urology",
    "urinary tract infection": "urology",
    "erectile dysfunction": "urology",
    # Neurology
    "stroke": "neurology",
    "epilepsy": "neurology",
    "seizure": "neurology",
    "migraine": "neurology",
    "parkinson": "neurology",
    "alzheimer": "neurology",
    "dementia": "neurology",
    "multiple sclerosis": "neurology",
    "neuropathy": "neurology",
    "bell palsy": "neurology",
    # Psychiatry
    "depression": "psychiatry",
    "anxiety": "psychiatry",
    "bipolar": "psychiatry",
    "schizophrenia": "psychiatry",
    "ocd": "psychiatry",
    "ptsd": "psychiatry",
    "adhd": "psychiatry",
    "insomnia": "psychiatry",
    # Rheumatology
    "rheumatoid arthritis": "rheumatology",
    "lupus": "rheumatology",
    "sle": "rheumatology",
    "gout": "rheumatology",
    "ankylosing spondylitis": "rheumatology",
    "psoriatic arthritis": "rheumatology",
    "vasculitis": "rheumatology",
    "fibromyalgia": "rheumatology",
    # Dermatology
    "eczema": "dermatology",
    "psoriasis": "dermatology",
    "acne": "dermatology",
    "vitiligo": "dermatology",
    "urticaria": "dermatology",
    "fungal infection": "dermatology",
    "scabies": "dermatology",
    "alopecia": "dermatology",
    "melanoma": "dermatology",
    # Oncology
    "cancer": "oncology",
    "carcinoma": "oncology",
    "lymphoma": "oncology",
    "leukemia": "oncology",
    "sarcoma": "oncology",
    "tumor": "oncology",
    "malignancy": "oncology",
    "metastasis": "oncology",
    # Hematology
    "anemia": "hematology",
    "thalassemia": "hematology",
    "sickle cell": "hematology",
    "hemophilia": "hematology",
    "thrombocytopenia": "hematology",
    # Orthopedics
    "fracture": "orthopedics",
    "osteoarthritis": "orthopedics",
    "slipped disc": "orthopedics",
    "herniated disc": "orthopedics",
    "scoliosis": "orthopedics",
    "acl injury": "orthopedics",
    "meniscus tear": "orthopedics",
    # Ophthalmology
    "cataract": "ophthalmology",
    "glaucoma": "ophthalmology",
    "diabetic retinopathy": "ophthalmology",
    "macular degeneration": "ophthalmology",
    "conjunctivitis": "ophthalmology",
    "refractive error": "ophthalmology",
    # ENT
    "sinusitis": "ent",
    "tonsillitis": "ent",
    "otitis media": "ent",
    "hearing loss": "ent",
    "vertigo": "ent",
    "deviated septum": "ent",
    # Pediatrics
    "neonatal jaundice": "pediatrics",
    "childhood fever": "pediatrics",
    "measles": "pediatrics",
    "chickenpox": "pediatrics",
    # OBGYN
    "pregnancy": "obgyn",
    "menstrual": "obgyn",
    "endometriosis": "obgyn",
    "fibroid": "obgyn",
    "menopause": "obgyn",
    "infertility": "obgyn",
    # Infectious
    "dengue": "infectious_disease",
    "malaria": "infectious_disease",
    "typhoid": "infectious_disease",
    "covid": "infectious_disease",
    "hiv": "infectious_disease",
    "sepsis": "infectious_disease",
    # Allergy
    "allergic rhinitis": "allergy",
    "food allergy": "allergy",
    "anaphylaxis": "allergy",
}

CATEGORY_FALLBACK_SPECIALTIES: dict[str, str] = {
    "cardiac": "Cardiology",
    "dermatology": "Dermatology",
    "endocrinology": "Endocrinology",
    "gastrointestinal": "Gastroenterology",
    "general": "Internal Medicine",
    "hematology": "Hematology",
    "hepatic": "Hepatology",
    "infectious": "Infectious Disease",
    "mental_health": "Psychiatry",
    "musculoskeletal": "Orthopedic Surgery",
    "neurology": "Neurology",
    "obgyn": "Obstetrics & Gynecology",
    "oncology": "Clinical Oncology",
    "ophthalmic": "Ophthalmology",
    "pediatric": "Pediatrics",
    "renal": "Nephrology",
    "respiratory": "Pulmonology",
    "rheumatology": "Rheumatology",
    "urology": "Urology",
}

GENERAL_SPECIALTIES = {"Internal Medicine", "Family Medicine"}

REPORT_TEST_PREFIX_EXPANSIONS: dict[str, str] = {
    "s": "Serum",
    "serum": "Serum",
    "bi": "Blood",
    "blood": "Blood",
    "u": "Urine",
    "urine": "Urine",
    "p": "Plasma",
    "plasma": "Plasma",
    "csf": "CSF",
    "st": "Stool",
    "stool": "Stool",
}

LOW_VALUE_REPORT_ANALYSIS_TOKENS = {
    "analysis",
    "blood",
    "bi",
    "finding",
    "report",
    "result",
    "s",
    "serum",
    "test",
    "value",
    "reading",
}

MEDICATION_GENERIC_HINTS: dict[str, str] = {
    # Cardiovascular
    "aspirin": "aspirin",
    "atorvastatin": "atorvastatin",
    "rosuvastatin": "rosuvastatin",
    "simvastatin": "simvastatin",
    "cilnidipine": "cilnidipine",
    "amlodipine": "amlodipine",
    "losartan": "losartan",
    "telmisartan": "telmisartan",
    "valsartan": "valsartan",
    "ramipril": "ramipril",
    "enalapril": "enalapril",
    "bisoprolol": "bisoprolol",
    "metoprolol": "metoprolol",
    "carvedilol": "carvedilol",
    "clopidogrel": "clopidogrel",
    "warfarin": "warfarin",
    "rivaroxaban": "rivaroxaban",
    "apixaban": "apixaban",
    "hydrochlorothiazide": "hydrochlorothiazide",
    "furosemide": "furosemide",
    "spironolactone": "spironolactone",
    # Endocrine
    "metformin": "metformin",
    "glimepiride": "glimepiride",
    "gliclazide": "gliclazide",
    "sitagliptin": "sitagliptin",
    "linagliptin": "linagliptin",
    "empagliflozin": "empagliflozin",
    "dapagliflozin": "dapagliflozin",
    "insulin": "insulin",
    "levothyroxine": "levothyroxine",
    # GI
    "esomeprazole": "esomeprazole",
    "omeprazole": "omeprazole",
    "pantoprazole": "pantoprazole",
    "rabeprazole": "rabeprazole",
    "ranitidine": "ranitidine",
    "famotidine": "famotidine",
    "domperidone": "domperidone",
    "ondansetron": "ondansetron",
    "loperamide": "loperamide",
    "pancreatic enzyme": "pancreatic enzyme",
    # Analgesics
    "paracetamol": "paracetamol",
    "acetaminophen": "paracetamol",
    "ibuprofen": "ibuprofen",
    "naproxen": "naproxen",
    "diclofenac": "diclofenac",
    "tramadol": "tramadol",
    # Antibiotics
    "amoxicillin": "amoxicillin",
    "azithromycin": "azithromycin",
    "ciprofloxacin": "ciprofloxacin",
    "levofloxacin": "levofloxacin",
    "doxycycline": "doxycycline",
    "metronidazole": "metronidazole",
    "cefixime": "cefixime",
    "ceftriaxone": "ceftriaxone",
    # Respiratory
    "salbutamol": "salbutamol",
    "albuterol": "salbutamol",
    "montelukast": "montelukast",
    "budesonide": "budesonide",
    "fluticasone": "fluticasone",
    # Neuro / Psych
    "clonazepam": "clonazepam",
    "diazepam": "diazepam",
    "alprazolam": "alprazolam",
    "sertraline": "sertraline",
    "fluoxetine": "fluoxetine",
    "escitalopram": "escitalopram",
    "amitriptyline": "amitriptyline",
    "gabapentin": "gabapentin",
    "pregabalin": "pregabalin",
    "levetiracetam": "levetiracetam",
    "carbamazepine": "carbamazepine",
    # Vitamins / Other
    "multivitamin": "multivitamin",
    "vitamin d": "vitamin d",
    "calcium": "calcium",
    "iron": "iron",
    "folic acid": "folic acid",
}

MEDICATION_GENERIC_ALIASES: dict[str, str] = {
    # Cardiovascular brand names (Bangladesh/South Asia common)
    "atova": "atorvastatin",
    "lipitor": "atorvastatin",
    "ecosprin": "aspirin",
    "disprin": "aspirin",
    "cardipin": "amlodipine",
    "amlopin": "amlodipine",
    "norvasc": "amlodipine",
    "cilidip": "cilnidipine",
    "clob": "clopidogrel",
    "clo8": "clopidogrel",
    "plavix": "clopidogrel",
    "htz": "hydrochlorothiazide",
    "lasix": "furosemide",
    "concor": "bisoprolol",
    "betaloc": "metoprolol",
    # GI
    "maxpro": "esomeprazole",
    "nexium": "esomeprazole",
    "losec": "omeprazole",
    "sergel": "esomeprazole",
    "omidon": "domperidone",
    "motigut": "domperidone",
    "ondem": "ondansetron",
    # Diabetes
    "zymet": "metformin",
    "glucophage": "metformin",
    "comet": "metformin",
    "amaryl": "glimepiride",
    "diamicron": "gliclazide",
    "januvia": "sitagliptin",
    "jardiance": "empagliflozin",
    "forxiga": "dapagliflozin",
    # Psych / Neuro
    "rivotril": "clonazepam",
    "epiclon": "clonazepam",
    "disopan": "diazepam",
    "xanax": "alprazolam",
    "neurontin": "gabapentin",
    "lyrica": "pregabalin",
    # Antibiotics
    "moxacil": "amoxicillin",
    "zimax": "azithromycin",
    "ciprocin": "ciprofloxacin",
    "flagyl": "metronidazole",
    # Analgesics
    "napa": "paracetamol",
    "ace": "paracetamol",
    "tylenol": "paracetamol",
    "brufen": "ibuprofen",
    "voltaren": "diclofenac",
    # Respiratory
    "ventolin": "salbutamol",
    "sultolin": "salbutamol",
    "montene": "montelukast",
    # Vitamins
    "bextram": "multivitamin",
    "bextram silver": "multivitamin",
    "calbo": "calcium",
}


def normalize_text(value: str) -> str:
    clean = str(value or "").strip().lower()
    for char in [",", ".", ";", ":", "(", ")", "[", "]", "{", "}", "/"]:
        clean = clean.replace(char, " ")
    clean = clean.replace("&", " and ")
    clean = clean.replace("-", " ")
    return " ".join(clean.split())


def normalize_report_test_name(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    clean = re.sub(r"\s+", " ", text).strip(" -:;,")
    match = re.match(r"^(?P<prefix>[A-Za-z]{1,8})(?:\.)?\s+(?P<rest>.+)$", clean)
    if not match:
        return clean

    prefix = normalize_text(match.group("prefix"))
    rest = re.sub(r"\s+", " ", match.group("rest")).strip(" -:;,")
    expanded = REPORT_TEST_PREFIX_EXPANSIONS.get(prefix)
    if not expanded or not rest:
        return clean
    return f"{expanded} {rest}"


def is_low_value_report_analysis(value: str | None, test_name: str | None = None) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return True

    normalized = normalize_text(text)
    if not normalized:
        return True

    normalized_test_name = normalize_text(normalize_report_test_name(test_name or ""))
    tokens = normalized.split()
    if normalized in LOW_VALUE_REPORT_ANALYSIS_TOKENS:
        return True
    if len(tokens) == 1 and (tokens[0] in LOW_VALUE_REPORT_ANALYSIS_TOKENS or len(tokens[0]) <= 4):
        return True
    if len(tokens) < 3 and not any(char.isdigit() for char in normalized):
        return True

    if normalized_test_name:
        if normalized == normalized_test_name:
            return True
        test_tokens = normalized_test_name.split()
        if len(tokens) == 1 and tokens[0] in set(test_tokens):
            return True
        if len(tokens) <= 2 and normalized in {
            f"{normalized_test_name} analysis",
            f"{normalized_test_name} result",
            f"{normalized_test_name} finding",
        }:
            return True

    return False


def specialty_domain(value: str | None) -> str | None:
    normalized = normalize_text(value or "")
    if not normalized:
        return None
    if normalized in SPECIALTY_ALIASES:
        return SPECIALTY_ALIASES[normalized]
    # Try disease-based routing
    for disease, domain in DISEASE_TO_SPECIALTY.items():
        if disease in normalized:
            return domain
    for alias, domain in SPECIALTY_ALIASES.items():
        if alias in normalized or normalized in alias:
            return domain
    return None


def specialty_from_disease(condition: str | None) -> str | None:
    """Map a disease/condition name directly to a canonical specialty label."""
    normalized = normalize_text(condition or "")
    if not normalized:
        return None
    for disease, domain in DISEASE_TO_SPECIALTY.items():
        if disease in normalized:
            return SPECIALTY_LABELS.get(domain)
    return None


def canonical_specialty(value: str | None) -> str | None:
    domain = specialty_domain(value)
    return SPECIALTY_LABELS.get(domain) if domain else None


def canonical_specialties(
    values: Iterable[str],
    *,
    primary_category: str | None = None,
    include_fallback: bool = False,
    limit: int = 6,
    drop_general_when_specific: bool = True,
) -> list[str]:
    ordered: list[str] = []
    seen_domains: set[str] = set()

    for item in values:
        domain = specialty_domain(item)
        if not domain or domain in seen_domains:
            continue
        seen_domains.add(domain)
        ordered.append(SPECIALTY_LABELS[domain])
        if len(ordered) >= limit:
            break

    fallback = CATEGORY_FALLBACK_SPECIALTIES.get(normalize_text(primary_category or ""))
    if include_fallback and fallback and fallback not in ordered and len(ordered) < limit:
        ordered.append(fallback)

    if drop_general_when_specific and len(ordered) > 1:
        ordered = [item for item in ordered if item not in GENERAL_SPECIALTIES] or ordered[:1]

    return ordered[:limit]


def merge_specialties(
    *collections: Iterable[str],
    primary_category: str | None = None,
    include_fallback: bool = False,
    limit: int = 6,
    drop_general_when_specific: bool = True,
) -> list[str]:
    merged: list[str] = []
    for collection in collections:
        merged.extend([str(item).strip() for item in collection if str(item).strip()])
    return canonical_specialties(
        merged,
        primary_category=primary_category,
        include_fallback=include_fallback,
        limit=limit,
        drop_general_when_specific=drop_general_when_specific,
    )


def specialty_matches(left: str | None, right: str | None) -> bool:
    left_domain = specialty_domain(left)
    right_domain = specialty_domain(right)
    return bool(left_domain and right_domain and left_domain == right_domain)


def medication_concepts(name: str | None, purpose: str | None = None) -> list[str]:
    concepts: list[str] = []
    normalized_name = normalize_text(name or "")
    normalized_purpose = normalize_text(purpose or "")

    if normalized_name:
        concepts.append(normalized_name)

    explicit_hints = [
        concept
        for phrase, concept in MEDICATION_GENERIC_HINTS.items()
        if phrase in normalized_name or phrase in normalized_purpose
    ]
    concepts.extend(explicit_hints)

    for alias, generic in MEDICATION_GENERIC_ALIASES.items():
        if alias in normalized_name:
            if explicit_hints and generic not in explicit_hints:
                continue
            concepts.append(generic)

    if "pancreatic enzyme" in normalized_purpose:
        concepts.append("pancreatic enzyme")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in concepts:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped