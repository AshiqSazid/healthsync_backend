from __future__ import annotations

from PIL import Image, ImageEnhance, ImageOps

from app.core.config import settings


def normalize_document_image(image: Image.Image, *, max_side: int | None = 2200) -> Image.Image:
    normalized = ImageOps.exif_transpose(image)

    if "A" in normalized.getbands():
        background = Image.new("RGB", normalized.size, "white")
        background.paste(normalized, mask=normalized.getchannel("A"))
        normalized = background
    elif normalized.mode != "RGB":
        normalized = normalized.convert("RGB")
    else:
        normalized = normalized.copy()

    if max_side and max(normalized.size) > max_side:
        scale = max_side / max(normalized.size)
        target_size = (
            max(1, int(normalized.width * scale)),
            max(1, int(normalized.height * scale)),
        )
        normalized = normalized.resize(target_size, Image.Resampling.LANCZOS)

    return normalized


def preprocess_for_vision(image: Image.Image) -> Image.Image:
    """Lighter preprocessing for Vision API — preserve color, fix orientation and levels."""
    normalized = normalize_document_image(image, max_side=settings.VISION_IMAGE_MAX_SIDE)

    # For vision API, keep RGB but enhance readability
    enhancer = ImageEnhance.Contrast(normalized)
    enhanced = enhancer.enhance(1.3)

    enhancer = ImageEnhance.Sharpness(enhanced)
    enhanced = enhancer.enhance(1.2)

    return enhanced
