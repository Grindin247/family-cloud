from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import base64
import re

import fitz

from .settings import note_settings


_PLACEHOLDER_PATTERNS = (
    r"\[image[^\]]*\]",
    r"<image[^>]*>",
    r"image placeholder",
    r"page images? (?:are|were) referenced",
    r"\bpdf-\d+\b",
    r"\bimage[:\s]+pdf-\d+\b",
    r"\bpage\s+\d+\s*[:\-]?\s*pdf-\d+\b",
    r"scanned pdf",
    r"contents not extracted",
    r"content not extracted",
    r"ocr[ -]?not available",
)


@dataclass(frozen=True)
class PdfQualityAssessment:
    quality: str
    page_count: int
    placeholder_hits: int
    text_length: int


def assess_pdf_text_quality(text: str, *, page_count: int) -> PdfQualityAssessment:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    placeholder_hits = sum(len(re.findall(pattern, cleaned, flags=re.IGNORECASE)) for pattern in _PLACEHOLDER_PATTERNS)
    page_ref_hits = len(re.findall(r"\bpdf-\d+\b", cleaned, flags=re.IGNORECASE))
    meaningful_words = re.findall(r"\b[a-zA-Z]{3,}\b", cleaned)
    meaningful_words = [
        word for word in meaningful_words
        if word.lower() not in {"pdf", "page", "pages", "image", "images", "scanned", "content", "contents", "extracted"}
    ]
    meaningful_word_count = len(meaningful_words)
    placeholder_heavy = page_ref_hits >= max(3, page_count // 2) or placeholder_hits >= 2
    if not cleaned:
        return PdfQualityAssessment(quality="image_only", page_count=page_count, placeholder_hits=placeholder_hits, text_length=0)
    if placeholder_heavy and meaningful_word_count <= max(12, page_count) and len(cleaned) < max(note_settings.note_agent_scanned_pdf_vision_min_text_chars * 3, page_count * 220):
        return PdfQualityAssessment(
            quality="image_only",
            page_count=page_count,
            placeholder_hits=placeholder_hits + page_ref_hits,
            text_length=len(cleaned),
        )
    if placeholder_hits >= 2 and len(cleaned) < max(note_settings.note_agent_scanned_pdf_vision_min_text_chars, page_count * 80):
        return PdfQualityAssessment(
            quality="image_only",
            page_count=page_count,
            placeholder_hits=placeholder_hits,
            text_length=len(cleaned),
        )
    if placeholder_heavy or meaningful_word_count < max(20, page_count * 2) or len(cleaned) < max(note_settings.note_agent_scanned_pdf_vision_min_text_chars, page_count * 40):
        return PdfQualityAssessment(
            quality="weak",
            page_count=page_count,
            placeholder_hits=placeholder_hits + page_ref_hits,
            text_length=len(cleaned),
        )
    return PdfQualityAssessment(quality="usable", page_count=page_count, placeholder_hits=placeholder_hits + page_ref_hits, text_length=len(cleaned))


def pdf_page_count(raw_bytes: bytes) -> int:
    document = fitz.open(stream=raw_bytes, filetype="pdf")
    try:
        return document.page_count
    finally:
        document.close()


def select_initial_pages(page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    if page_count <= note_settings.note_agent_scanned_pdf_vision_max_initial_pages:
        return list(range(1, page_count + 1))
    candidates = [1, 2, max(1, (page_count + 1) // 2), page_count]
    return sorted(dict.fromkeys(page for page in candidates if 1 <= page <= page_count))


def select_escalated_pages(page_count: int, *, initial_pages: list[int]) -> list[int]:
    if page_count <= 0:
        return []
    if page_count <= note_settings.note_agent_scanned_pdf_vision_max_total_pages:
        return list(range(1, page_count + 1))
    expanded = list(range(1, min(page_count, 5) + 1))
    expanded.extend(initial_pages)
    expanded.append(page_count)
    return sorted(dict.fromkeys(page for page in expanded if 1 <= page <= page_count))[: note_settings.note_agent_scanned_pdf_vision_max_total_pages]


def render_pdf_pages(raw_bytes: bytes, pages: list[int]) -> list[dict[str, str | int]]:
    if not pages:
        return []
    document = fitz.open(stream=raw_bytes, filetype="pdf")
    try:
        scale = max(1.0, note_settings.note_agent_scanned_pdf_render_dpi / 72.0)
        matrix = fitz.Matrix(scale, scale)
        rendered: list[dict[str, str | int]] = []
        for page_number in pages:
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pixmap.tobytes("png")
            rendered.append(
                {
                    "page": page_number,
                    "mime_type": "image/png",
                    "base64": base64.b64encode(png_bytes).decode("ascii"),
                }
            )
        return rendered
    finally:
        document.close()
