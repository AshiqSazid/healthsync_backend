from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_system,
    ai,
    auth,
    bookings,
    dashboard,
    diagnostics,
    doctors,
    files,
    hospitals,
    payments,
    prescriptions,
    profiles,
    recommendations,
    symptom_checker,
    symptoms,
    uploads,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin_system.router, prefix="/admin/system", tags=["admin-system"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(symptoms.router, prefix="/symptoms", tags=["symptoms"])
api_router.include_router(symptom_checker.router, prefix="/symptom-checker", tags=["symptom-checker"])
api_router.include_router(prescriptions.router, prefix="/prescriptions", tags=["prescriptions"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(doctors.router, prefix="/doctors", tags=["doctors"])
api_router.include_router(hospitals.router, prefix="/hospitals", tags=["hospitals"])
api_router.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(payments.admin_router, prefix="/admin/payments", tags=["admin-payments"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["bookings"])
api_router.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
api_router.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
