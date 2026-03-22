from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Family, FamilyMember, RoleEnum
from app.models.identity import FamilyFeature, Person, PersonAccount, PersonAlias


DEFAULT_FEATURES = {
    "decision": True,
    "tasks": True,
    "files": True,
    "events": True,
    "profile": False,
    "health": False,
    "education": False,
    "finance": False,
}

ACCOUNT_TYPE_BY_CHANNEL = {
    "discord": "discord_sender_id",
    "signal": "signal_sender_id",
    "openclaw": "openclaw_sender_key",
}

ALIAS_SEED_BY_EMAIL: dict[str, list[str]] = {
    "mrjamescallender@gmail.com": ["dadda", "dad", "james", "james jr", "biscuithead", "luvwrk777"],
    "rachel@example.com": ["momma", "mom", "rachel", "ray", "snunkz"],
    "rachel.c.griffin@gmail.com": ["momma", "mom", "rachel", "ray", "snunkz"],
    "valerie@example.com": ["valerie", "val", "vivadiva", "valpal", "vivadiva14"],
    "felicity@example.com": ["felicity", "lissie", "lis anne", "sissie", "buh", "buh annie", "lissieanne15"],
    "james3@example.com": ["james", "james iii", "mr. man", "man baby", "mrman1517"],
    "ezekiel@example.com": ["ezekiel", "zekie", "zekie zeke", "zekiezeke19"],
}

ACCOUNT_SEED_BY_EMAIL: dict[str, dict[str, list[str]]] = {
    "mrjamescallender@gmail.com": {
        "openclaw_sender_key": ["jcallender"],
        "discord_sender_id": ["525687139737010177"],
    },
    "rachel.c.griffin@gmail.com": {
        "openclaw_sender_key": ["r.callender"],
        "discord_sender_id": ["831683621114216469"],
    },
}


@dataclass(frozen=True)
class ResolvedPersonContext:
    family_id: int
    family_slug: str
    person_id: str
    actor_person_id: str
    target_person_id: str
    is_family_admin: bool
    directory_account_id: str | None
    primary_email: str | None
    source_channel: str | None
    source_sender_id: str | None
    resolution_source: str
    member_id: int | None = None


