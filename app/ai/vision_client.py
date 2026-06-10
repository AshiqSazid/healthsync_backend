from __future__ import annotations

import base64
import io
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from PIL import Image

from app.ai.http_client import get_openai_http_client, with_openai_concurrency_cap
from app.ai.medical_prompts import get_prescription_extraction_system_prompt
from app.ai.openai_response_utils import candidate_models, parse_json_message_content
from app.core.config import settings
from app.utils.image_processing import preprocess_for_vision

logger = logging.getLogger(__name__)

VISION_TEMPERATURE = 0.15  # Slightly lower than 0.2 for more deterministic extraction


class VisionClient:
    async def analyze_image(self, image_path: str, prompt: str, language: str = "en") -> dict:
        if not settings.OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY is not set - vision analysis will return stub")
            return {
                "status": "vision_analysis_stub",
                "error": "No API key configured",
            }

        path = Path(image_path)
        if not path.exists():
            return {
                "status": "vision_image_not_found",
                "error": f"File not found: {image_path}",
            }

        payload_build_started = time.monotonic()
        image_items = self._build_image_items(path)
        if not image_items:
            return {
                "status": "vision_unsupported_file_type",
                "error": f"Unsupported file type: {path.suffix}",
            }
        output_format, _mime_type = self._resolve_output_format()
        detail = self._resolve_vision_detail()
        logger.info(
            "Vision payload prepared — file: %s, items: %d, format: %s, detail: %s, max_side: %d, prep_ms: %d",
            path.name,
            len(image_items),
            output_format,
            detail,
            settings.VISION_IMAGE_MAX_SIDE,
            int((time.monotonic() - payload_build_started) * 1000),
        )

        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        for model_name in candidate_models(
            settings.OPENAI_VISION_MODEL,
            settings.OPENAI_VISION_FALLBACK_MODELS,
        ):
            started_at = time.monotonic()
            try:
                payload = {
                    "model": model_name,
                    "messages": [
                        {
                            "role": "system",
                            "content": get_prescription_extraction_system_prompt(language),
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                *image_items,
                            ],
                        },
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": VISION_TEMPERATURE,
                    "max_tokens": settings.OPENAI_VISION_MAX_TOKENS,
                }

                async def send_request() -> httpx.Response:
                    return await get_openai_http_client().post(
                        f"{settings.OPENAI_API_BASE.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                response = await with_openai_concurrency_cap(send_request)
                response.raise_for_status()
                data = response.json()
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                parsed = parse_json_message_content(content)
                parsed["status"] = "vision_api_success"

                # Capture token usage for monitoring
                usage = data.get("usage")
                if usage:
                    parsed["_vision_tokens"] = {
                        "prompt": usage.get("prompt_tokens"),
                        "completion": usage.get("completion_tokens"),
                        "total": usage.get("total_tokens"),
                    }

                logger.info(
                    "Vision API success — model: %s, format: %s, detail: %s, items: %d, medications: %d, findings: %d, confidence: %s, duration_ms: %d",
                    model_name,
                    output_format,
                    detail,
                    len(image_items),
                    len(parsed.get("medications") or []),
                    len(parsed.get("report_findings") or []),
                    parsed.get("confidence_score"),
                    int((time.monotonic() - started_at) * 1000),
                )
                return parsed
            except httpx.HTTPStatusError as exc:
                if self._is_model_not_found_error(exc.response):
                    logger.warning("OpenAI vision model unavailable: %s. Trying fallback.", model_name)
                    continue
                logger.error(
                    "Vision API HTTP error for model %s: %s - %s",
                    model_name,
                    exc.response.status_code,
                    exc.response.text[:500],
                )
                return {
                    "status": "vision_api_error",
                    "error": f"HTTP {exc.response.status_code}",
                }
            except httpx.TimeoutException:
                logger.error("Vision API timeout for model %s", model_name)
                return {
                    "status": "vision_api_error",
                    "error": "Request timed out",
                }
            except httpx.RequestError as exc:
                logger.error("Vision API request error for model %s: %s", model_name, exc)
                return {
                    "status": "vision_api_error",
                    "error": str(exc),
                }
            except Exception as exc:
                logger.error("Vision API unexpected error for model %s: %s", model_name, exc)
                return {
                    "status": "vision_api_error",
                    "error": str(exc),
                }

        return {
            "status": "vision_api_error",
            "error": "No usable OpenAI vision model is available from the configured primary/fallback list.",
        }

    @staticmethod
    def _resolve_vision_detail() -> str:
        detail = str(settings.VISION_IMAGE_DETAIL or "auto").strip().lower()
        return detail if detail in {"low", "high", "auto"} else "auto"

    @staticmethod
    def _resolve_output_format() -> tuple[str, str]:
        configured = str(settings.VISION_IMAGE_OUTPUT_FORMAT or "jpeg").strip().lower()
        if configured == "png":
            return "PNG", "image/png"
        return "JPEG", "image/jpeg"

    @staticmethod
    def _resolve_jpeg_quality() -> int:
        try:
            quality = int(settings.VISION_IMAGE_JPEG_QUALITY)
        except (TypeError, ValueError):
            quality = 85
        return max(40, min(quality, 95))

    def _build_image_items(self, path: Path) -> list[dict]:
        detail = self._resolve_vision_detail()
        output_format, mime_type = self._resolve_output_format()
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            encoded_pages = self._render_pdf_pages(path, output_format=output_format)
            return [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{encoded_page}",
                        "detail": detail,
                    },
                }
                for encoded_page in encoded_pages
            ]
        encoded = self._encode_enhanced_image(path, output_format=output_format)
        if not encoded:
            return []
        return [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{encoded}",
                    "detail": detail,
                },
            }
        ]

    def _encode_enhanced_image(self, path: Path, output_format: str) -> str | None:
        """Encode image with vision-optimized preprocessing."""
        try:
            with Image.open(path) as image:
                # Use vision-specific preprocessing before sending the document to OpenAI.
                enhanced = preprocess_for_vision(image)
                buffer = io.BytesIO()
                save_kwargs: dict[str, str | int | bool] = {"format": output_format}
                if output_format == "JPEG":
                    save_kwargs.update({"quality": self._resolve_jpeg_quality(), "optimize": True})
                else:
                    save_kwargs.update({"optimize": True})
                enhanced.save(buffer, **save_kwargs)
                return base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception as exc:
            logger.warning("Image enhancement failed for %s: %s", path, exc)
            return None

    def _render_pdf_pages(self, pdf_path: Path, output_format: str = "JPEG") -> list[str]:
        """Render PDF pages at high DPI for better text recognition."""
        pdfium_pages = self._render_pdf_pages_with_pdfium(pdf_path, output_format=output_format)
        if pdfium_pages:
            return pdfium_pages

        pdftoppm_path = shutil.which("pdftoppm")
        if not pdftoppm_path:
            logger.error("pdftoppm is not installed; cannot process PDF for vision analysis")
            return []

        try:
            with tempfile.TemporaryDirectory(prefix="vision-pdf-") as tmpdir:
                output_prefix = Path(tmpdir) / "page"
                is_png = output_format.upper() == "PNG"
                render_flag = "-png" if is_png else "-jpeg"
                file_glob = "page-*.png" if is_png else "page-*.jpg"
                command = [
                    pdftoppm_path,
                    "-f", "1",
                    "-l", str(settings.VISION_PDF_MAX_PAGES),
                    "-r", str(settings.VISION_PDF_RENDER_DPI),
                    render_flag,
                    str(pdf_path),
                    str(output_prefix),
                ]
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)

                rendered = sorted(Path(tmpdir).glob(file_glob))
                encoded_pages: list[str] = []
                for page_file in rendered:
                    # Enhance each rendered page for better Vision API results
                    try:
                        with Image.open(page_file) as page_img:
                            enhanced = preprocess_for_vision(page_img)
                            buffer = io.BytesIO()
                            if output_format.upper() == "JPEG":
                                enhanced.save(
                                    buffer,
                                    format="JPEG",
                                    quality=self._resolve_jpeg_quality(),
                                    optimize=True,
                                )
                            else:
                                enhanced.save(buffer, format="PNG", optimize=True)
                            encoded_pages.append(base64.b64encode(buffer.getvalue()).decode("utf-8"))
                    except Exception:
                        # Fallback to raw bytes
                        encoded_pages.append(base64.b64encode(page_file.read_bytes()).decode("utf-8"))
                return encoded_pages
        except subprocess.TimeoutExpired:
            logger.error("pdftoppm timed out for %s", pdf_path)
            return []
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            logger.error("pdftoppm failed for %s: %s", pdf_path, stderr)
            return []
        except Exception as exc:
            logger.error("Unexpected PDF rendering error for %s: %s", pdf_path, exc)
            return []

    def _render_pdf_pages_with_pdfium(self, pdf_path: Path, output_format: str = "JPEG") -> list[str]:
        try:
            import pypdfium2 as pdfium  # type: ignore
        except Exception:
            return []

        try:
            document = pdfium.PdfDocument(str(pdf_path))
            page_count = min(len(document), settings.VISION_PDF_MAX_PAGES)
            if page_count <= 0:
                return []

            encoded_pages: list[str] = []
            scale = settings.VISION_PDF_RENDER_DPI / 72
            for index in range(page_count):
                page = document[index]
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()

                # Enhance rendered page for better Vision API results
                try:
                    enhanced = preprocess_for_vision(image)
                    buffer = io.BytesIO()
                    if output_format.upper() == "JPEG":
                        enhanced.save(
                            buffer,
                            format="JPEG",
                            quality=self._resolve_jpeg_quality(),
                            optimize=True,
                        )
                    else:
                        enhanced.save(buffer, format="PNG", optimize=True)
                    encoded_pages.append(base64.b64encode(buffer.getvalue()).decode("utf-8"))
                except Exception:
                    buffer = io.BytesIO()
                    if output_format.upper() == "JPEG":
                        image.save(buffer, format="JPEG", quality=self._resolve_jpeg_quality(), optimize=True)
                    else:
                        image.save(buffer, format="PNG")
                    encoded_pages.append(base64.b64encode(buffer.getvalue()).decode("utf-8"))

                image.close()
                page.close()
            document.close()
            return encoded_pages
        except Exception as exc:
            logger.error("PDFium render failed for %s: %s", pdf_path, exc)
            return []

    @staticmethod
    def _is_model_not_found_error(response: httpx.Response) -> bool:
        if response.status_code != 404:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return False
        return str(error.get("code") or "").strip() == "model_not_found"
