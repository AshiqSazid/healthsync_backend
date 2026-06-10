from __future__ import annotations

# ─────────────────────────────────────────────────────────────
# EDIT THIS FILE to update any doctor info, fees, or schedules.
# No other files need to change.
# ─────────────────────────────────────────────────────────────

DOCTORS = [
    {
        "id": 1,
        "name": "Dr. Shahidul Islam",
        "display_name": "Dr. Shahidul Islam",
        "specialization": ["Dermatologist"],
        "experience_years": 10,
        "license_number": "E89012",
        "education": [
            "MBBS (Rajshahi Medical College)",
            "DDV (BIRDEM)",
            "MD Dermatology (BSMMU)",
        ],
        "consultation_fee": 800,     # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Labaid Hospital",
                "location": "Labaid Hospital",
                "address": "House 06, Road 04, Dhanmondi, Dhaka-1205",
                "hospitalAddress": "House 06, Road 04, Dhanmondi, Dhaka-1205",
                "hospitalName": "Labaid Hospital",
                "days": "Sat, Mon, Wed",
                "time": "02:00 PM - 06:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": "dr.shahidul islam.jpg",
        "has_photo": True,
    },
    {
        "id": 2,
        "name": "Dr. SK Farid Ahmed",
        "display_name": "Dr. SK Farid Ahmed",
        "specialization": ["Oncoplastic Breast Surgeon"],
        "experience_years": 20,
        "license_number": None,
        "education": [
            "MBBS (Mymensingh Medical College, 1992)",
            "Surgical Fellowship FRCS (Royal College of Physicians and Surgeons of Glasgow, 2000)",
        ],
        "consultation_fee": 1500,    # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Breast Unit BRB Hospital Ltd.",
                "location": "Breast Unit BRB Hospital Ltd.",
                "address": "Panthapath, Dhanmondi, Dhaka",
                "hospitalAddress": "Panthapath, Dhanmondi, Dhaka",
                "hospitalName": "Breast Unit BRB Hospital Ltd.",
                "days": "Sat, Sun, Mon, Tue, Wed, Thu, Fri",
                "time": "10:00 AM - 02:00 PM",
                "contactNumber": "",
            },
            {
                "hospital": "Labaid Cancer Hospital",
                "location": "Labaid Cancer Hospital",
                "address": "26 Green Rd, Dhanmondi, Dhaka 1205",
                "hospitalAddress": "26 Green Rd, Dhanmondi, Dhaka 1205",
                "hospitalName": "Labaid Cancer Hospital",
                "days": "Sat, Sun, Mon, Tue, Wed, Thu, Fri",
                "time": "07:00 PM - 10:00 PM",
                "contactNumber": "",
            },
        ],
        "photo_filename": "Dr. SK Farid Ahmed.jpg",
        "has_photo": True,
    },
    {
        "id": 3,
        "name": "Prof. Syed Md. Akram Hussain",
        "display_name": "Prof. Syed Md. Akram Hussain",
        "specialization": ["Clinical Oncology & Radiotherapy"],
        "experience_years": 32,
        "license_number": None,
        "education": [
            "MBBS - Bachelor of Medicine and Bachelor of Surgery",
            "FCPS - Fellowship of College of Physicians & Surgeons",
            "FRCP (Glasgow) - Fellowship of Royal College of Physicians",
            "FRCP (Edinburgh) - Fellowship of Royal College of Physicians",
            "FACP (USA) - Fellow of the American College of Physicians",
            "MRCR (UK) - Member, Royal College of Radiologists",
        ],
        "consultation_fee": 2000,    # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Square Hospitals Ltd",
                "location": "Square Hospitals Ltd",
                "address": "18/F, Bir Uttam Qazi Nuruzzaman Sarak, Panthapath, 12, Dhanmondi, Dhaka-1205, Bangladesh",
                "hospitalAddress": "18/F, Bir Uttam Qazi Nuruzzaman Sarak, Panthapath, 12, Dhanmondi, Dhaka-1205, Bangladesh",
                "hospitalName": "Square Hospitals Ltd",
                "days": "Sat, Sun, Mon, Tue, Wed, Thu",
                "time": "06:00 PM - 08:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": "Prof. Syed Md. Akram Hussain.jpg",
        "has_photo": True,
    },
    {
        "id": 4,
        "name": "Prof. Dr. Qazi Mushtaq Hussain",
        "display_name": "Prof. Dr. Qazi Mushtaq Hussain",
        "specialization": ["Clinical Oncology"],
        "experience_years": 25,
        "license_number": None,
        "education": [
            "MBBS - Bachelor of Medicine and Bachelor of Surgery",
            "M.Phil (Oncology)",
            "Training (India)",
        ],
        "consultation_fee": 1500,    # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Labaid Specialized Hospital",
                "location": "Labaid Specialized Hospital",
                "address": "House: 1 and 6, Road No 4, Mirpur Road, Dhanmondi 32, Dhaka-1205",
                "hospitalAddress": "House: 1 and 6, Road No 4, Mirpur Road, Dhanmondi 32, Dhaka-1205",
                "hospitalName": "Labaid Specialized Hospital",
                "days": "Sat, Mon, Wed",
                "time": "05:00 PM - 07:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": "Prof. Dr. Qazi Mushtaq Hussain.jpg",
        "has_photo": True,
    },
    {
        "id": 5,
        "name": "DR. A. M. Shafique",
        "display_name": "DR. A. M. Shafique",
        "specialization": ["Cardiologist", "Cardiac Surgeon"],
        "experience_years": 35,
        "license_number": None,
        "education": [
            "MBBS - Dhaka Medical College Hospital (2001)",
        ],
        "consultation_fee": 2000,    # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "United Hospital Limited",
                "location": "United Hospital Limited",
                "address": "Plot: 15, Road: 71, Gulshan 2, Dhaka-1212",
                "hospitalAddress": "Plot: 15, Road: 71, Gulshan 2, Dhaka-1212",
                "hospitalName": "United Hospital Limited",
                "days": "Sat, Wed",
                "time": "08:00 AM - 06:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": "DR. A. M. SHAFIQUE.jpg",
        "has_photo": True,
    },
    {
        "id": 6,
        "name": "Prof. Dr. Zafor Md. Masud",
        "display_name": "Prof. Dr. Zafor Md. Masud",
        "specialization": ["Oncologist", "Cancer Specialist"],
        "experience_years": 19,
        "license_number": None,
        "education": [
            "MBBS (1999)",
            "M.Phil - BSMMU (2004)",
            "FCPS - Fellow of College of Physicians and Surgeons (1999)",
        ],
        "consultation_fee": 1500,    # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Ibn Sina Specialized Hospital",
                "location": "Ibn Sina Specialized Hospital",
                "address": "House #68, Road #15/A, Dhanmondi, Dhaka-1209",
                "hospitalAddress": "House #68, Road #15/A, Dhanmondi, Dhaka-1209",
                "hospitalName": "Ibn Sina Specialized Hospital",
                "days": "Sat, Mon, Wed, Thu",
                "time": "01:30 PM - 03:30 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": "Prof. Dr. Zafor Md. Masud.jpg",
        "has_photo": True,
    },
    {
        "id": 7,
        "name": "Assoc. Prof. Dr. Mohammad Masudur Rahman",
        "display_name": "Assoc. Prof. Dr. Mohammad Masudur Rahman",
        "specialization": ["Neuromedicine"],
        "experience_years": 28,
        "license_number": None,
        "education": [
            "MBBS - Bachelor of Medicine and Bachelor of Surgery",
            "BCS (Health) - Bangladesh Civil Service",
            "MD Neurology - Doctor of Medicine",
        ],
        "consultation_fee": 1200,    # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Ibn Sina Medical College Hospital",
                "location": "Ibn Sina Medical College Hospital",
                "address": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalAddress": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalName": "Ibn Sina Medical College Hospital",
                "days": "Sat, Sun, Mon",
                "time": "06:00 PM - 09:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": "Assoc. Prof. Dr. Mohammad Masudur Rahman.jpg",
        "has_photo": True,
    },
    {
        "id": 8,
        "name": "Dr. Rashed Imam Zahid",
        "display_name": "Dr. Rashed Imam Zahid",
        "specialization": ["Neuromedicine Specialist"],
        "experience_years": 20,
        "license_number": None,
        "education": [
            "MBBS - Bachelor of Medicine and Bachelor of Surgery",
            "BCS (Health) - Bangladesh Civil Service",
            "MD - Masters of Surgery",
        ],
        "consultation_fee": 800,     # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Ibn Sina Medical College Hospital",
                "location": "Ibn Sina Medical College Hospital",
                "address": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalAddress": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalName": "Ibn Sina Medical College Hospital",
                "days": "Sun, Tue",
                "time": "04:00 PM - 06:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": None,
        "has_photo": False,
    },
    {
        "id": 9,
        "name": "Dr. A.F.M Al Masum Khan",
        "display_name": "Dr. A.F.M Al Masum Khan",
        "specialization": ["Neuromedicine Specialist"],
        "experience_years": 20,
        "license_number": None,
        "education": [
            "MBBS - Bachelor of Medicine and Bachelor of Surgery",
            "BCS (Health) - Bangladesh Civil Service",
            "MD - Masters of Surgery",
        ],
        "consultation_fee": 800,     # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Ibn Sina Medical College Hospital",
                "location": "Ibn Sina Medical College Hospital",
                "address": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalAddress": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalName": "Ibn Sina Medical College Hospital",
                "days": "Sat, Sun, Tue, Wed, Thu",
                "time": "06:00 PM - 08:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": None,
        "has_photo": False,
    },
    {
        "id": 10,
        "name": "Dr. Md. Khairul Kabir",
        "display_name": "Dr. Md. Khairul Kabir",
        "specialization": ["Neuromedicine"],
        "experience_years": 20,
        "license_number": None,
        "education": [
            "MBBS - Bachelor of Medicine and Bachelor of Surgery",
            "BCS (Health) - Bangladesh Civil Service",
            "MD - Masters of Surgery",
        ],
        "consultation_fee": 800,     # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Ibn Sina Medical College Hospital",
                "location": "Ibn Sina Medical College Hospital",
                "address": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalAddress": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalName": "Ibn Sina Medical College Hospital",
                "days": "Sun, Tue, Thu",
                "time": "03:00 PM - 05:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": None,
        "has_photo": False,
    },
    {
        "id": 11,
        "name": "Dr. Md. Zakirul Islam Jewel",
        "display_name": "Dr. Md. Zakirul Islam Jewel",
        "specialization": ["Medicine Specialist", "Neuromedicine"],
        "experience_years": 13,
        "license_number": None,
        "education": [
            "MBBS - Bachelor of Medicine and Bachelor of Surgery",
            "BCS (Health) - Bangladesh Civil Service",
            "FCPS (Medicine) - Fellow of College of Physicians and Surgeons",
        ],
        "consultation_fee": 700,     # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Ibn Sina Medical College Hospital",
                "location": "Ibn Sina Medical College Hospital",
                "address": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalAddress": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalName": "Ibn Sina Medical College Hospital",
                "days": "Sat, Mon, Tue, Wed",
                "time": "04:30 PM - 09:00 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": None,
        "has_photo": False,
    },
    {
        "id": 12,
        "name": "Dr. Humayun Kabir Himu",
        "display_name": "Dr. Humayun Kabir Himu",
        "specialization": ["Neurology"],
        "experience_years": 5,
        "license_number": None,
        "education": [],
        "consultation_fee": 700,     # ← Change this number to update the fee
        "consultation_fee_currency": "BDT",
        "consultation_fee_note": "Per visit",
        "available_slots": [
            {
                "hospital": "Ibn Sina Medical College Hospital",
                "location": "Ibn Sina Medical College Hospital",
                "address": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalAddress": "Kallyanpur 1/1, Mirpur Road, Kallyanpur, Dhaka-1216",
                "hospitalName": "Ibn Sina Medical College Hospital",
                "days": "Sat, Sun, Mon, Wed, Thu",
                "time": "07:00 PM - 09:30 PM",
                "contactNumber": "",
            }
        ],
        "photo_filename": None,
        "has_photo": False,
    },
]

