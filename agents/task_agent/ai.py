from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from .ops_mode import strip_control_lines
from .schemas import IntentMode, ProjectIdea
from .settings import task_settings


# Heuristic safety-net only (used when AI classification fails).
_ACTION_PREFIXES = (
    "need to",
    "have to",
    "todo",
    "to do",
    "remember to",
    "please",
    "i should",
)
_COMPLETION_VERBS = {
    "called": "call",
    "emailed": "email",
    "texted": "text",
    "scheduled": "schedule",
    "submitted": "submit",
    "reviewed": "review",
    "finished": "finish",
    "completed": "complete",
    "bought": "buy",
    "picked": "pick",
    "paid": "pay",
}
_INSIGHT_HINTS = (
    "insight",
    "status",
    "overview",
    "summary",
    "what's pending",
    "what is pending",
    "due",
    "overdue",
    "blocked",
    "stale",
    "what does",
    "what do",
    "have i",
    "did i",
    "is it done",
    "is this done",
    "complete?",
    "completed?",
)
_DIRECTIVE_TITLE_RE = re.compile(
    r"^(do not|don't|then|return|action|ops_|parameters|note:|notes:|instruction:|instructions:|extract mode test|here are tasks)",
    flags=re.IGNORECASE,
)


@dataclass
class ExtractedTask:
    title: str
    confidence: float
    description: str = ""
    due_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    priority: int | None = None
    progress: float | None = None
    color: str | None = None
    assignees: list[str] = field(default_factory=list)
    attachments: list[dict[str, str]] = field(default_factory=list)
    relations: list[dict[str, str]] = field(default_factory=list)
    target_project: str | None = None
    parent_project: str | None = None
    repeat_interval: str | None = None
    labels: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)


class _ExtractedTaskOut(BaseModel):
    title: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    description: str = ""
    due_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    priority: int | None = None
    progress: float | None = None
    color: str | None = None
    assignees: list[str] = Field(default_factory=list)
    attachments: list[dict[str, str]] = Field(default_factory=list)
    relations: list[dict[str, str]] = Field(default_factory=list)
    target_project: str | None = None
    parent_project: str | None = None
    repeat_interval: str | None = None
    labels: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class _CompletionUpdateOut(BaseModel):
    subject: str = Field(min_length=1)
    verb: str = Field(min_length=1)
    target: str = Field(min_length=1)
    raw: str = Field(min_length=1)


class _AnalysisOut(BaseModel):
    intent_mode: IntentMode = "mutate_tasks"
    topic: str | None = None
    person: str | None = None
    query_terms: list[str] = Field(default_factory=list)
    allow_task_creation: bool = True
    purchase_items: list[str] = Field(default_factory=list)
    bulk_actions: list[dict[str, str]] = Field(default_factory=list)
    team_actions: list[dict[str, str]] = Field(default_factory=list)
    management_actions: list[dict[str, str]] = Field(default_factory=list)
    create_new_list: bool = False
    list_title: str | None = None
    project_mode: bool = False
    task_candidates: list[_ExtractedTaskOut] = Field(default_factory=list)
    completion_updates: list[_CompletionUpdateOut] = Field(default_factory=list)