def normalize_alias(value: str) -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def parse_person_id(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def slugify_family_name(value: str) -> str:
    normalized = normalize_alias(value).replace(" ", "-")
    return normalized or "family"


def canonical_name_for_member(member: FamilyMember) -> str:
    if member.display_name.strip():
        return member.display_name.strip()
    return member.email.strip().lower()


def _ensure_family_slug(db: Session, family: Family) -> str:
    slug = (getattr(family, "slug", None) or "").strip()
    if slug:
        return slug
    slug = slugify_family_name(family.name)
    existing = db.execute(select(Family).where(Family.id != family.id, Family.slug == slug)).scalar_one_or_none()  # type: ignore[attr-defined]
    if existing is not None:
        slug = f"{slug}-{family.id}"
    family.slug = slug  # type: ignore[attr-defined]
    db.flush()
    return slug


def ensure_person_for_member(db: Session, member: FamilyMember) -> Person:
    person = db.execute(select(Person).where(Person.legacy_member_id == member.id)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if person is None:
        person = Person(
            family_id=member.family_id,
            legacy_member_id=member.id,
            canonical_name=canonical_name_for_member(member),
            display_name=member.display_name,
            role_in_family=member.role.value,
            is_admin=member.role == RoleEnum.admin,
            metadata_jsonb={"source": "family_members"},
            updated_at=now,
        )
        db.add(person)
        db.flush()
    else:
        person.family_id = member.family_id
        person.canonical_name = canonical_name_for_member(member)
        person.display_name = member.display_name
        person.role_in_family = member.role.value
        person.is_admin = member.role == RoleEnum.admin
        person.status = "active"
        person.updated_at = now

    upsert_person_account(
        db,
        family_id=member.family_id,
        person=person,
        account_type="email",
        account_value=member.email,
        is_primary=True,
        metadata={"source": member.external_source, "external_id": member.external_id},
    )
    if member.external_id:
        upsert_person_account(
            db,
            family_id=member.family_id,
            person=person,
            account_type=f"{member.external_source or 'directory'}_user_id",
            account_value=str(member.external_id),
            is_primary=True,
            metadata={"source": member.external_source},
        )
    seed_person_aliases(db, person=person, member=member)
    seed_person_accounts(db, person=person, member=member)
    ensure_family_feature_defaults(db, member.family_id)
    return person


def upsert_person_account(
    db: Session,
    *,
    family_id: int,
    person: Person,
    account_type: str,
    account_value: str,
    is_primary: bool = False,
    metadata: dict[str, Any] | None = None,
) -> PersonAccount:
    normalized_value = normalize_alias(account_value)
    existing = db.execute(
        select(PersonAccount).where(
            PersonAccount.account_type == account_type,
            PersonAccount.normalized_value == normalized_value,
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = PersonAccount(
            family_id=family_id,
            person_id=person.person_id,
            account_type=account_type,
            account_value=account_value.strip(),
            normalized_value=normalized_value,
            is_primary=is_primary,
            metadata_jsonb=metadata or {},
        )
        db.add(existing)
        db.flush()
    else:
        existing.family_id = family_id
        existing.person_id = person.person_id
        existing.account_value = account_value.strip()
        existing.is_primary = is_primary or existing.is_primary
        existing.metadata_jsonb = metadata or existing.metadata_jsonb
    return existing


def seed_person_aliases(db: Session, *, person: Person, member: FamilyMember) -> None:
    raw_seeds = list(ALIAS_SEED_BY_EMAIL.get(member.email.strip().lower(), []))
    raw_seeds.append(member.display_name)
    seen_normalized: set[str] = set()
    for alias in raw_seeds:
        alias_value = (alias or "").strip()
        normalized = normalize_alias(alias_value)
        if not normalized:
            continue
        if normalized in seen_normalized:
            continue
        seen_normalized.add(normalized)
        existing = db.execute(
            select(PersonAlias).where(
                PersonAlias.family_id == member.family_id,
                PersonAlias.person_id == person.person_id,
                PersonAlias.normalized_alias == normalized,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                PersonAlias(
                    family_id=member.family_id,
                    person_id=person.person_id,
                    alias=alias_value,
                    normalized_alias=normalized,
                    priority=10 if normalized == normalize_alias(member.display_name) else 100,
                    is_primary=normalized == normalize_alias(member.display_name),
                )
            )


def seed_person_accounts(db: Session, *, person: Person, member: FamilyMember) -> None:
    for account_type, values in ACCOUNT_SEED_BY_EMAIL.get(member.email.strip().lower(), {}).items():
        for index, account_value in enumerate(values):
            upsert_person_account(
                db,
                family_id=member.family_id,
                person=person,
                account_type=account_type,
                account_value=account_value,
                is_primary=index == 0,
                metadata={"source": "seed"},
            )


def ensure_family_feature_defaults(db: Session, family_id: int) -> None:
    existing = {
        row.feature_key: row
        for row in db.execute(select(FamilyFeature).where(FamilyFeature.family_id == family_id)).scalars().all()
    }
    pending_keys = {
        row.feature_key
        for row in db.new
        if isinstance(row, FamilyFeature) and row.family_id == family_id
    }
    now = datetime.now(timezone.utc)
    created = False
    for feature_key, enabled in DEFAULT_FEATURES.items():
        if feature_key in existing or feature_key in pending_keys:
            continue
        db.add(
            FamilyFeature(
                family_id=family_id,
                feature_key=feature_key,
                enabled=enabled,
                config_jsonb={},
                created_at=now,
                updated_at=now,
            )
        )
        created = True
    if created:
        db.flush()
        pending_keys.add(feature_key)


def feature_enabled(db: Session, family_id: int, feature_key: str) -> bool:
    ensure_family_feature_defaults(db, family_id)
    row = db.execute(
        select(FamilyFeature).where(FamilyFeature.family_id == family_id, FamilyFeature.feature_key == feature_key)
    ).scalar_one_or_none()
    if row is None:
        return DEFAULT_FEATURES.get(feature_key, False)
    return bool(row.enabled)


def require_feature_enabled(db: Session, family_id: int, feature_key: str) -> None:
    if not feature_enabled(db, family_id, feature_key):
        raise HTTPException(status_code=404, detail=f"{feature_key} domain is disabled for this family")


def resolve_person_by_email(db: Session, family_id: int, email: str) -> Person:
    normalized = normalize_alias(email)
    account = db.execute(
        select(PersonAccount).where(
            PersonAccount.family_id == family_id,
            PersonAccount.account_type == "email",
            PersonAccount.normalized_value == normalized,
        )
    ).scalar_one_or_none()
    if account is not None:
        person = db.get(Person, account.person_id)
        if person is not None:
            return person

    member = db.execute(
        select(FamilyMember).where(FamilyMember.family_id == family_id, FamilyMember.email == email.strip().lower())
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=403, detail="not a member of this family")
    person = ensure_person_for_member(db, member)
    db.flush()
    return person


def resolve_person_by_actor_identifier(db: Session, family_id: int, actor_identifier: str) -> Person:
    candidate = (actor_identifier or "").strip()
    if not candidate:
        raise HTTPException(status_code=403, detail="not a member of this family")

    normalized = normalize_alias(candidate)
    account = db.execute(
        select(PersonAccount).where(
            PersonAccount.family_id == family_id,
            PersonAccount.normalized_value == normalized,
        )
    ).scalar_one_or_none()
    if account is not None:
        person = db.get(Person, account.person_id)
        if person is not None:
            return person

    return resolve_person_by_email(db, family_id, candidate.lower())


def resolve_person_by_alias(db: Session, family_id: int, alias: str) -> tuple[Person | None, str, float, str | None]:
    normalized = normalize_alias(alias)
    if not normalized:
        return None, "no_match", 0.0, None
    rows = db.execute(
        select(PersonAlias)
        .where(PersonAlias.family_id == family_id, PersonAlias.normalized_alias == normalized)
        .order_by(PersonAlias.priority.asc(), PersonAlias.id.asc())
    ).scalars().all()
    if not rows:
        return None, "no_match", 0.0, None
    person = db.get(Person, rows[0].person_id)
    if person is None:
        return None, "dangling_alias", 0.0, rows[0].alias
    confidence = 1.0 if len(rows) == 1 else 0.65
    source = "exact_alias" if len(rows) == 1 else "exact_alias_ambiguous_priority"
    return person, source, confidence, rows[0].alias


def resolve_person_by_sender(
    db: Session,
    *,
    family_id: int,
    source_channel: str,
    source_sender_id: str,
) -> tuple[Person | None, str, float]:
    account_type = ACCOUNT_TYPE_BY_CHANNEL.get(source_channel.strip().lower(), f"{source_channel.strip().lower()}_sender_id")
    normalized = normalize_alias(source_sender_id)
    account = db.execute(
        select(PersonAccount).where(
            PersonAccount.family_id == family_id,
            PersonAccount.account_type == account_type,
            PersonAccount.normalized_value == normalized,
        )
    ).scalar_one_or_none()
    if account is None:
        return None, "no_sender_mapping", 0.0
    person = db.get(Person, account.person_id)
    if person is None:
        return None, "dangling_sender_mapping", 0.0
    return person, "sender_account", 1.0


def person_accounts_map(db: Session, person_id: str) -> dict[str, list[str]]:
    rows = db.execute(select(PersonAccount).where(PersonAccount.person_id == parse_person_id(person_id))).scalars().all()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row.account_type, []).append(row.account_value)
    return result


def person_alias_list(db: Session, person_id: str) -> list[str]:
    rows = db.execute(
        select(PersonAlias).where(PersonAlias.person_id == parse_person_id(person_id)).order_by(PersonAlias.priority.asc(), PersonAlias.alias.asc())
    ).scalars().all()
    return [row.alias for row in rows]


def list_family_persons(db: Session, family_id: int) -> list[Person]:
    members = db.execute(select(FamilyMember).where(FamilyMember.family_id == family_id)).scalars().all()
    for member in members:
        ensure_person_for_member(db, member)
    db.flush()
    return db.execute(select(Person).where(Person.family_id == family_id).order_by(Person.display_name.asc())).scalars().all()


def build_person_response(db: Session, person: Person) -> dict[str, Any]:
    return {
        "person_id": str(person.person_id),
        "family_id": person.family_id,
        "legacy_member_id": person.legacy_member_id,
        "canonical_name": person.canonical_name,
        "display_name": person.display_name,
        "role_in_family": person.role_in_family,
        "is_admin": person.is_admin,
        "status": person.status,
        "aliases": person_alias_list(db, str(person.person_id)),
        "accounts": person_accounts_map(db, str(person.person_id)),
    }


def resolve_context(
    db: Session,
    *,
    family_id: int,
    email: str,
    source_channel: str | None = None,
    source_sender_id: str | None = None,
    target_person_id: str | None = None,
) -> ResolvedPersonContext:
    family = db.get(Family, family_id)
    if family is None:
        raise HTTPException(status_code=404, detail="family not found")
    person = resolve_person_by_actor_identifier(db, family_id, email)
    family_slug = _ensure_family_slug(db, family)
    selected_target = target_person_id or str(person.person_id)
    if selected_target != str(person.person_id) and not person.is_admin:
        raise HTTPException(status_code=403, detail="admin role required for cross-member access")
    directory_account_id = None
    primary_email = None
    for account_type, values in person_accounts_map(db, str(person.person_id)).items():
        if account_type.endswith("_user_id") and directory_account_id is None:
            directory_account_id = values[0]
        if account_type == "email" and values:
            primary_email = values[0]
    return ResolvedPersonContext(
        family_id=family_id,
        family_slug=family_slug,
        person_id=str(person.person_id),
        actor_person_id=str(person.person_id),
        target_person_id=selected_target,
        is_family_admin=person.is_admin,
        directory_account_id=directory_account_id,
        primary_email=primary_email or email,
        source_channel=source_channel,
        source_sender_id=source_sender_id,
        resolution_source="authenticated_email",
        member_id=person.legacy_member_id,
    )


def export_openclaw_identity_registry(db: Session, *, output_path: str) -> dict[str, Any]:
    families = db.execute(select(Family).order_by(Family.id.asc())).scalars().all()
    payload: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "families": []}
    for family in families:
        slug = _ensure_family_slug(db, family)
        persons = [build_person_response(db, person) for person in list_family_persons(db, family.id)]
        features = {
            item.feature_key: item.enabled
            for item in db.execute(select(FamilyFeature).where(FamilyFeature.family_id == family.id)).scalars().all()
        }
        payload["families"].append({"family_id": family.id, "family_slug": slug, "name": family.name, "features": features, "persons": persons})
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return payload
