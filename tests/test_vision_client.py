import base64
import io
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from app.ai.vision_client import VisionClient


def test_build_image_items_converts_supported_non_png_images_to_jpeg(tmp_path: Path) -> None:
    image_path = tmp_path / "scan.bmp"
    Image.new("RGB", (120, 80), color="white").save(image_path)

    items = VisionClient()._build_image_items(image_path)

    assert len(items) == 1
    assert items[0]["type"] == "image_url"
    assert items[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert items[0]["image_url"]["detail"] == "auto"


def test_build_image_items_respects_configured_max_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (2400, 1200), color="white").save(image_path)
    monkeypatch.setattr("app.ai.vision_client.settings.VISION_IMAGE_MAX_SIDE", 600)

    items = VisionClient()._build_image_items(image_path)
    payload = items[0]["image_url"]["url"].split(",", 1)[1]
    resized = Image.open(io.BytesIO(base64.b64decode(payload)))

    assert max(resized.size) <= 600


def test_build_image_items_respects_configured_detail_and_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (500, 300), color="white").save(image_path)
    monkeypatch.setattr("app.ai.vision_client.settings.VISION_IMAGE_DETAIL", "high")
    monkeypatch.setattr("app.ai.vision_client.settings.VISION_IMAGE_OUTPUT_FORMAT", "png")

    items = VisionClient()._build_image_items(image_path)

    assert items[0]["image_url"]["detail"] == "high"
    assert items[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_render_pdf_pages_with_pdfium_respects_configured_page_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("app.ai.vision_client.settings.VISION_PDF_MAX_PAGES", 2)
    monkeypatch.setattr("app.ai.vision_client.settings.VISION_PDF_RENDER_DPI", 180)

    class _FakeBitmap:
        def to_pil(self):
            return Image.new("RGB", (100, 120), color="white")

    class _FakePage:
        def render(self, scale: float):
            assert scale == 180 / 72
            return _FakeBitmap()

        def close(self) -> None:
            return None

    class _FakeDocument:
        def __init__(self, _: str) -> None:
            self._pages = [_FakePage(), _FakePage(), _FakePage()]

        def __len__(self) -> int:
            return len(self._pages)

        def __getitem__(self, index: int) -> _FakePage:
            return self._pages[index]

        def close(self) -> None:
            return None

    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=_FakeDocument))

    pages = VisionClient()._render_pdf_pages_with_pdfium(pdf_path)

    assert len(pages) == 2


@pytest.mark.asyncio
async def test_analyze_image_timeout_returns_error_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (120, 80), color="white").save(image_path)
    monkeypatch.setattr("app.ai.vision_client.settings.OPENAI_API_KEY", "test-key")

    class _TimeoutClient:
        async def post(self, *args, **kwargs):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.ai.vision_client.get_openai_http_client", lambda: _TimeoutClient())

    result = await VisionClient().analyze_image(str(image_path), "extract this")

    assert result["status"] == "vision_api_error"
    assert result["error"] == "Request timed out"


@pytest.mark.asyncio
async def test_analyze_image_does_not_pass_per_request_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (120, 80), color="white").save(image_path)
    monkeypatch.setattr("app.ai.vision_client.settings.OPENAI_API_KEY", "test-key")

    captured_kwargs: dict = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "{\"confidence_score\": 0.9, \"medications\": [], \"report_findings\": []}"
                        }
                    }
                ]
            }

    class _Client:
        async def post(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
            return _Response()

    monkeypatch.setattr("app.ai.vision_client.get_openai_http_client", lambda: _Client())

    result = await VisionClient().analyze_image(str(image_path), "extract this")

    assert result["status"] == "vision_api_success"
    assert "timeout" not in captured_kwargs
