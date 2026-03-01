from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import email.utils
import logging
import posixpath
import re
from threading import Lock
from typing import Any
from urllib.parse import quote

from agents.common.observability.tracing import new_correlation_id

from .ai import NoteAi
from .document_extractors import can_extract_extension, extract_document_bytes
from .pdf_understanding import assess_pdf_text_quality, pdf_page_count, render_pdf_pages, select_escalated_pages, select_initial_pages
from .schemas import CreatedItem, IngestClassification, IngestSourceContext, NoteAgentResponse, NoteAttachment, NoteIngestRequest, NoteIngestResponse, NoteInvokeRequest
from .settings import note_settings
from .tools import NextcloudNotesTool, note_tools


logger = logging.getLogger(__name__)


def _safe_attachment_name(name: str, index: int) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "-" for ch in name).strip("-")
    return cleaned or f"attachment-{index}"


def _filename_stem(name: str) -> str:
    stem = posixpath.splitext(name)[0]
    return re.sub(r"[_\-]+", " ", stem).strip() or name


def _slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-") or "note"


def _capture_filename(value: str) -> str:
    slug = _slugify(value)[:80]
    return slug or "captured-note"


def _render_note(title: str, summary: str, details: str, action_items: list[str], tags: list[str], filed: str, attachment_lines: list[str]) -> str:
    actions = "\n".join(f"- {item}" for item in action_items) if action_items else "- None yet"
    attachments = "\n".join(f"- {line}" for line in attachment_lines) if attachment_lines else "- None"
    tags_line = ", ".join(tags) if tags else "inbox"
    return (
        f"# {title}\n\n"
        f"## Summary\n{summary}\n\n"
        f"## Details\n{details}\n\n"
        f"## Action Items\n{actions}\n\n"
        f"## Attachments\n{attachments}\n\n"
        f"Tags: {tags_line}\n"
        f"Filed: {filed}\n"
    )


def _render_polished_ingest_note(
    *,
    classification: IngestClassification,
    filed_path: str,
    archived_raw_path: str,
    original_path: str,
    original_name: str,
    mime_type: str,
    source_date: str | None,
    extraction_mode: str,
    ocr_quality: str,
    analyzed_pages: list[int],
) -> str:
    key_points = []
    if classification.details.strip():
        for chunk in re.split(r"[\n\r]+", classification.details.strip()):
            line = chunk.strip(" -\t")
            if line:
                key_points.append(line)
            if len(key_points) == 6:
                break
    key_points_block = "\n".join(f"- {item}" for item in key_points) if key_points else "- None extracted"
    action_items_block = "\n".join(f"- {item}" for item in classification.action_items) if classification.action_items else "- None"
    tags_line = ", ".join(classification.tags) if classification.tags else "inbox"
    raw_file_url = _nextcloud_files_app_url(archived_raw_path)
    source_lines = [
        f"- Raw file: [{original_name}]({raw_file_url})",
        f"- Archived path: `{archived_raw_path}`",
        f"- Ingested from: `{original_path}`",
        f"- Source type: `{mime_type or 'application/octet-stream'}`",
        f"- Source date: `{source_date or 'unknown'}`",
        f"- Extraction mode: `{extraction_mode or 'unknown'}`",
        f"- OCR quality: `{ocr_quality or 'unknown'}`",
    ]
    if analyzed_pages:
        source_lines.append(f"- Analyzed pages: `{', '.join(str(page) for page in analyzed_pages)}`")
    if classification.classification_method:
        source_lines.append(f"- Classification method: `{classification.classification_method}`")
    if classification.evidence_summary:
        source_lines.append(f"- Evidence: {classification.evidence_summary}")
    return (
        f"# {classification.title}\n\n"
        f"## Summary\n{classification.summary}\n\n"
        f"## Key Points\n{key_points_block}\n\n"
        f"## Action Items\n{action_items_block}\n\n"
        f"## Source\n"
        f"{chr(10).join(source_lines)}\n\n"
        f"## Tags\n{tags_line}\n\n"
        f"Filed: {filed_path}\n"
    )


