from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from openai import OpenAI

from .schemas import IngestClassification, IngestSourceContext, NoteFormattingPlan, ParaCategory
from .settings import note_settings


_PROMPT_PATH = Path(__file__).with_name("prompts") / "format_and_file_note.txt"
_INGEST_PROMPT_PATH = Path(__file__).with_name("prompts") / "polish_ingested_source.txt"
_SCANNED_PDF_PROMPT_PATH = Path(__file__).with_name("prompts") / "understand_scanned_pdf.txt"
_AREA_KEYWORDS = {"health", "school", "maintenance", "home", "family", "finance", "insurance", "permits"}
_PROJECT_KEYWORDS = {"timeline", "estimate", "contractor", "before", "plan", "deadline", "remodel", "trip", "move"}
_RESOURCE_KEYWORDS = {"article", "reference", "recipe", "manual", "guide", "notes from", "research"}
_ARCHIVE_KEYWORDS = {"completed", "done", "resolved", "archived", "closed"}
_CHURCH_KEYWORDS = {
    "church",
    "sermon",
    "scripture",
    "isaiah",
    "jesus",
    "god",
    "prayer",
    "small groups",
    "candle of hope",
    "service",
    "luke",
    "peter",
    "offering",
    "counselor",
}


class _AiPlan(BaseModel):
    title: str
    summary: str
    details: str
    action_items: list[str] = []
    tags: list[str] = []
    destination: ParaCategory = "Inbox"
    confidence: float = 0.0
    followups: list[str] = []