# All known specializations — injected into the AI system prompt so the
# model knows which values to return in "recommended_specialization".
SPECIALIZATION_LIST = [
    "Dermatologist",
    "Oncoplastic Breast Surgeon",
    "Clinical Oncology & Radiotherapy",
    "Clinical Oncology",
    "Oncologist",
    "Cancer Specialist",
    "Cardiologist",
    "Cardiac Surgeon",
    "Neuromedicine",
    "Neuromedicine Specialist",
    "Neurology",
    "Medicine Specialist",
]

# ─────────────────────────────────────────────────────────────
# Helper functions — used by endpoints and the AI service.
# ─────────────────────────────────────────────────────────────

_STATIC_PHOTO_PATH = "/api/v1/doctors/local/{doctor_id}/photo"


def _build_photo_url(backend_base_url: str, doctor_id: int, filename: str | None) -> str | None:
    if not filename or not doctor_id:
        return None
    base = (backend_base_url or "").rstrip("/")
    return f"{base}{_STATIC_PHOTO_PATH.format(doctor_id=doctor_id)}"


def get_doctors_with_urls(backend_base_url: str = "") -> list[dict]:
    result = []
    for doc in DOCTORS:
        d = dict(doc)
        d["photo_url"] = _build_photo_url(backend_base_url, int(doc.get("id") or 0), doc.get("photo_filename"))
        d["image_url"] = d["photo_url"]
        d["imageUrl"] = d["photo_url"]
        result.append(d)
    return result


def get_doctor_by_id(doctor_id: int, backend_base_url: str = "") -> dict | None:
    for doc in get_doctors_with_urls(backend_base_url):
        if doc["id"] == doctor_id:
            return doc
    return None


def get_doctors_by_specialization(spec: str, backend_base_url: str = "") -> list[dict]:
    needle = spec.strip().lower()
    matched = [
        doc for doc in get_doctors_with_urls(backend_base_url)
        if any(needle in s.lower() for s in (doc.get("specialization") or []))
    ]
    if not matched:
        all_docs = get_doctors_with_urls(backend_base_url)
        return sorted(all_docs, key=lambda d: d.get("experience_years") or 0, reverse=True)[:3]
    return matched
