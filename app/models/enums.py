import enum


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    DOCTOR = "doctor"


class SymptomCategory(str, enum.Enum):
    RESPIRATORY = "respiratory"
    CARDIAC = "cardiac"
    NEUROLOGICAL = "neurological"
    GASTROINTESTINAL = "gastrointestinal"
    DERMATOLOGICAL = "dermatological"
    MUSCULOSKELETAL = "musculoskeletal"
    GENERAL = "general"


class SessionStatus(str, enum.Enum):
    ONGOING = "ongoing"
    COMPLETED = "completed"
    REFERRED = "referred"


class AssessmentDocumentStatus(str, enum.Enum):
    DRAFT = "draft"
    COMPLETED = "completed"


class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BookingType(str, enum.Enum):
    ONLINE = "online"
    IN_PERSON = "in-person"


class PaymentMethod(str, enum.Enum):
    CARD = "card"
    UPI = "upi"
    WALLET = "wallet"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class FileScanStatus(str, enum.Enum):
    UPLOADING = "UPLOADING"
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    ERROR = "ERROR"


class UploadFileType(str, enum.Enum):
    PRESCRIPTION = "prescription"
    REPORT = "report"
