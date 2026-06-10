from pathlib import Path

import pytest
from PIL import Image

from app.utils.image_processing import normalize_document_image


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "image_path",
    [
        REPO_ROOT / "Photos-3-001" / "IMG_1378.JPG",
        REPO_ROOT / "Photos-3-001" / "IMG_1381.JPG",
    ],
)
def test_normalize_document_image_rotates_local_medical_fixtures(image_path: Path) -> None:
    with Image.open(image_path) as image:
        normalized = normalize_document_image(image)

    assert normalized.height > normalized.width
    assert max(normalized.size) <= 2200