@dataclass
class TaskAi:
    model: str = task_settings.pydantic_ai_model
    _cache: dict[str, _AnalysisOut] = field(default_factory=dict)

    def detect_intent_mode(self, *, message: str, metadata: dict[str, Any]) -> IntentMode:
        explicit = str(metadata.get("intent_mode") or "").strip().lower()
        if explicit in {"insights_only", "mutate_tasks", "hybrid"}:
            return explicit  # type: ignore[return-value]
        analysis = self._analyze(message=message, attachment_text="")
        return analysis.intent_mode

    def infer_query_focus(self, *, message: str) -> dict[str, str | list[str] | None]:
        analysis = self._analyze(message=message, attachment_text="")
        return {"topic": analysis.topic, "person": analysis.person, "terms": analysis.query_terms}

    def extract_task_candidates(self, *, message: str, attachment_text: str) -> list[ExtractedTask]:
        safe_message = strip_control_lines(message)
        analysis = self._analyze(message=safe_message, attachment_text=attachment_text)
        if analysis.task_candidates:
            items = [
                ExtractedTask(
                    title=item.title.strip(),
                    confidence=float(item.confidence),
                    description=str(item.description or "").strip(),
                    due_date=item.due_date,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    priority=item.priority,
                    progress=item.progress,
                    color=item.color,
                    assignees=[str(v).strip() for v in item.assignees if str(v).strip()],
                    attachments=[dict(v) for v in item.attachments if isinstance(v, dict)],
                    relations=[dict(v) for v in item.relations if isinstance(v, dict)],
                    target_project=str(item.target_project or "").strip() or None,
                    parent_project=str(item.parent_project or "").strip() or None,
                    repeat_interval=str(item.repeat_interval or "").strip() or None,
                    labels=[str(v).strip() for v in item.labels if str(v).strip()],
                    ambiguities=[str(v).strip() for v in item.ambiguities if str(v).strip()],
                )
                for item in analysis.task_candidates
                if item.title.strip() and not _DIRECTIVE_TITLE_RE.match(item.title.strip())
            ]
            return self._prune_aggregate_candidates(items)

        # Heuristic fallback.
        merged = "\n".join(part for part in [safe_message.strip(), attachment_text.strip()] if part)
        if not merged:
            return []
        normalized = merged.replace("\r", "\n")
        for prefix in _ACTION_PREFIXES:
            normalized = re.sub(rf"\b{re.escape(prefix)}\b", "", normalized, flags=re.IGNORECASE)
        raw_chunks = re.split(r"[\n.;]|\bthen\b", normalized)
        results: list[ExtractedTask] = []
        seen: set[str] = set()
        for chunk in raw_chunks:
            candidate = chunk.strip(" -:\t")
            if len(candidate) < 4:
                continue
            if _DIRECTIVE_TITLE_RE.match(candidate):
                continue
            key = _normalize_title(candidate)
            if not key or key in seen:
                continue
            seen.add(key)
            inferred_priority = None
            if re.search(r"\b(urgent|asap|highest)\b", candidate, flags=re.IGNORECASE):
                inferred_priority = 5
            elif re.search(r"\b(low|someday|whenever)\b", candidate, flags=re.IGNORECASE):
                inferred_priority = 1
            labels: list[str] = []
            if re.search(r"\b(high cost|expensive)\b", candidate, flags=re.IGNORECASE):
                labels.append("high cost")
            results.append(
                ExtractedTask(
                    title=candidate,
                    confidence=0.68,
                    priority=inferred_priority,
                    labels=labels,
                )
            )
        return self._prune_aggregate_candidates(results)

    def extract_completion_updates(self, *, message: str) -> list[dict[str, str]]:
        analysis = self._analyze(message=message, attachment_text="")
        if analysis.completion_updates:
            return [item.model_dump() for item in analysis.completion_updates]

        return self._heuristic_completion_updates(message=message)

    def should_allow_task_creation(self, *, message: str, attachment_text: str, metadata: dict[str, Any] | None = None) -> bool:
        metadata = metadata or {}
        explicit = str(metadata.get("allow_task_creation") or "").strip().lower()
        if explicit in {"true", "1", "yes"}:
            return True
        if explicit in {"false", "0", "no"}:
            return False
        lowered = message.lower()
        if any(token in lowered for token in ("create ", "add the items", "add items", "new list", "new project", "add task", "create task")):
            return True
        analysis = self._analyze(message=message, attachment_text=attachment_text)
        if analysis.allow_task_creation:
            return True
        if "?" in lowered or any(token in lowered for token in ("status", "overview", "summary", "what ", "show ", "list ")):
            return False
        return bool(message.strip())

    def extract_purchase_items(self, *, message: str, attachment_text: str) -> list[str]:
        analysis = self._analyze(message=message, attachment_text=attachment_text)
        ai_items = [item.strip().lower() for item in analysis.purchase_items if item.strip()]
        heuristic_items = self._heuristic_purchase_items(message=message, attachment_text=attachment_text)
        if ai_items or heuristic_items:
            merged: list[str] = []
            for item in [*ai_items, *heuristic_items]:
                if item and item not in merged:
                    merged.append(item)
            return merged[:30]

        text = f"{message}\n{attachment_text}".lower()
        if not any(token in text for token in ("receipt", "subtotal", "total", "thank you", "visa", "mastercard", "change")):
            # Handle normal language updates like "we got eggs and milk from the store".
            sentence = text.replace("\n", " ")
            match = re.search(r"\b(got|bought|picked up|grabbed)\s+(.+?)\s+(from|at)\s+the\s+(store|market|grocery)\b", sentence)
            if not match:
                return []
            items_part = match.group(2)
            rough_items = [part.strip(" .,\t") for part in re.split(r",| and ", items_part) if part.strip(" .,\t")]
            return [item for item in rough_items if item][:20]
        items: list[str] = []
        for line in re.split(r"[\n;]", text):
            clean = re.sub(r"\$\s*\d+[\d.,]*", "", line).strip(" -\t")
            if len(clean) < 2:
                continue
            if any(skip in clean for skip in ("total", "subtotal", "tax", "card", "cash", "change", "thank", "receipt")):
                continue
            clean = re.sub(r"\b\d+[xX]\b", "", clean).strip()
            clean = re.sub(r"\s+", " ", clean)
            if 2 <= len(clean) <= 80 and clean not in items:
                items.append(clean)
        return items[:30]

    def extract_bulk_actions(self, *, message: str, attachment_text: str = "") -> list[dict[str, str]]:
        analysis = self._analyze(message=message, attachment_text=attachment_text)
        if analysis.bulk_actions:
            filtered = [item for item in analysis.bulk_actions if item.get("action") and item.get("target")]
            if filtered:
                return filtered
        return self._heuristic_bulk_actions(message=message)

    def extract_team_actions(self, *, message: str, attachment_text: str = "") -> list[dict[str, str]]:
        analysis = self._analyze(message=message, attachment_text=attachment_text)
        if analysis.team_actions:
            filtered = [item for item in analysis.team_actions if item.get("action") and item.get("target") and item.get("team")]
            if filtered:
                return filtered
        return self._heuristic_team_actions(message=message)

    def extract_management_actions(self, *, message: str, attachment_text: str = "") -> list[dict[str, str]]:
        analysis = self._analyze(message=message, attachment_text=attachment_text)
        if analysis.management_actions:
            filtered = [item for item in analysis.management_actions if item.get("action")]
            if filtered:
                return filtered
        return self._heuristic_management_actions(message=message)

    def extract_list_directive(self, *, message: str, attachment_text: str = "") -> dict[str, Any]:
        analysis = self._analyze(message=message, attachment_text=attachment_text)
        heuristic = self._heuristic_list_directive(message=message)
        explicit_create_requested = bool(heuristic.get("create_new_list"))
        analysis_title = str(analysis.list_title or "").strip()
        generic_analysis_title = analysis_title.lower() in {"new project", "new list", "project", "list"}
        if not explicit_create_requested:
            return {"create_new_list": False, "list_title": None, "project_mode": False}
        if analysis.create_new_list and (analysis.list_title or "").strip():
            title = analysis_title
            # If heuristic also explicitly demands a new list/project, trust explicit heuristic title.
            if bool(heuristic.get("create_new_list")) and str(heuristic.get("list_title") or "").strip():
                return heuristic
            if generic_analysis_title:
                return heuristic
            return {"create_new_list": True, "list_title": title, "project_mode": bool(analysis.project_mode)}
        return heuristic

    def extract_itemized_purchase_tasks(self, *, message: str) -> list[str]:
        # Focus on first sentence for "buy/purchase/get" lists.
        sentence = re.split(r"[.!?]", message, maxsplit=1)[0].strip()
        if not sentence:
            return []
        lowered = sentence.lower()
        match = re.search(r"\b(buy|purchase|purchases|get)\s+(.+)$", lowered)
        if not match:
            return []
        items_part = match.group(2).strip()
        items_part = re.sub(r"\bfor this trip\b.*$", "", items_part, flags=re.IGNORECASE).strip(" .")
        raw_items = [part.strip(" .,\t") for part in re.split(r",| and ", items_part) if part.strip(" .,\t")]
        normalized: list[str] = []
        for item in raw_items:
            item = re.sub(r"^(a|an|the)\s+", "", item, flags=re.IGNORECASE).strip()
            if not item:
                continue
            title = f"Buy {item}"
            if title.lower() not in [entry.lower() for entry in normalized]:
                normalized.append(title)
        return normalized[:20]

    def infer_list_name(self, task_title: str) -> str:
        text = task_title.lower()
        if any(token in text for token in ("milk", "eggs", "grocery", "market", "store", "buy", "pickup order")):
            return "Shopping"
        if any(token in text for token in ("school", "kids", "pickup", "dropoff")):
            return "Family Errands"
        if any(token in text for token in ("deploy", "release", "api", "bug", "feature", "project")):
            return "Project Work"
        if any(token in text for token in ("call", "appointment", "doctor", "dentist", "insurance")):
            return "Admin"
        return "General"

    def cluster_project_candidates(self, tasks: list[str]) -> list[ProjectIdea]:
        if len(tasks) < 3:
            return []
        tokens: dict[str, int] = {}
        for task in tasks:
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", task.lower()):
                if token in {"with", "from", "that", "this", "then", "need", "pick", "task"}:
                    continue
                tokens[token] = tokens.get(token, 0) + 1
        shared = [token for token, count in tokens.items() if count >= 2]
        if not shared:
            return [
                ProjectIdea(
                    title="Task Cluster",
                    confidence=0.75,
                    rationale="Detected multiple related action items but no single dominant keyword.",
                    tasks=tasks,
                )
            ]
        shared.sort(key=lambda token: tokens[token], reverse=True)
        lead = shared[0]
        confidence = min(0.9, 0.72 + (0.06 * min(tokens[lead], 3)))
        return [
            ProjectIdea(
                title=lead.title(),
                confidence=confidence,
                rationale=f"Detected recurring task theme around '{lead}' across {tokens[lead]} items.",
                tasks=tasks,
            )
        ]

    def _analyze(self, *, message: str, attachment_text: str) -> _AnalysisOut:
        cache_key = f"{message}\n\n{attachment_text}".strip()
        if cache_key in self._cache:
            return self._cache[cache_key]

        prompt = (
            "Analyze the user input for a household task-management agent.\n"
            "Classify intent and extract structured operations context.\n"
            "Rules:\n"
            "- intent_mode must be one of: mutate_tasks, insights_only, hybrid.\n"
            "- topic should be 'general_query' when this is an informational question.\n"
            "- Extract query_terms relevant for matching tasks.\n"
            "- allow_task_creation should be false unless user explicitly asks to create/add/new/remind/todo a task.\n"
            "- Extract task_candidates with structured task details.\n"
            "- task_candidates fields: title, confidence, description, due_date, start_date, end_date, priority, progress, color, assignees, attachments, relations, target_project, parent_project, repeat_interval, labels, ambiguities.\n"
            "- Keep title short and place supporting details in description.\n"
            "- When dates exist, put them in start_date/end_date/due_date instead of title.\n"
            "- For relations default type should be 'relates_to' when user did not specify.\n"
            "- Extract purchase_items when message/attachments indicate items were acquired (store/market/grocery/receipt).\n"
            "- Extract completion_updates when text states work already happened (subject + past-tense action + target task).\n"
            "- Extract bulk_actions for explicit destructive commands only.\n"
            "- bulk_actions item format: {'action':'clear_tasks','target':'<list/project reference>'}.\n"
            "- Extract team_actions for explicit team sharing/assignment requests.\n"
            "- team_actions item format: {'action':'share_list','target':'<list/project reference>','team':'<team name>'}.\n"
            "- Extract management_actions for project/list management and task maintenance commands.\n"
            "- management_actions formats:\n"
            "  {'action':'delete_projects','target':'<project names text>'}\n"
            "  {'action':'archive_projects','target':'<project names text>'}\n"
            "  {'action':'reparent_project','target':'<child project/list>','parent':'<parent project/list>'}\n"
            "  {'action':'move_tasks','target':'<task reference text>','destination':'<list/project reference>'}\n"
            "  {'action':'highest_priority_query','target':'<list/project reference>'}\n"
            "  {'action':'update_task_details','target':'<task reference>','list':'<list reference>','details':'<detail text>'}\n"
            "  {'action':'label_task','target':'<task reference>','label':'<label title>','list':'<list reference optional>'}\n"
            "  {'action':'replace_task','target':'<old task text>','replacement':'<new task text>','list':'<list/project reference>'}\n"
            "- If user explicitly asks for a NEW list/project, set create_new_list=true and infer a concise list_title.\n"
            "- Set project_mode=true only when user explicitly asks for a project.\n"
            "- Do not require fixed keyword lists; infer from semantics.\n"
            "- Keep outputs concise and machine-usable.\n\n"
            f"Message:\n{message or '[empty]'}\n\n"
            f"Attachment text:\n{attachment_text or '[none]'}\n"
        )

        try:
            planner = Agent(
                self.model,
                output_type=_AnalysisOut,
                system_prompt="You are an intent and action extractor for task orchestration.",
            )
            result = planner.run_sync(prompt).output
            self._cache[cache_key] = result
            return result
        except Exception:
            fallback = self._fallback_analysis(message=message, attachment_text=attachment_text)
            self._cache[cache_key] = fallback
            return fallback

    def _fallback_analysis(self, *, message: str, attachment_text: str) -> _AnalysisOut:
        text = message.lower()
        asks_project_listing = bool(
            re.search(r"\b(list|show|what are)\b.*\b(project|projects|lists)\b", text)
        )
        asks_generic_listing = bool(
            re.search(
                r"\b(list|show|what are)\b.*\b(teams?|members?|archived|labels?|labeled)\b",
                text,
            )
        )
        asks_insights = any(token in text for token in _INSIGHT_HINTS) or "?" in text or asks_project_listing or asks_generic_listing
        intent: IntentMode = "insights_only" if asks_insights else "mutate_tasks"
        explicit_create = any(token in text for token in ("add ", "create ", "new task", "todo", "to do", "remind me"))
        person = None
        match = re.search(r"\bwhat does\s+([a-z][a-z'-]+)\b", text)
        if match:
            person = match.group(1).title()
        topic = "general_query" if ("?" in text or asks_project_listing or asks_generic_listing) else None
        query_terms = []
        if topic == "general_query":
            for token in re.findall(r"[a-z][a-z0-9'-]{2,}", text):
                if token in {"what", "does", "have", "has", "did", "from", "the", "and", "today", "need", "needs", "list", "completed", "complete"}:
                    continue
                if token not in query_terms:
                    query_terms.append(token)
        completion_updates = [_CompletionUpdateOut(**item) for item in self._heuristic_completion_updates(message=message) if item.get("subject") and item.get("target")]
        purchase_items = self._heuristic_purchase_items(message=message, attachment_text=attachment_text)
        bulk_actions = self._heuristic_bulk_actions(message=message)
        team_actions = self._heuristic_team_actions(message=message)
        management_actions = self._heuristic_management_actions(message=message)
        directive = self._heuristic_list_directive(message=message)
        return _AnalysisOut(
            intent_mode=intent,
            topic=topic,
            person=person,
            query_terms=query_terms[:8],
            allow_task_creation=explicit_create,
            purchase_items=purchase_items,
            bulk_actions=bulk_actions,
            team_actions=team_actions,
            management_actions=management_actions,
            create_new_list=bool(directive.get("create_new_list")),
            list_title=directive.get("list_title"),
            project_mode=bool(directive.get("project_mode")),
            completion_updates=completion_updates,
        )

    def _heuristic_completion_updates(self, *, message: str) -> list[dict[str, str]]:
        updates: list[dict[str, str]] = []
        for chunk in re.split(r"[\n.;]", message):
            text = chunk.strip(" -\t")
            if not text:
                continue
            match = re.match(r"^([A-Za-z][A-Za-z'-]{1,})\s+([A-Za-z]+)\s+(.+)$", text)
            if not match:
                continue
            subject = match.group(1).strip()
            verb = match.group(2).strip().lower()
            rest = match.group(3).strip()
            base = _COMPLETION_VERBS.get(verb)
            if base is None:
                continue
            rest = re.sub(r"^(the|a|an)\s+", "", rest, flags=re.IGNORECASE)
            target = f"{base} {rest}".strip()
            updates.append({"subject": subject, "verb": verb, "target": target, "raw": text})
        return updates

    def _heuristic_purchase_items(self, *, message: str, attachment_text: str) -> list[str]:
        text = f"{message}\n{attachment_text}".lower().replace("\n", " ")
        match = re.search(r"\b(got|bought|picked up|grabbed)\s+(.+?)\s+(from|at)\s+the\s+(store|market|grocery)\b", text)
        if not match:
            return []
        items_part = match.group(2)
        rough_items = [part.strip(" .,\t") for part in re.split(r",| and ", items_part) if part.strip(" .,\t")]
        return [item for item in rough_items if item][:20]

    def _heuristic_bulk_actions(self, *, message: str) -> list[dict[str, str]]:
        text = message.strip().lower()
        actions: list[dict[str, str]] = []
        if any(token in text for token in ("delete all tasks", "clear the", "clear ", "remove all tasks")):
            target = ""
            m = re.search(r"(?:for|from)\s+(.+)$", text)
            if m:
                target = m.group(1).strip()
            else:
                m2 = re.search(r"clear\s+(.+)$", text)
                if m2:
                    target = m2.group(1).strip()
            target = re.sub(r"\b(tasks?|list)\b", "", target).strip(" .")
            if target:
                actions.append({"action": "clear_tasks", "target": target})
        return actions

    def _heuristic_team_actions(self, *, message: str) -> list[dict[str, str]]:
        text = message.strip()
        lowered = text.lower()
        if not any(token in lowered for token in ("assign", "share")):
            return []
        match = re.search(r"(?:assign|share)\s+(?:the\s+)?(.+?)\s+to\s+(?:the\s+)?([a-z][a-z0-9' -]{1,40})", text, flags=re.IGNORECASE)
        if not match:
            return []
        target = match.group(1).strip(" .")
        team = match.group(2).strip(" .")
        team = re.sub(r"\bteam\b$", "", team, flags=re.IGNORECASE).strip()
        if not target or not team:
            return []
        return [{"action": "share_list", "target": target, "team": team}]

    def _heuristic_management_actions(self, *, message: str) -> list[dict[str, str]]:
        text = message.strip()
        lowered = text.lower()
        actions: list[dict[str, str]] = []

        if re.search(r"\bdelete\s+.+\bprojects?\b", lowered):
            target = re.sub(r"^.*?\bdelete\b", "", text, flags=re.IGNORECASE).strip(" .")
            target = re.sub(r"\bprojects?\b", "", target, flags=re.IGNORECASE).strip(" .")
            if target:
                actions.append({"action": "delete_projects", "target": target})

        if re.search(r"\barchive\s+.+", lowered):
            target = re.sub(r"^.*?\barchive\b", "", text, flags=re.IGNORECASE).strip(" .")
            target = re.sub(r"\bprojects?\b", "", target, flags=re.IGNORECASE).strip(" .")
            if target:
                actions.append({"action": "archive_projects", "target": target})

        m = re.search(r"\bset\s+parent\s+project\s+for\s+(.+?)\s+(.+)$", text, flags=re.IGNORECASE)
        if m:
            child = m.group(1).strip(" .")
            parent = m.group(2).strip(" .")
            if child and parent:
                actions.append({"action": "reparent_project", "target": child, "parent": parent})

        m = re.search(r"\b(?:move|put)\s+(.+?)\s+under\s+(.+)$", text, flags=re.IGNORECASE)
        if m:
            child = m.group(1).strip(" .")
            parent = m.group(2).strip(" .")
            if child and parent:
                actions.append({"action": "reparent_project", "target": child, "parent": parent})

        if "highest priority" in lowered:
            m = re.search(r"\bon\s+(?:my\s+)?(.+?)(?:\?|$)", text, flags=re.IGNORECASE)
            target = m.group(1).strip(" .?") if m else ""
            if target:
                target = re.sub(r"\b(remaining|item|items)\b", "", target, flags=re.IGNORECASE).strip(" .")
            if not target:
                target = "shopping"
            actions.append({"action": "highest_priority_query", "target": target})

        m = re.search(
            r"\bthe\s+(.+?)\s+i need to buy from\s+(.+?)\s+is\s+(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            actions.append(
                {
                    "action": "update_task_details",
                    "target": f"buy {m.group(1).strip()}",
                    "list": m.group(2).strip(" ."),
                    "details": m.group(3).strip(" ."),
                }
            )

        m = re.search(r"\blabel\s+(?:the\s+)?(.+?)\s+(high cost|low cost|urgent|important)\.?$", text, flags=re.IGNORECASE)
        if m:
            target = m.group(1).strip(" .")
            label = m.group(2).strip(" .")
            if target and label:
                actions.append({"action": "label_task", "target": target, "label": label})
        else:
            m = re.search(r"\blabel\s+(.+?)\s+(.+)$", text, flags=re.IGNORECASE)
            if m:
                target = m.group(1).strip(" .")
                label = m.group(2).strip(" .")
                if target and label:
                    actions.append({"action": "label_task", "target": target, "label": label})

        m = re.search(
            r"\breplace\s+(.+?)\s+on\s+the\s+(.+?)\s+(?:list|project)\s+with\s+(.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            actions.append(
                {
                    "action": "replace_task",
                    "target": m.group(1).strip(" ."),
                    "list": m.group(2).strip(" ."),
                    "replacement": m.group(3).strip(" ."),
                }
            )
        m = re.search(
            r"\bmove\s+(.+?)\s+tasks?\s+to\s+(.+?)(?:\s+(?:list|project))?\s*$",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            target = m.group(1).strip(" .")
            destination = m.group(2).strip(" .")
            destination = re.sub(r"\b(list|project)\b$", "", destination, flags=re.IGNORECASE).strip(" .")
            if target and destination:
                actions.append({"action": "move_tasks", "target": target, "destination": destination})
        return actions

    def _heuristic_list_directive(self, *, message: str) -> dict[str, Any]:
        text = message.strip()
        lowered = text.lower()
        create_new = any(token in lowered for token in ("create a new list", "new list for", "create new list", "start a new list"))
        create_project = any(token in lowered for token in ("create a new project", "new project for", "create project"))
        if not create_new and not create_project:
            return {"create_new_list": False, "list_title": None, "project_mode": False}

        place_match = re.search(r"\bgo to\s+([A-Za-z][A-Za-z0-9'& -]{1,40})", text, flags=re.IGNORECASE)
        if not place_match:
            place_match = re.search(r"\bto\s+([A-Za-z][A-Za-z0-9'& -]{1,40})", text, flags=re.IGNORECASE)
        place = None
        if place_match:
            place = place_match.group(1).strip(" .")
            place = re.sub(r"\b(and|to|for|buy|purchase|purchases)\b.*$", "", place, flags=re.IGNORECASE).strip(" .")
            place = re.sub(r"^(go|the)\s+", "", place, flags=re.IGNORECASE).strip(" .")

        if place:
            base_title = f"{place} Trip"
        elif create_project:
            proj_match = re.search(r"\bproject\s+for\s+(.+?)(?:\band\b|[.!?]|$)", text, flags=re.IGNORECASE)
            if proj_match:
                base_title = proj_match.group(1).strip(" .")
            else:
                for_match = re.search(r"\bfor\s+(.+?)(?:\band\b|[.!?]|$)", text, flags=re.IGNORECASE)
                if not for_match:
                    return {"create_new_list": False, "list_title": None, "project_mode": True}
                base_title = for_match.group(1).strip(" .")
        elif "trip" in lowered:
            base_title = "Trip List"
        else:
            return {"create_new_list": False, "list_title": None, "project_mode": False}

        if create_project:
            return {"create_new_list": True, "list_title": base_title, "project_mode": True}
        return {"create_new_list": True, "list_title": base_title, "project_mode": False}

    def _prune_aggregate_candidates(self, items: list[ExtractedTask]) -> list[ExtractedTask]:
        if len(items) < 2:
            return items
        normalized = [(_normalize_title(item.title), item) for item in items if _normalize_title(item.title)]
        if len(normalized) < 2:
            return items
        kept: list[ExtractedTask] = []
        has_buy_items = any(
            norm.startswith(("buy ", "purchase ", "get "))
            and len(norm.split()) >= 2
            for norm, _ in normalized
        )
        for norm, item in normalized:
            lower_title = item.title.lower().strip()
            if _DIRECTIVE_TITLE_RE.match(lower_title):
                continue
            if lower_title.startswith("create a new list") or lower_title.startswith("add the items"):
                continue
            if has_buy_items and lower_title.startswith("go to "):
                continue
            looks_aggregate = (
                ("," in item.title or " and " in item.title.lower())
                and any(token in item.title.lower() for token in ("go to", "buy", "purchase", "trip"))
            )
            if not looks_aggregate:
                kept.append(item)
                continue
            overlap_count = 0
            for other_norm, other_item in normalized:
                if other_item is item:
                    continue
                if not other_norm:
                    continue
                if other_norm in norm or _similarity_text(other_norm, norm) >= 0.62:
                    overlap_count += 1
            if overlap_count >= 2:
                continue
            kept.append(item)
        # de-duplicate exact titles preserving order
        seen: set[str] = set()
        deduped: list[ExtractedTask] = []
        for item in kept:
            key = _normalize_title(item.title)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped


def _normalize_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip().lower())
    return re.sub(r"[^a-z0-9 ]+", "", value)


def _similarity_text(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    from difflib import SequenceMatcher

    return SequenceMatcher(a=a, b=b).ratio()
