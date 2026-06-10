from __future__ import annotations

from app.local_doctors import (  # re-export for any legacy imports
    DOCTORS,
    SPECIALIZATION_LIST,
    get_doctor_by_id,
    get_doctors_by_specialization,
    get_doctors_with_urls,
)

__all__ = [
    "DOCTORS",
    "SPECIALIZATION_LIST",
    "get_doctors_with_urls",
    "get_doctor_by_id",
    "get_doctors_by_specialization",
]

_STATIC_PHOTO_PATH = "/static/doctors"


def _build_photo_url(backend_base_url: str, filename: str | None) -> str | None:
    if not filename:
        return None
    safe = quote(filename, safe="")
    base = (backend_base_url or "").rstrip("/")
    return f"{base}{_STATIC_PHOTO_PATH}/{safe}"


def get_doctors_with_urls(backend_base_url: str = "") -> list[dict]:
    result = []
    for doc in DOCTORS:
        d = dict(doc)
        d["photo_url"] = _build_photo_url(backend_base_url, doc.get("photo_filename"))
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
    matched = []
    for doc in get_doctors_with_urls(backend_base_url):
        for s in doc.get("specialization") or []:
            if needle in s.lower():
                matched.append(doc)
                break
    if not matched:
        all_docs = get_doctors_with_urls(backend_base_url)
        return sorted(all_docs, key=lambda d: d.get("experience_years") or 0, reverse=True)[:3]
    return matched


__all__ = [
    "DOCTORS",
    "SPECIALIZATION_LIST",
    "get_doctors_with_urls",
    "get_doctor_by_id",
    "get_doctors_by_specialization",
]
