from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agents.common.family_events import (
    build_event,
    diff_field_paths,
    make_privacy,
    publish_event as publish_family_event,
    snippet_fields,
)
from app.models.profile import ProfileRecord, RelationshipEdge
from app.schemas.profile import (
    AccountProfileSection,
    PersonProfileSection,
    PreferencesSection,
    ProfileDetailResponse,
    ProfileSummaryResponse,
    ProfileUpdate,
    RelationshipCreate,
    RelationshipResponse,
    RelationshipType,
    RelationshipUpdate,
)

logger = logging.getLogger("family_cloud.profile_service")

MUTUAL_RELATIONSHIP_TYPES = {"spouse", "co_parent"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_actor(actor_email: str | None, *, internal_admin: bool) -> tuple[str, str]:
    if actor_email:
        return "user", actor_email.strip().lower()
    if internal_admin:
        return "system", "internal-admin"
    raise ValueError("missing actor identity")


def mutual_default_for_relationship(relationship_type: RelationshipType) -> bool:
    return relationship_type in MUTUAL_RELATIONSHIP_TYPES


def _default_account_profile() -> dict[str, Any]:
    return AccountProfileSection().model_dump(mode="json")


def _default_person_profile() -> dict[str, Any]:
    return PersonProfileSection().model_dump(mode="json")


def _default_preferences() -> dict[str, Any]:
    return PreferencesSection().model_dump(mode="json")


def _profile_record(db: Session, *, family_id: int, person_id: UUID) -> ProfileRecord | None:
    return db.execute(
        select(ProfileRecord).where(
            ProfileRecord.family_id == family_id,
            ProfileRecord.person_id == person_id,
        )
    ).scalar_one_or_none()


def _profile_snapshot(record: ProfileRecord | None) -> dict[str, Any]:
    account_profile = dict(record.account_profile_json or _default_account_profile()) if record else _default_account_profile()
    person_profile = dict(record.person_profile_json or _default_person_profile()) if record else _default_person_profile()
    preferences = dict(record.preferences_json or _default_preferences()) if record else _default_preferences()
    return {
        "account_profile": account_profile,
        "person_profile": person_profile,
        "preferences": preferences,
    }


def _profile_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    account_profile = dict(snapshot.get("account_profile") or {})
    person_profile = dict(snapshot.get("person_profile") or {})
    preferences = dict(snapshot.get("preferences") or {})
    learning_preferences = dict(preferences.get("learning_preferences") or {})
    dietary_preferences = dict(preferences.get("dietary_preferences") or {})
    accessibility_needs = dict(preferences.get("accessibility_needs") or {})
    motivation_style = dict(preferences.get("motivation_style") or {})
    communication_preferences = dict(preferences.get("communication_preferences") or {})
    return {
        "account_profile": {
            "primary_login_present": bool(account_profile.get("primary_login")),
            "auth_providers": list(account_profile.get("auth_providers") or []),
            "auth_methods": list(account_profile.get("auth_methods") or []),
            "mfa_enabled": bool(account_profile.get("mfa_enabled")),
            "passkeys_enabled": bool(account_profile.get("passkeys_enabled")),
            "passkey_label_count": len(account_profile.get("passkey_labels") or []),
            "recovery_methods": list(account_profile.get("recovery_methods") or []),
            "recovery_contact_count": len(account_profile.get("recovery_contacts") or []),
            "legal_consent_keys": [item.get("consent_key") for item in account_profile.get("legal_consents") or [] if isinstance(item, dict)],
            "last_reviewed_at": account_profile.get("last_reviewed_at"),
        },
        "person_profile": {
            "birthdate_present": bool(person_profile.get("birthdate")),
            "pronouns": person_profile.get("pronouns"),
            "timezone": person_profile.get("timezone"),
            "locale": person_profile.get("locale"),
            "languages": list(person_profile.get("languages") or []),
            "role_tags": list(person_profile.get("role_tags") or []),
            "traits": list(person_profile.get("traits") or []),
        },
        "preferences": {
            "hobbies": list(preferences.get("hobbies") or []),
            "interests": list(preferences.get("interests") or []),
            "learning_preferences": {
                "modalities": list(learning_preferences.get("modalities") or []),
                "pace": learning_preferences.get("pace"),
                "environments": list(learning_preferences.get("environments") or []),
                "supports": list(learning_preferences.get("supports") or []),
            },
            "dietary_preferences": {
                "restrictions": list(dietary_preferences.get("restrictions") or []),
                "allergies": list(dietary_preferences.get("allergies") or []),
                "likes": list(dietary_preferences.get("likes") or []),
                "dislikes": list(dietary_preferences.get("dislikes") or []),
            },
            "accessibility_needs": {
                "accommodations": list(accessibility_needs.get("accommodations") or []),
                "assistive_tools": list(accessibility_needs.get("assistive_tools") or []),
                "sensory_considerations": list(accessibility_needs.get("sensory_considerations") or []),
                "mobility_considerations": list(accessibility_needs.get("mobility_considerations") or []),
            },
            "motivation_style": {
                "encouragements": list(motivation_style.get("encouragements") or []),
                "rewards": list(motivation_style.get("rewards") or []),
                "triggers_to_avoid": list(motivation_style.get("triggers_to_avoid") or []),
                "routines": list(motivation_style.get("routines") or []),
            },
            "communication_preferences": {
                "preferred_channels": list(communication_preferences.get("preferred_channels") or []),
                "response_style": communication_preferences.get("response_style"),
                "cadence": communication_preferences.get("cadence"),
                "boundaries": list(communication_preferences.get("boundaries") or []),
            },
        },
    }


def _profile_snippet_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    account_profile = dict(snapshot.get("account_profile") or {})
    person_profile = dict(snapshot.get("person_profile") or {})
    preferences = dict(snapshot.get("preferences") or {})
    payload: dict[str, Any] = {}
    payload.update(snippet_fields("security_notes", account_profile.get("security_notes")))
    payload.update(snippet_fields("demographic_notes", person_profile.get("demographic_notes")))
    payload.update(snippet_fields("learning_notes", (preferences.get("learning_preferences") or {}).get("notes")))
    payload.update(snippet_fields("dietary_notes", (preferences.get("dietary_preferences") or {}).get("notes")))
    payload.update(snippet_fields("accessibility_notes", (preferences.get("accessibility_needs") or {}).get("notes")))
    payload.update(snippet_fields("motivation_notes", (preferences.get("motivation_style") or {}).get("notes")))
    payload.update(snippet_fields("communication_notes", (preferences.get("communication_preferences") or {}).get("notes")))
    return payload


def _relationship_state(row: RelationshipEdge | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, dict):
        metadata = dict(row.get("metadata") or {})
        return {
            "source_person_id": row.get("source_person_id"),
            "target_person_id": row.get("target_person_id"),
            "relationship_type": row.get("relationship_type"),
            "status": row.get("status"),
            "is_mutual": bool(row.get("is_mutual")),
            "metadata_keys": sorted(str(key) for key in metadata),
            "notes": row.get("notes"),
        }
    metadata = dict(row.metadata_json or {})
    return {
        "source_person_id": str(row.source_person_id),
        "target_person_id": str(row.target_person_id),
        "relationship_type": row.relationship_type,
        "status": row.status,
        "is_mutual": row.is_mutual,
        "metadata_keys": sorted(str(key) for key in metadata),
        "notes": row.notes,
    }


def list_relationship_edges(db: Session, *, family_id: int, person_id: UUID | None = None) -> list[dict[str, Any]]:
    query = select(RelationshipEdge).where(RelationshipEdge.family_id == family_id)
    if person_id is not None:
        query = query.where(
            or_(
                RelationshipEdge.source_person_id == person_id,
                RelationshipEdge.target_person_id == person_id,
            )
        )
    rows = db.execute(query.order_by(RelationshipEdge.relationship_type.asc(), RelationshipEdge.created_at.asc())).scalars().all()
    return [_relationship_to_dict(row) for row in rows]


def _relationship_to_dict(row: RelationshipEdge) -> dict[str, Any]:
    return {
        "relationship_id": str(row.relationship_id),
        "family_id": row.family_id,
        "source_person_id": str(row.source_person_id),
        "target_person_id": str(row.target_person_id),
        "relationship_type": row.relationship_type,
        "status": row.status,
        "is_mutual": row.is_mutual,
        "notes": row.notes,
        "metadata": dict(row.metadata_json or {}),
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def build_profile_summary_response(*, db: Session, family_id: int, person: dict[str, Any], relationship_count: int) -> ProfileSummaryResponse:
    person_id = UUID(str(person["person_id"]))
    record = _profile_record(db, family_id=family_id, person_id=person_id)
    person_profile = PersonProfileSection.model_validate(record.person_profile_json or _default_person_profile()) if record else PersonProfileSection()
    preferences = PreferencesSection.model_validate(record.preferences_json or _default_preferences()) if record else PreferencesSection()
    return ProfileSummaryResponse(
        person_id=str(person["person_id"]),
        family_id=family_id,
        display_name=str(person.get("display_name") or person.get("canonical_name") or person["person_id"]),
        canonical_name=str(person.get("canonical_name") or person.get("display_name") or person["person_id"]),
        role_in_family=person.get("role_in_family"),
        is_admin=bool(person.get("is_admin")),
        status=str(person.get("status") or "active"),
        role_tags=person_profile.role_tags,
        hobbies=preferences.hobbies,
        interests=preferences.interests,
        relationship_count=relationship_count,
        updated_at=record.updated_at if record else None,
    )


def build_profile_detail_response(*, db: Session, family_id: int, person: dict[str, Any]) -> ProfileDetailResponse:
    person_id = UUID(str(person["person_id"]))
    record = _profile_record(db, family_id=family_id, person_id=person_id)
    relationships = [
        RelationshipResponse.model_validate(item)
        for item in list_relationship_edges(db, family_id=family_id, person_id=person_id)
    ]
    account_profile = AccountProfileSection.model_validate(record.account_profile_json or _default_account_profile()) if record else AccountProfileSection()
    person_profile = PersonProfileSection.model_validate(record.person_profile_json or _default_person_profile()) if record else PersonProfileSection()
    preferences = PreferencesSection.model_validate(record.preferences_json or _default_preferences()) if record else PreferencesSection()
    return ProfileDetailResponse(
        profile_id=str(record.profile_id) if record else None,
        family_id=family_id,
        person_id=str(person["person_id"]),
        display_name=str(person.get("display_name") or person.get("canonical_name") or person["person_id"]),
        canonical_name=str(person.get("canonical_name") or person.get("display_name") or person["person_id"]),
        role_in_family=person.get("role_in_family"),
        is_admin=bool(person.get("is_admin")),
        status=str(person.get("status") or "active"),
        accounts=person.get("accounts") if isinstance(person.get("accounts"), dict) else {},
        account_profile=account_profile,
        person_profile=person_profile,
        preferences=preferences,
        relationships=relationships,
        created_at=record.created_at if record else None,
        updated_at=record.updated_at if record else None,
    )


def create_or_update_profile_record(
    db: Session,
    *,
    family_id: int,
    person_id: UUID,
    payload: ProfileUpdate,
    actor_id: str,
    actor_type: str,
    actor_person_id: str | None,
    person: dict[str, Any],
) -> ProfileRecord:
    record = _profile_record(db, family_id=family_id, person_id=person_id)
    before_snapshot = _profile_snapshot(record)
    now = utcnow()
    if record is None:
        record = ProfileRecord(
            family_id=family_id,
            person_id=person_id,
            account_profile_json=payload.account_profile.model_dump(mode="json"),
            person_profile_json=payload.person_profile.model_dump(mode="json"),
            preferences_json=payload.preferences.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        db.add(record)
    else:
        record.account_profile_json = payload.account_profile.model_dump(mode="json")
        record.person_profile_json = payload.person_profile.model_dump(mode="json")
        record.preferences_json = payload.preferences.model_dump(mode="json")
        record.updated_at = now

    db.commit()
    db.refresh(record)
    after_snapshot = _profile_snapshot(record)
    changed_fields = diff_field_paths(before_snapshot, after_snapshot)
    role_tags = list((after_snapshot.get("person_profile") or {}).get("role_tags") or [])
    interests = list((after_snapshot.get("preferences") or {}).get("interests") or [])
    hobbies = list((after_snapshot.get("preferences") or {}).get("hobbies") or [])
    _publish_profile_event(
        family_id=family_id,
        event_type="profile.person.updated",
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=actor_person_id,
        subject_person_id=str(person_id),
        subject_id=str(person_id),
        payload={
            "title": str(person.get("display_name") or person.get("canonical_name") or person_id),
            "person_id": str(person_id),
            "sections_updated": sorted({item.split(".", 1)[0] for item in changed_fields}),
            "changed_fields": changed_fields,
            "role_tags": role_tags,
            "role_tag_count": len(role_tags),
            "interests": interests,
            "interest_count": len(interests),
            "hobbies": hobbies,
            "hobby_count": len(hobbies),
            "status": str(person.get("status") or "active"),
            "role_in_family": person.get("role_in_family"),
            "after": _profile_state(after_snapshot),
            **_profile_snippet_payload(after_snapshot),
        },
        tags=["profile", "profile-update"],
    )
    return record


def create_relationship_edge(
    db: Session,
    *,
    family_id: int,
    payload: RelationshipCreate,
    actor_id: str,
    actor_type: str,
    actor_person_id: str | None,
    source_person: dict[str, Any],
    target_person: dict[str, Any],
) -> dict[str, Any]:
    now = utcnow()
    row = RelationshipEdge(
        family_id=family_id,
        source_person_id=UUID(payload.source_person_id),
        target_person_id=UUID(payload.target_person_id),
        relationship_type=payload.relationship_type,
        status=payload.status,
        is_mutual=payload.is_mutual if payload.is_mutual is not None else mutual_default_for_relationship(payload.relationship_type),
        notes=payload.notes,
        metadata_json=payload.metadata,
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    relationship_state = _relationship_state(row)
    _publish_profile_event(
        family_id=family_id,
        event_type="profile.relationship.created",
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=actor_person_id,
        subject_person_id=str(row.target_person_id),
        subject_id=str(row.relationship_id),
        payload={
            "title": f"{source_person.get('display_name') or row.source_person_id} -> {target_person.get('display_name') or row.target_person_id}",
            "relationship_id": str(row.relationship_id),
            "source_person_id": str(row.source_person_id),
            "source_display_name": source_person.get("display_name"),
            "target_person_id": str(row.target_person_id),
            "target_display_name": target_person.get("display_name"),
            "relationship_direction": "source_to_target",
            "relationship_type": row.relationship_type,
            "is_mutual": row.is_mutual,
            "status": row.status,
            "metadata_keys": relationship_state["metadata_keys"],
            "after": {
                "relationship_type": relationship_state["relationship_type"],
                "status": relationship_state["status"],
                "is_mutual": relationship_state["is_mutual"],
                "metadata_keys": relationship_state["metadata_keys"],
            },
            **snippet_fields("relationship_notes", row.notes),
        },
        tags=["profile", "relationship"],
    )
    return _relationship_to_dict(row)


def update_relationship_edge(
    db: Session,
    *,
    row: RelationshipEdge,
    payload: RelationshipUpdate,
    actor_id: str,
    actor_type: str,
    actor_person_id: str | None,
    source_person: dict[str, Any],
    target_person: dict[str, Any],
) -> dict[str, Any]:
    before_state = _relationship_state(row)
    if payload.source_person_id is not None:
        row.source_person_id = UUID(payload.source_person_id)
    if payload.target_person_id is not None:
        row.target_person_id = UUID(payload.target_person_id)
    if payload.relationship_type is not None:
        row.relationship_type = payload.relationship_type
    if payload.status is not None:
        row.status = payload.status
    if payload.is_mutual is not None:
        row.is_mutual = payload.is_mutual
    elif payload.relationship_type is not None and payload.relationship_type in MUTUAL_RELATIONSHIP_TYPES:
        row.is_mutual = True
    if payload.notes is not None:
        row.notes = payload.notes
    if payload.metadata is not None:
        row.metadata_json = payload.metadata
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    after_state = _relationship_state(row)
    _publish_profile_event(
        family_id=row.family_id,
        event_type="profile.relationship.updated",
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=actor_person_id,
        subject_person_id=str(row.target_person_id),
        subject_id=str(row.relationship_id),
        payload={
            "title": f"{source_person.get('display_name') or row.source_person_id} -> {target_person.get('display_name') or row.target_person_id}",
            "relationship_id": str(row.relationship_id),
            "source_person_id": str(row.source_person_id),
            "source_display_name": source_person.get("display_name"),
            "target_person_id": str(row.target_person_id),
            "target_display_name": target_person.get("display_name"),
            "relationship_direction": "source_to_target",
            "relationship_type": row.relationship_type,
            "is_mutual": row.is_mutual,
            "status": row.status,
            "metadata_keys": after_state["metadata_keys"],
            "changed_fields": diff_field_paths(before_state, after_state),
            "after": {
                "relationship_type": after_state["relationship_type"],
                "status": after_state["status"],
                "is_mutual": after_state["is_mutual"],
                "metadata_keys": after_state["metadata_keys"],
            },
            **snippet_fields("relationship_notes", row.notes),
        },
        tags=["profile", "relationship"],
    )
    return _relationship_to_dict(row)


def delete_relationship_edge(
    db: Session,
    *,
    row: RelationshipEdge,
    actor_id: str,
    actor_type: str,
    actor_person_id: str | None,
    source_person: dict[str, Any],
    target_person: dict[str, Any],
) -> None:
    relationship_state = _relationship_state(row)
    event_payload = {
        "title": f"{source_person.get('display_name') or row.source_person_id} -> {target_person.get('display_name') or row.target_person_id}",
        "relationship_id": str(row.relationship_id),
        "source_person_id": str(row.source_person_id),
        "source_display_name": source_person.get("display_name"),
        "target_person_id": str(row.target_person_id),
        "target_display_name": target_person.get("display_name"),
        "relationship_direction": "source_to_target",
        "relationship_type": row.relationship_type,
        "is_mutual": row.is_mutual,
        "status": row.status,
        "metadata_keys": relationship_state["metadata_keys"],
        **snippet_fields("relationship_notes", row.notes),
    }
    db.delete(row)
    db.commit()
    _publish_profile_event(
        family_id=row.family_id,
        event_type="profile.relationship.deleted",
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=actor_person_id,
        subject_person_id=event_payload["target_person_id"],
        subject_id=event_payload["relationship_id"],
        payload=event_payload,
        tags=["profile", "relationship"],
    )


def _publish_profile_event(
    *,
    family_id: int,
    event_type: str,
    actor_id: str,
    actor_type: str,
    actor_person_id: str | None,
    subject_person_id: str | None,
    subject_id: str,
    payload: dict[str, Any],
    tags: list[str],
) -> None:
    try:
        contains_free_text = any(key.endswith("_snippet") for key in payload)
        event = build_event(
            family_id=family_id,
            domain="profile",
            event_type=event_type,
            actor={"actor_type": actor_type, "actor_id": actor_id, "person_id": actor_person_id},
            subject={"subject_type": "profile", "subject_id": subject_id, "person_id": subject_person_id},
            payload=payload,
            source={"agent_id": "ProfileService", "runtime": "backend"},
            privacy=make_privacy(
                contains_pii=True,
                contains_child_data=bool(subject_person_id),
                contains_free_text=contains_free_text,
            ),
            tags=tags,
        )
        publish_family_event(event)
    except Exception:
        logger.exception("Failed to publish profile event family_id=%s event_type=%s subject_id=%s", family_id, event_type, subject_id)
