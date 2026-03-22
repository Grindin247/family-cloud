from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agents.common.family_events import build_event, make_privacy, publish_event as publish_family_event
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
            "sections_updated": ["account_profile", "person_profile", "preferences"],
            "role_tags": payload.person_profile.role_tags,
            "interests": payload.preferences.interests,
            "hobbies": payload.preferences.hobbies,
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
            "target_person_id": str(row.target_person_id),
            "relationship_type": row.relationship_type,
            "is_mutual": row.is_mutual,
            "status": row.status,
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
            "target_person_id": str(row.target_person_id),
            "relationship_type": row.relationship_type,
            "is_mutual": row.is_mutual,
            "status": row.status,
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
    event_payload = {
        "title": f"{source_person.get('display_name') or row.source_person_id} -> {target_person.get('display_name') or row.target_person_id}",
        "relationship_id": str(row.relationship_id),
        "source_person_id": str(row.source_person_id),
        "target_person_id": str(row.target_person_id),
        "relationship_type": row.relationship_type,
        "is_mutual": row.is_mutual,
        "status": row.status,
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
        event = build_event(
            family_id=family_id,
            domain="profile",
            event_type=event_type,
            actor={"actor_type": actor_type, "actor_id": actor_id, "person_id": actor_person_id},
            subject={"subject_type": "profile", "subject_id": subject_id, "person_id": subject_person_id},
            payload=payload,
            source={"agent_id": "profile-management-service", "runtime": "backend"},
            privacy=make_privacy(),
            tags=tags,
        )
        publish_family_event(event)
    except Exception:
        logger.exception("Failed to publish profile event family_id=%s event_type=%s subject_id=%s", family_id, event_type, subject_id)
