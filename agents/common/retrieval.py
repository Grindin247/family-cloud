from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.common.mcp.client import HttpToolClient
from agents.common.settings import settings


DEFAULT_REGISTRY_PATH = Path.home() / ".openclaw" / "family-identity.json"


@dataclass(frozen=True)
class ResolvedActorContext:
    family_id: int
    actor_id: str
    person_id: str | None
    display_name: str


def _normalize(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _normalize_family_label(value: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).split())


def _iter_account_values(person: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for raw_values in (person.get("accounts") or {}).values():
        if isinstance(raw_values, list):
            values.extend(str(item) for item in raw_values if str(item).strip())
        elif raw_values:
            values.append(str(raw_values))
    return values


def _preferred_actor_id(person: dict[str, Any]) -> str | None:
    accounts = person.get("accounts") or {}
    for key in ("email", "openclaw_sender_key", "discord_sender_id"):
        values = accounts.get(key) or []
        for value in values:
            candidate = str(value).strip()
            if candidate:
                return candidate
    for candidate in _iter_account_values(person):
        if candidate:
            return candidate
    return None


def _load_registry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _matching_people(
    registry: dict[str, Any],
    *,
    candidate: str,
    family_id: int | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    needle = _normalize(candidate)
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for family in registry.get("families") or []:
        if family_id is not None and int(family.get("family_id")) != int(family_id):
            continue
        for person in family.get("persons") or []:
            haystack = {
                _normalize(person.get("canonical_name")),
                _normalize(person.get("display_name")),
            }
            haystack.update(_normalize(alias) for alias in person.get("aliases") or [])
            haystack.update(_normalize(value) for value in _iter_account_values(person))
            if needle and needle in haystack:
                matches.append((family, person))
    return matches


def _match_family_candidate(
    registry: dict[str, Any],
    *,
    candidate: str,
    family_id: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    needle = _normalize_family_label(candidate)
    if not needle:
        return None
    family_matches: list[dict[str, Any]] = []
    for family in registry.get("families") or []:
        if family_id is not None and int(family.get("family_id")) != int(family_id):
            continue
        labels = {
            _normalize_family_label(family.get("family_slug")),
            _normalize_family_label(family.get("name")),
        }
        if needle in labels:
            family_matches.append(family)
    if len(family_matches) != 1:
        return None
    family = family_matches[0]
    for person in family.get("persons") or []:
        actor_id = _preferred_actor_id(person)
        if actor_id:
            return family, person
    return None


def resolve_actor_context(
    *,
    speaker: str | None = None,
    actor_id: str | None = None,
    family_id: int | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> ResolvedActorContext:
    registry = _load_registry(registry_path)
    candidates = [candidate for candidate in (actor_id, speaker) if candidate]
    if not candidates:
        raise ValueError("provide either speaker or actor_id")

    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in candidates:
        matches = _matching_people(registry, candidate=candidate, family_id=family_id)
        if matches:
            break
        family_match = _match_family_candidate(registry, candidate=candidate, family_id=family_id)
        if family_match is not None:
            matches = [family_match]
            break

    if not matches:
        if actor_id and family_id is not None:
            return ResolvedActorContext(
                family_id=int(family_id),
                actor_id=actor_id,
                person_id=None,
                display_name=actor_id,
            )
        raise ValueError(f"could not resolve actor context for {speaker or actor_id!r}")

    if len(matches) > 1:
        family_ids = sorted({int(family.get("family_id")) for family, _ in matches})
        if len(family_ids) > 1:
            raise ValueError(f"ambiguous actor context for {speaker or actor_id!r}; matches families {family_ids}")
    family, person = matches[0]
    resolved_actor_id = actor_id or _preferred_actor_id(person)
    if not resolved_actor_id:
        raise ValueError(f"resolved person {person.get('display_name')!r} has no usable actor account")
    return ResolvedActorContext(
        family_id=int(family.get("family_id")),
        actor_id=resolved_actor_id,
        person_id=str(person.get("person_id")) if person.get("person_id") else None,
        display_name=str(person.get("display_name") or person.get("canonical_name") or resolved_actor_id),
    )


def _search_path(kind: str) -> str:
    if kind == "documents":
        return "/search"
    if kind == "files":
        return "/files/search"
    if kind == "notes":
        return "/notes/search"
    raise ValueError(f"unsupported search kind: {kind}")


def search_index(
    kind: str,
    *,
    query_text: str,
    speaker: str | None = None,
    actor_id: str | None = None,
    family_id: int | None = None,
    top_k: int = 5,
    include_content: bool = True,
    owner_person_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    document_kinds: list[str] | None = None,
    preferred_item_types: list[str] | None = None,
    content_types: list[str] | None = None,
    query_tags: list[str] | None = None,
    base_url: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    resolved = resolve_actor_context(
        speaker=speaker,
        actor_id=actor_id,
        family_id=family_id,
        registry_path=registry_path,
    )
    payload: dict[str, Any] = {
        "family_id": resolved.family_id,
        "actor": resolved.actor_id,
        "query": query_text,
        "top_k": top_k,
        "include_content": include_content,
    }
    if owner_person_id is not None:
        payload["owner_person_id"] = owner_person_id
    if kind == "documents":
        payload["date_from"] = date_from
        payload["date_to"] = date_to
        payload["document_kinds"] = document_kinds or []
        payload["preferred_item_types"] = preferred_item_types or []
        payload["content_types"] = content_types or []
        payload["query_tags"] = query_tags or []
    elif kind == "files":
        payload["preferred_item_types"] = preferred_item_types or []
        payload["content_types"] = content_types or []
    elif kind == "notes":
        payload["query_tags"] = query_tags or []

    client = HttpToolClient(base_url=base_url or settings.file_api_base_url)
    result = client.request(
        "POST",
        _search_path(kind),
        json_body=payload,
        headers={"X-Dev-User": resolved.actor_id},
    ).result or {}
    return {
        "kind": kind,
        "resolved_context": {
            "family_id": resolved.family_id,
            "actor_id": resolved.actor_id,
            "person_id": resolved.person_id,
            "display_name": resolved.display_name,
        },
        "query": query_text,
        "response": result,
    }


def summarize_search_result(result: dict[str, Any]) -> dict[str, Any]:
    response = result.get("response") or {}
    items = response.get("items") or []
    summarized_items: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        summary: dict[str, Any] = {"rank": index}
        for key in (
            "document_id",
            "document_kind",
            "item_type",
            "path",
            "name",
            "title",
            "summary",
            "excerpt_text",
            "content_type",
            "source_date",
            "owner_person_id",
            "nextcloud_url",
            "raw_note_url",
            "match_reasons",
            "source_refs",
        ):
            value = item.get(key)
            if value not in (None, "", [], {}):
                summary[key] = value
        summarized_items.append(summary)
    return {
        "ok": True,
        "kind": result.get("kind"),
        "query": result.get("query"),
        "resolved_context": result.get("resolved_context"),
        "total": len(items),
        "items": summarized_items,
    }