class _AiIngestPlan(BaseModel):
    title: str
    canonical_title: str = ""
    summary: str
    details: str
    action_items: list[str] = []
    tags: list[str] = []
    destination: ParaCategory = "Inbox"
    collection_path: str = ""
    confidence: float = 0.0
    note_kind: str = "note"
    media_class: str = "other"
    source_date: str | None = None
    followups: list[str] = []


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _load_ingest_prompt() -> str:
    return _INGEST_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _load_scanned_pdf_prompt() -> str:
    return _SCANNED_PDF_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _derive_title(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip(" .\n\t")
    if not cleaned:
        return "Captured note"
    first_clause = re.split(r"[.!?\n;]", cleaned, maxsplit=1)[0].strip()
    words = first_clause.split()
    return " ".join(words[:8]).strip() or "Captured note"


def _extract_action_items(message: str) -> list[str]:
    lowered = message.lower()
    items: list[str] = []
    for chunk in re.split(r"[.\n]+", message):
        line = chunk.strip(" -\t")
        if not line:
            continue
        if any(token in line.lower() for token in ("need to", "follow up", "check ", "confirm ", "ask ", "schedule ", "call ", "email ")):
            items.append(line)
    if " also " in lowered:
        parts = [part.strip(" .") for part in re.split(r"\balso\b", message, flags=re.IGNORECASE) if part.strip()]
        for part in parts[1:]:
            if part not in items:
                items.append(part)
    return items[:5]


def _destination_for(message: str) -> tuple[ParaCategory, float]:
    lowered = message.lower()
    if any(keyword in lowered for keyword in _CHURCH_KEYWORDS):
        return "Areas", 0.9
    if any(keyword in lowered for keyword in _ARCHIVE_KEYWORDS):
        return "Archive", 0.9
    if any(keyword in lowered for keyword in _PROJECT_KEYWORDS):
        return "Projects", 0.82
    if any(keyword in lowered for keyword in _AREA_KEYWORDS):
        return "Areas", 0.78
    if any(keyword in lowered for keyword in _RESOURCE_KEYWORDS):
        return "Resources", 0.8
    return "Inbox", 0.45


def _tagify(message: str, destination: ParaCategory) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", message.lower())
    tags: list[str] = []
    for word in words:
        if word in {"with", "need", "before", "about", "also", "from", "that", "this", "have", "will"}:
            continue
        if word not in tags:
            tags.append(word)
        if len(tags) == 4:
            break
    base = [destination.lower()]
    return [*base, *tags]


def _canonicalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip(" -\n\t") or "Captured note"


def _extract_date(text: str) -> str | None:
    patterns = [
        r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b",
        r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        groups = match.groups()
        try:
            if len(groups[0]) == 4:
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
            else:
                month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                if year < 100:
                    year += 2000
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def _collection_path_for(message: str, destination: ParaCategory) -> str:
    lowered = message.lower()
    if any(keyword in lowered for keyword in _CHURCH_KEYWORDS):
        return "Church"
    if destination == "Resources" and "program" in lowered:
        return "Programming"
    return ""


def _note_kind_for(message: str) -> str:
    lowered = message.lower()
    if any(keyword in lowered for keyword in {"sermon", "service", "church"}):
        return "sermon_note"
    if any(keyword in lowered for keyword in {"receipt", "invoice"}):
        return "receipt"
    return "note"


def _media_class_for(context: IngestSourceContext) -> str:
    text = f"{context.original_name} {context.raw_text} {context.ocr_text}".lower()
    if any(token in text for token in {"sermon", "church", "service"}):
        return "sermons"
    if any(token in text for token in {"receipt", "invoice", "total"}):
        return "receipts"
    if any(token in text for token in {"screenshot", "screen shot"}):
        return "screenshots"
    if any(token in text for token in {"whiteboard", "board"}):
        return "whiteboards"
    if context.mime_type.startswith("image/"):
        return "photos"
    return "documents"


@dataclass
class NoteAi:
    model: str = note_settings.pydantic_ai_model

    def _planner(self) -> Agent[Any, _AiPlan]:
        return Agent(self.model, output_type=_AiPlan, system_prompt=_load_prompt())

    def _ingest_planner(self) -> Agent[Any, _AiIngestPlan]:
        return Agent(self.model, output_type=_AiIngestPlan, system_prompt=_load_ingest_prompt())

    def _openai_model_name(self) -> str:
        if self.model.startswith("openai:"):
            return self.model.split(":", 1)[1]
        return self.model

    def plan(self, *, message: str, attachments: list[dict[str, Any]] | None = None, metadata: dict[str, Any] | None = None) -> NoteFormattingPlan:
        prompt = (
            f"User message:\n{message or '[empty]'}\n\n"
            f"Attachments:\n{attachments or []}\n\n"
            f"Metadata:\n{metadata or {}}\n"
        )
        try:
            result = self._planner().run_sync(prompt).output
            return NoteFormattingPlan(
                title=result.title.strip() or _derive_title(message),
                canonical_title=_canonicalize_title(result.title.strip() or _derive_title(message)),
                summary=result.summary.strip() or "Captured note.",
                details=result.details.strip() or (message.strip() or "Attachment-only capture."),
                action_items=[item.strip() for item in result.action_items if item.strip()],
                tags=[tag.strip().lower() for tag in result.tags if tag.strip()],
                destination=result.destination,
                collection_path="",
                source_date=None,
                note_kind="note",
                confidence=max(0.0, min(1.0, float(result.confidence))),
                followups=[item.strip() for item in result.followups if item.strip()],
            )
        except Exception:
            destination, confidence = _destination_for(message)
            title = _derive_title(message)
            return NoteFormattingPlan(
                title=title,
                canonical_title=_canonicalize_title(title),
                summary=(message.strip()[:180] or "Captured attachment note."),
                details=message.strip() or "Attachment-only capture.",
                action_items=_extract_action_items(message),
                tags=_tagify(message, destination),
                destination=destination,
                collection_path=_collection_path_for(message, destination),
                source_date=_extract_date(message),
                note_kind=_note_kind_for(message),
                confidence=confidence,
                followups=[] if message.strip() else ["What should this note say?"],
            )

    def plan_ingested_source(self, context: IngestSourceContext) -> IngestClassification:
        raw_body = context.ocr_text.strip() or context.raw_text.strip()
        prompt = (
            f"Original name: {context.original_name}\n"
            f"Source path: {context.source_path}\n"
            f"MIME type: {context.mime_type}\n"
            f"Modified at: {context.modified_at or ''}\n"
            f"Derived source date: {context.source_date or ''}\n"
            f"Parsed: {context.parsed}\n"
            f"Raw text:\n{raw_body or '[empty]'}\n"
        )
        try:
            result = self._ingest_planner().run_sync(prompt).output
            title = _canonicalize_title(result.title or result.canonical_title or _derive_title(raw_body or context.original_name))
            return IngestClassification(
                title=title,
                canonical_title=_canonicalize_title(result.canonical_title or title),
                summary=result.summary.strip() or "Captured and polished ingested note.",
                details=result.details.strip() or (raw_body or context.original_name),
                action_items=[item.strip() for item in result.action_items if item.strip()],
                tags=[tag.strip().lower() for tag in result.tags if tag.strip()],
                destination=result.destination,
                collection_path=(result.collection_path or _collection_path_for(prompt, result.destination)).strip("/"),
                confidence=max(0.0, min(1.0, float(result.confidence))),
                note_kind=result.note_kind or _note_kind_for(prompt),
                media_class=result.media_class or _media_class_for(context),
                source_date=result.source_date or context.source_date,
                followups=[item.strip() for item in result.followups if item.strip()],
                classification_method=context.extraction_mode,
                evidence_summary="Text extraction used for classification.",
            )
        except Exception:
            destination, confidence = _destination_for(raw_body or context.original_name)
            title_source = raw_body or context.original_name
            title = _derive_title(title_source)
            return IngestClassification(
                title=title,
                canonical_title=_canonicalize_title(title),
                summary=(raw_body.strip()[:240] or f"Ingested file {context.original_name}."),
                details=raw_body or f"Ingested source file {context.original_name}.",
                action_items=_extract_action_items(raw_body),
                tags=_tagify(raw_body or context.original_name, destination),
                destination=destination,
                collection_path=_collection_path_for(raw_body or context.original_name, destination),
                confidence=confidence,
                note_kind=_note_kind_for(raw_body or context.original_name),
                media_class=_media_class_for(context),
                source_date=context.source_date or _extract_date(title_source),
                followups=[] if raw_body.strip() else [
                    "What is the document about (topic/purpose)?",
                    "Should this be routed to a specific Project or Area, or archived?",
                    "Do you want it renamed (suggest a descriptive title)?",
                ],
                classification_method=context.extraction_mode,
                evidence_summary="Heuristic fallback used because the text planner failed.",
            )

    def plan_scanned_pdf(
        self,
        *,
        context: IngestSourceContext,
        page_images: list[dict[str, str | int]],
        page_numbers: list[int],
        extracted_text: str,
    ) -> IngestClassification:
        prompt = (
            f"Original name: {context.original_name}\n"
            f"Source path: {context.source_path}\n"
            f"MIME type: {context.mime_type}\n"
            f"Derived source date: {context.source_date or ''}\n"
            f"Page count: {context.page_count or ''}\n"
            f"OCR quality: {context.ocr_quality}\n"
            f"Analyzed pages: {page_numbers}\n"
            f"Weak OCR text (may be incomplete or wrong):\n{extracted_text.strip() or '[empty]'}\n"
        )
        try:
            client = OpenAI()
            content: list[dict[str, Any]] = [{"type": "text", "text": _load_scanned_pdf_prompt() + "\n\n" + prompt}]
            for image in page_images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{image['mime_type']};base64,{image['base64']}"},
                    }
                )
            response = client.beta.chat.completions.parse(
                model=self._openai_model_name(),
                messages=[{"role": "user", "content": content}],
                response_format=_AiIngestPlan,
            )
            message = response.choices[0].message
            result = message.parsed
            if result is None:
                raise RuntimeError("No parsed scanned PDF result returned")
            title = _canonicalize_title(result.title or result.canonical_title or _derive_title(context.original_name))
            return IngestClassification(
                title=title,
                canonical_title=_canonicalize_title(result.canonical_title or title),
                summary=result.summary.strip() or "Summary derived from scanned PDF page images.",
                details=result.details.strip() or (extracted_text.strip() or context.original_name),
                action_items=[item.strip() for item in result.action_items if item.strip()],
                tags=[tag.strip().lower() for tag in result.tags if tag.strip()],
                destination=result.destination,
                collection_path=(result.collection_path or _collection_path_for(prompt, result.destination)).strip("/"),
                confidence=max(0.0, min(1.0, float(result.confidence))),
                note_kind=result.note_kind or _note_kind_for(prompt),
                media_class=result.media_class or _media_class_for(context),
                source_date=result.source_date or context.source_date,
                followups=[item.strip() for item in result.followups if item.strip()],
                classification_method="vision",
                evidence_summary=f"Summary derived from page-image analysis of pages {', '.join(str(page) for page in page_numbers)} because extracted PDF text was insufficient.",
            )
        except Exception:
            raw_body = extracted_text.strip() or context.original_name
            destination, confidence = _destination_for(raw_body)
            title = _derive_title(raw_body)
            return IngestClassification(
                title=f"{title} (uncertain)" if "(uncertain)" not in title.lower() else title,
                canonical_title=_canonicalize_title(title),
                summary=f"Scanned PDF required page-image analysis, but the result is still uncertain for {context.original_name}.",
                details=(
                    "The PDF appears to be a scan and extracted text was weak. "
                    "A vision fallback was attempted, but the document remains too ambiguous for a confident summary."
                ),
                action_items=["Review the scanned PDF manually if exact naming or filing matters."],
                tags=["scan", "pdf", "needs-review"],
                destination=destination,
                collection_path=_collection_path_for(raw_body, destination),
                confidence=min(confidence, 0.45),
                note_kind=_note_kind_for(raw_body),
                media_class=_media_class_for(context),
                source_date=context.source_date,
                followups=[
                    "If you know the document type or organization name, add it so this can be renamed more accurately.",
                    "If the handwriting includes a name or title, provide it to improve the filing result.",
                ],
                classification_method="vision",
                evidence_summary=f"Vision fallback on pages {', '.join(str(page) for page in page_numbers)} remained inconclusive.",
            )