def _nextcloud_files_app_url(path: str) -> str:
    normalized = posixpath.normpath("/" + path.strip().lstrip("/"))
    directory = posixpath.dirname(normalized)
    rel_path = posixpath.basename(normalized)
    base_url = note_settings.nextcloud_base_url.rstrip("/")
    encoded_dir = quote(directory, safe="/")
    encoded_rel_path = quote(rel_path, safe="")
    return f"{base_url}/apps/files/?dir={encoded_dir}&relPath={encoded_rel_path}"


@dataclass
class NoteAgent:
    name: str = "note"
    ai: NoteAi | None = None
    tools: NextcloudNotesTool | None = None
    ingest_lock: Lock = field(default_factory=Lock)

    def run(self, req: NoteInvokeRequest) -> NoteAgentResponse:
        request_id = new_correlation_id()
        actor = req.actor.strip()
        session_id = (req.session_id or "default").strip() or "default"
        message = req.message.strip()
        logger.info("note_agent_invoke request_id=%s session_id=%s family_id=%s actor=%s", request_id, session_id, req.family_id, actor)

        if not message and not req.attachments:
            return self._response(
                status="needs_clarification",
                summary="Need note text or at least one attachment.",
                created_items=[],
                actions_taken=[],
                followups=["What should be captured in this note?"],
                debug={"request_id": request_id} if note_settings.debug else None,
            )

        debug: dict[str, Any] | None = {"request_id": request_id, "session_id": session_id} if note_settings.debug else None
        response = self._capture_note(
            actor=actor,
            family_id=req.family_id,
            session_id=session_id,
            message=message,
            attachments=req.attachments,
            metadata=req.metadata,
            debug=debug,
        )
        return response

    def ingest(self, req: NoteIngestRequest) -> NoteIngestResponse:
        request_id = new_correlation_id()
        actor = req.actor.strip()
        session_id = (req.session_id or "ingest").strip() or "ingest"
        logger.info("note_agent_ingest request_id=%s session_id=%s family_id=%s actor=%s", request_id, session_id, req.family_id, actor)
        tools = self.tools or note_tools()
        debug: dict[str, Any] | None = {"request_id": request_id, "session_id": session_id} if note_settings.debug else None
        created_items: list[CreatedItem] = []
        actions_taken: list[str] = []
        processed = 0
        skipped = 0
        cursor: str | None = None

        with self.ingest_lock:
            inbox_files = sorted(
                tools.list_ready_inbox_files(limit=req.max_items, tag_name=note_settings.note_agent_ready_tag_name),
                key=lambda item: str(item.get("last_modified") or ""),
            )
            for item in inbox_files:
                path = str(item.get("path") or "")
                cursor = str(item.get("last_modified") or cursor or "")
                if not path:
                    skipped += 1
                    continue
                if "/Attachments/" in path:
                    skipped += 1
                    continue
                ingest_result = self._ingest_inbox_file(
                    actor=actor,
                    family_id=req.family_id,
                    session_id=session_id,
                    metadata=req.metadata,
                    item=item,
                    tools=tools,
                )
                if ingest_result is None:
                    skipped += 1
                    continue
                processed += 1
                created_items.extend(ingest_result["created_items"])
                actions_taken.extend(ingest_result["actions_taken"])

        summary = f"Processed {processed} ready inbox file(s)." if processed else "No ready inbox files found."
        return NoteIngestResponse(
            status="ok",
            summary=summary,
            created_items=created_items,
            actions_taken=actions_taken,
            processed_count=processed,
            skipped_count=skipped,
            cursor=cursor,
            debug=debug if note_settings.debug else None,
        )

    def auto_ingest_ready_from_config(self) -> NoteIngestResponse | None:
        if not note_settings.note_agent_auto_ingest_ready_enabled:
            return None
        if not note_settings.note_agent_auto_ingest_actor.strip() or note_settings.note_agent_auto_ingest_family_id <= 0:
            logger.warning("note_agent_auto_ingest_skipped missing actor or family_id config")
            return None
        return self.ingest(
            NoteIngestRequest(
                actor=note_settings.note_agent_auto_ingest_actor.strip(),
                family_id=note_settings.note_agent_auto_ingest_family_id,
                session_id="auto-ingest",
                max_items=25,
            )
        )

    def _capture_note(
        self,
        *,
        actor: str,
        family_id: int,
        session_id: str | None,
        message: str,
        attachments: list[NoteAttachment],
        metadata: dict[str, Any],
        debug: dict[str, Any] | None,
    ) -> NoteAgentResponse:
        tools = self.tools or note_tools()
        created_items: list[CreatedItem] = []
        actions_taken: list[str] = []
        attachment_lines: list[str] = []

        for index, attachment in enumerate(attachments, start=1):
            result = self._handle_attachment(attachment, session_id=session_id, tools=tools, index=index)
            if result["created_item"] is not None:
                created_items.append(result["created_item"])
            attachment_lines.append(result["reference"])
            actions_taken.extend(result["actions"])

        source_path, source_text = self._record_invoke_source(
            actor=actor,
            session_id=session_id,
            message=message,
            attachment_lines=attachment_lines,
            tools=tools,
        )
        created_items.append(CreatedItem(path=source_path, kind="note"))
        actions_taken.append("Recorded raw invoke source in Nextcloud")

        source_context = self._build_source_context(
            path=source_path,
            filename=posixpath.basename(source_path),
            content_type="text/markdown",
            item={},
            source_read={"content": source_text, "content_type": "text/markdown"},
        )
        classification = self._analyze_ingested_source(source_context)
        if note_settings.debug and debug is not None:
            debug["plan"] = classification.model_dump()
            debug["effective_destination"] = classification.destination

        archive_path = self._archive_raw_source(
            source_context=source_context,
            classification=classification,
            tools=tools,
        )
        created_items.append(CreatedItem(path=archive_path, kind="note"))
        actions_taken.append("Archived raw invoke source file")

        polished_note_path = self._write_polished_ingest_note(
            source_context=source_context,
            classification=classification,
            archive_path=archive_path,
            tools=tools,
        )
        created_items.append(CreatedItem(path=polished_note_path, kind="note"))
        actions_taken.append("Created polished markdown note in Nextcloud")

        destination = classification.destination
        summary = f"Filed note '{classification.title}' to {destination}."
        if attachments:
            summary = f"{summary} Processed {len(attachments)} attachment(s)."
        return self._response(
            status="ok",
            summary=summary,
            created_items=created_items,
            actions_taken=actions_taken,
            followups=classification.followups or None,
            debug=debug,
        )

    def _record_invoke_source(
        self,
        *,
        actor: str,
        session_id: str | None,
        message: str,
        attachment_lines: list[str],
        tools: NextcloudNotesTool,
    ) -> tuple[str, str]:
        inbox_dir = f"{note_settings.note_agent_root}/Inbox"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        session_part = _capture_filename(session_id or "invoke")
        title_part = _capture_filename(message[:120])
        source_path = f"{inbox_dir}/{timestamp}-{session_part}-{title_part}-raw.md"
        body_lines = [
            "# Captured Invoke Source",
            "",
            f"- Actor: {actor}",
            f"- Session: {session_id or 'default'}",
            f"- Captured at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}",
            "",
            "## Original Message",
            message.strip() or "[empty]",
        ]
        if attachment_lines:
            body_lines.extend(["", "## Attachments"])
            body_lines.extend(f"- {line}" for line in attachment_lines)
        source_text = "\n".join(body_lines).strip() + "\n"
        if note_settings.note_agent_dry_run:
            return source_path, source_text
        tools.ensure_directory(inbox_dir)
        unique_path = tools.ensure_unique_path(source_path)
        tools.write_markdown_note(unique_path, source_text)
        return unique_path, source_text

    def _ingest_inbox_file(
        self,
        *,
        actor: str,
        family_id: int,
        session_id: str,
        metadata: dict[str, Any],
        item: dict[str, Any],
        tools: NextcloudNotesTool,
    ) -> dict[str, Any] | None:
        path = str(item.get("path") or "")
        filename = posixpath.basename(path)
        content_type = str(item.get("content_type") or "")
        source_read = self._read_ingest_source(path=path, filename=filename, content_type=content_type, tools=tools)
        source_context = self._build_source_context(
            path=path,
            filename=filename,
            content_type=content_type,
            item=item,
            source_read=source_read,
        )
        classification = self._analyze_ingested_source(source_context)
        actions_taken = [f"Ingested ready inbox file {path}"]
        created_items: list[CreatedItem] = []

        archive_path = self._archive_raw_source(
            source_context=source_context,
            classification=classification,
            tools=tools,
        )
        created_items.append(
            CreatedItem(
                path=archive_path,
                kind="note" if self._is_textual(content_type, filename) else "media",
            )
        )
        actions_taken.append("Archived raw source file")

        polished_note_path = self._write_polished_ingest_note(
            source_context=source_context,
            classification=classification,
            archive_path=archive_path,
            tools=tools,
        )
        created_items.append(CreatedItem(path=polished_note_path, kind="note"))
        actions_taken.append("Created polished markdown note in Nextcloud")
        if not self._is_textual(content_type, filename):
            created_items.append(CreatedItem(path=f"external://{filename}", kind="media", url=archive_path))
            actions_taken.append(f"Referenced archived raw media {filename}")
        if classification.followups:
            actions_taken.extend(f"Follow-up needed: {item}" for item in classification.followups)
        return {"created_items": created_items, "actions_taken": actions_taken}

    def _read_ingest_source(self, *, path: str, filename: str, content_type: str, tools: NextcloudNotesTool) -> dict[str, Any]:
        try:
            payload = tools.read(path)
            extension = posixpath.splitext(filename)[1].lower()
            if payload.get("encoding") == "base64" and can_extract_extension(extension):
                raw_bytes = base64.b64decode(str(payload.get("content") or ""))
                extracted = extract_document_bytes(raw_bytes, extension)
                payload["content"] = extracted.text
                payload["parsed"] = True
                payload["parser"] = extracted.parser
                payload["encoding"] = None
                payload["bytes_base64"] = base64.b64encode(raw_bytes).decode("ascii")
            if content_type.lower() == "application/pdf" and "bytes_base64" not in payload:
                raw_payload = tools.read_raw(path)
                if raw_payload.get("encoding") == "base64":
                    payload["bytes_base64"] = str(raw_payload.get("content") or "")
            return payload
        except Exception:
            if self._is_textual(content_type, filename):
                raise
            return {}

    def _is_textual(self, content_type: str, filename: str) -> bool:
        lowered = content_type.lower()
        extension = posixpath.splitext(filename)[1].lower()
        return lowered.startswith("text/") or "markdown" in lowered or filename.lower().endswith((".md", ".txt", ".json", ".csv")) or can_extract_extension(extension)

    def _build_media_ingest_message(
        self,
        *,
        filename: str,
        path: str,
        moved_attachment: str,
        content_type: str,
        source_read: dict[str, Any],
    ) -> str:
        title_hint = _filename_stem(filename)
        extracted_text = str(source_read.get("content") or source_read.get("text") or "").strip()
        parsed = bool(source_read.get("parsed"))
        summary_lines = [
            f"Ingest file: {filename}",
            f"Title hint: {title_hint}",
            f"Source path: {path}",
            f"Filed media path: {moved_attachment}",
        ]
        if content_type:
            summary_lines.append(f"Content type: {content_type}")
        if parsed and source_read.get("parsing_metadata"):
            summary_lines.append(f"Parsing metadata: {source_read.get('parsing_metadata')}")

        if extracted_text and source_read.get("encoding") != "base64":
            excerpt = re.sub(r"\s+", " ", extracted_text).strip()[:4000]
            summary_lines.append("")
            summary_lines.append("Extracted document text:")
            summary_lines.append(excerpt)
        else:
            summary_lines.append("")
            summary_lines.append("Available source metadata only; use filename and file type for naming and filing.")
        return "\n".join(summary_lines)

    def _build_source_context(
        self,
        *,
        path: str,
        filename: str,
        content_type: str,
        item: dict[str, Any],
        source_read: dict[str, Any],
    ) -> IngestSourceContext:
        raw_text = str(source_read.get("content") or source_read.get("text") or "").strip()
        encoding = source_read.get("encoding")
        bytes_base64 = str(source_read.get("bytes_base64") or "") or (str(source_read.get("content") or "") if encoding == "base64" else "")
        parsed = bool(source_read.get("parsed")) or bool(raw_text and not self._is_textual(content_type, filename))
        source_date, origin = self._derive_source_date(
            text=raw_text,
            filename=filename,
            modified_at=str(item.get("last_modified") or "") or None,
        )
        page_count = None
        ocr_quality = "unknown"
        extraction_mode = "text"
        analyzed_pages: list[int] = []
        if content_type.lower() == "application/pdf":
            extraction_mode = "ocr" if parsed else "text"
            if bytes_base64:
                try:
                    page_count = pdf_page_count(base64.b64decode(bytes_base64))
                except Exception:
                    page_count = None
            quality = assess_pdf_text_quality(raw_text, page_count=page_count or 1)
            ocr_quality = quality.quality
        elif parsed:
            extraction_mode = "ocr"
        return IngestSourceContext(
            source_path=path,
            original_name=filename,
            mime_type=content_type,
            modified_at=str(item.get("last_modified") or "") or None,
            raw_text=raw_text,
            ocr_text=raw_text if parsed else "",
            parsed=parsed,
            encoding=str(encoding) if encoding else None,
            bytes_base64=bytes_base64 or None,
            source_date=source_date,
            source_date_origin=origin,
            page_count=page_count,
            extraction_mode=extraction_mode,
            ocr_quality=ocr_quality,
            analyzed_pages=analyzed_pages,
        )

    def _derive_source_date(self, *, text: str, filename: str, modified_at: str | None) -> tuple[str | None, str]:
        candidates = [text, filename]
        for candidate, origin in ((text, "content"), (filename, "filename")):
            match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b", candidate)
            if match:
                month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                if year < 100:
                    year += 2000
                try:
                    return datetime(year, month, day).strftime("%Y-%m-%d"), origin
                except Exception:
                    pass
        if modified_at:
            try:
                dt = email.utils.parsedate_to_datetime(modified_at)
                return dt.strftime("%Y-%m-%d"), "metadata"
            except Exception:
                pass
        return None, "unknown"

    def _analyze_ingested_source(self, source_context: IngestSourceContext) -> IngestClassification:
        planner = self.ai or NoteAi()
        if (
            note_settings.note_agent_scanned_pdf_vision_enabled
            and source_context.mime_type.lower() == "application/pdf"
            and source_context.ocr_quality in {"weak", "image_only"}
            and source_context.bytes_base64
            and hasattr(planner, "plan_scanned_pdf")
        ):
            try:
                raw_pdf = base64.b64decode(source_context.bytes_base64)
                initial_pages = select_initial_pages(source_context.page_count or pdf_page_count(raw_pdf))
                rendered = render_pdf_pages(raw_pdf, initial_pages)
                logger.info(
                    "note_agent_pdf_vision_fallback source=%s ocr_quality=%s pages=%s",
                    source_context.source_path,
                    source_context.ocr_quality,
                    initial_pages,
                )
                source_context.analyzed_pages = initial_pages
                source_context.extraction_mode = "hybrid"
                classification = planner.plan_scanned_pdf(
                    context=source_context,
                    page_images=rendered,
                    page_numbers=initial_pages,
                    extracted_text=source_context.ocr_text or source_context.raw_text,
                )  # type: ignore[assignment]
                if (
                    classification.confidence < note_settings.note_agent_scanned_pdf_vision_confidence_threshold
                    and (source_context.page_count or 0) > len(initial_pages)
                ):
                    escalated_pages = select_escalated_pages(source_context.page_count or 0, initial_pages=initial_pages)
                    if escalated_pages != initial_pages:
                        logger.info(
                            "note_agent_pdf_vision_escalated source=%s pages=%s",
                            source_context.source_path,
                            escalated_pages,
                        )
                        rendered = render_pdf_pages(raw_pdf, escalated_pages)
                        source_context.analyzed_pages = escalated_pages
                        classification = planner.plan_scanned_pdf(
                            context=source_context,
                            page_images=rendered,
                            page_numbers=escalated_pages,
                            extracted_text=source_context.ocr_text or source_context.raw_text,
                        )  # type: ignore[assignment]
                classification.classification_method = "hybrid" if source_context.ocr_text.strip() else "vision"
                if not classification.evidence_summary:
                    classification.evidence_summary = (
                        f"OCR quality was {source_context.ocr_quality}; analyzed pages {', '.join(str(page) for page in source_context.analyzed_pages)}."
                    )
                return classification
            except Exception as exc:
                logger.warning("note_agent_pdf_vision_failed source=%s error=%s", source_context.source_path, exc)
        if hasattr(planner, "plan_ingested_source"):
            return planner.plan_ingested_source(source_context)  # type: ignore[return-value]
        fallback = planner.plan(message=source_context.raw_text or source_context.original_name, attachments=[], metadata={"source_path": source_context.source_path})
        return IngestClassification(
            title=fallback.title,
            canonical_title=fallback.canonical_title or fallback.title,
            summary=fallback.summary,
            details=fallback.details,
            action_items=fallback.action_items,
            tags=fallback.tags,
            destination=fallback.destination,
            collection_path=fallback.collection_path,
            confidence=fallback.confidence,
            note_kind=fallback.note_kind,
            media_class="documents",
            source_date=fallback.source_date or source_context.source_date,
            followups=fallback.followups,
            classification_method=source_context.extraction_mode,
            evidence_summary="Heuristic fallback used because no ingest planner was available.",
        )

    def _archive_raw_source(
        self,
        *,
        source_context: IngestSourceContext,
        classification: IngestClassification,
        tools: NextcloudNotesTool,
    ) -> str:
        archive_path = self._derive_archive_path(source_context=source_context, classification=classification)
        if note_settings.note_agent_dry_run:
            return archive_path
        tools.ensure_directory(posixpath.dirname(archive_path))
        unique_path = tools.ensure_unique_path(archive_path)
        tools.move(source_context.source_path, unique_path)
        return unique_path

    def _derive_archive_path(self, *, source_context: IngestSourceContext, classification: IngestClassification) -> str:
        date_part = classification.source_date or source_context.source_date or "undated"
        year_part = (date_part[:4] if len(date_part) >= 4 else "unknown")
        base_dir = f"{note_settings.note_agent_root}/Archive/Raw"
        if classification.collection_path:
            base_dir = f"{base_dir}/{classification.collection_path.strip('/')}"
        base_dir = f"{base_dir}/{year_part}"
        ext = posixpath.splitext(source_context.original_name)[1].lower() or ".bin"
        slug = _slugify(classification.canonical_title or classification.title or _filename_stem(source_context.original_name))
        return f"{base_dir}/{date_part}-{slug}-raw{ext}"

    def _derive_polished_note_path(self, *, classification: IngestClassification, tools: NextcloudNotesTool) -> str:
        date_part = classification.source_date or "undated"
        slug = _slugify(classification.canonical_title or classification.title)
        base_dir = f"{note_settings.note_agent_root}/{classification.destination}"
        if classification.collection_path:
            base_dir = f"{base_dir}/{classification.collection_path.strip('/')}"
        tools.ensure_directory(base_dir)
        return tools.ensure_unique_path(f"{base_dir}/{date_part}-{slug}.md")

    def _write_polished_ingest_note(
        self,
        *,
        source_context: IngestSourceContext,
        classification: IngestClassification,
        archive_path: str,
        tools: NextcloudNotesTool,
    ) -> str:
        note_path = self._derive_polished_note_path(classification=classification, tools=tools)
        note_body = _render_polished_ingest_note(
            classification=classification,
            filed_path=note_path,
            archived_raw_path=archive_path,
            original_path=source_context.source_path,
            original_name=source_context.original_name,
            mime_type=source_context.mime_type,
            source_date=classification.source_date or source_context.source_date,
            extraction_mode=source_context.extraction_mode,
            ocr_quality=source_context.ocr_quality,
            analyzed_pages=source_context.analyzed_pages,
        )
        if note_settings.note_agent_dry_run:
            return note_path
        if tools.path_exists(note_path):
            existing = tools.read(note_path)
            existing_text = str(existing.get("content") or existing.get("text") or "").strip()
            if existing_text:
                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
                note_body = existing_text + f"\n\n## Agent Addendum ({timestamp})\n\n" + note_body
        tools.write_markdown_note(note_path, note_body)
        return note_path

    def _destination_hint_from_content(self, content: str) -> str | None:
        filed_match = re.search(r"^filed:\s*(.+)$", content, flags=re.IGNORECASE | re.MULTILINE)
        if not filed_match:
            return None
        filed = filed_match.group(1).strip().rstrip("/")
        if filed.endswith("/Projects"):
            return "Projects"
        if filed.endswith("/Areas"):
            return "Areas"
        if filed.endswith("/Resources"):
            return "Resources"
        if filed.endswith("/Archive"):
            return "Archive"
        if filed.endswith("/Inbox"):
            return "Inbox"
        return None

    def _handle_attachment(self, attachment: NoteAttachment, *, session_id: str, tools: NextcloudNotesTool, index: int) -> dict[str, Any]:
        filename = _safe_attachment_name(attachment.name, index)
        target_dir = f"{note_settings.note_agent_root}/Inbox/Attachments/{session_id}"
        if attachment.bytes_base64:
            if note_settings.note_agent_dry_run:
                return {
                    "created_item": CreatedItem(path=f"{target_dir}/{filename}", kind="media"),
                    "reference": f"{filename} (DRY_RUN)",
                    "actions": [f"DRY_RUN enabled; skipped upload for {filename}"],
                }
            raw_bytes = base64.b64decode(attachment.bytes_base64)
            upload = tools.upload_media(raw_bytes, filename, destination=target_dir, content_type=attachment.type)
            return {
                "created_item": CreatedItem(path=upload["path"], kind="media"),
                "reference": upload["path"],
                "actions": [f"Uploaded attachment {filename}"],
            }
        if attachment.url:
            return {
                "created_item": CreatedItem(path=f"external://{filename}", kind="media", url=attachment.url),
                "reference": f"{filename}: {attachment.url}",
                "actions": [f"Referenced remote attachment {filename}"],
            }
        return {
            "created_item": None,
            "reference": f"{filename}: attachment had no bytes or URL",
            "actions": [f"Skipped empty attachment payload for {filename}"],
        }

    def _response(
        self,
        *,
        status: str,
        summary: str,
        created_items: list[CreatedItem],
        actions_taken: list[str],
        followups: list[str] | None,
        debug: dict[str, Any] | None,
    ) -> NoteAgentResponse:
        return NoteAgentResponse(
            status=status,  # type: ignore[arg-type]
            summary=summary,
            created_items=created_items,
            actions_taken=actions_taken,
            followups=followups,
            debug=debug if note_settings.debug else None,
        )
