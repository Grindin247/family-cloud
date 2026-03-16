from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Family, FamilyMember, RoleEnum


@dataclass(frozen=True)
class KeycloakSyncStats:
    families_created: int = 0
    families_updated: int = 0
    members_created: int = 0
    members_updated: int = 0
    members_deleted: int = 0


def _token_url() -> str:
    return f"{settings.keycloak_base_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"


def _admin_groups_url() -> str:
    return f"{settings.keycloak_base_url}/admin/realms/{settings.keycloak_realm}/groups"


def _admin_group_members_url(group_id: str) -> str:
    return f"{settings.keycloak_base_url}/admin/realms/{settings.keycloak_realm}/groups/{group_id}/members"


def _require_keycloak_sync_config() -> None:
    if not settings.keycloak_sync_client_id or not settings.keycloak_sync_client_secret:
        raise RuntimeError("missing KEYCLOAK_SYNC_CLIENT_ID / KEYCLOAK_SYNC_CLIENT_SECRET")


async def _fetch_admin_token(client: httpx.AsyncClient) -> str:
    _require_keycloak_sync_config()
    resp = await client.post(
        _token_url(),
        data={
            "grant_type": "client_credentials",
            "client_id": settings.keycloak_sync_client_id,
            "client_secret": settings.keycloak_sync_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("keycloak token response missing access_token")
    return token


def _walk_groups(groups: list[dict]) -> list[dict]:
    out: list[dict] = []
    stack = list(groups)
    while stack:
        g = stack.pop()
        out.append(g)
        subs = g.get("subGroups") or []
        if isinstance(subs, list) and subs:
            stack.extend(subs)
    return out


async def _list_groups(client: httpx.AsyncClient, token: str) -> list[dict]:
    resp = await client.get(
        _admin_groups_url(),
        params={"briefRepresentation": "false"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("unexpected keycloak groups response")
    return _walk_groups(data)


async def _list_group_members(client: httpx.AsyncClient, token: str, group_id: str) -> list[dict]:
    members: list[dict] = []
    first = 0
    page_size = 200
    while True:
        resp = await client.get(
            _admin_group_members_url(group_id),
            params={"first": first, "max": page_size},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        page = resp.json()
        if not isinstance(page, list):
            raise RuntimeError("unexpected keycloak group members response")
        if not page:
            break
        members.extend(page)
        if len(page) < page_size:
            break
        first += page_size
    return members


def _display_name(user: dict) -> str:
    first = (user.get("firstName") or "").strip()
    last = (user.get("lastName") or "").strip()
    if first or last:
        return f"{first} {last}".strip()
    return (user.get("username") or user.get("email") or "Unknown").strip()


async def sync_keycloak_families(db: Session) -> KeycloakSyncStats:
    """
    Sync Keycloak groups with suffix KEYCLOAK_SYNC_GROUP_SUFFIX into Families and FamilyMembers.

    Rules:
    - Group -> Family is keyed by (external_source='keycloak', external_id=<group_id>)
    - Member -> FamilyMember is keyed by (family_id, external_source='keycloak', external_id=<user_id>)
    - For Keycloak-managed memberships, the group membership is treated as the source of truth.
    """
    suffix = settings.keycloak_sync_group_suffix
    stats = KeycloakSyncStats()

    timeout = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token = await _fetch_admin_token(client)
        groups = await _list_groups(client, token)
        family_groups = [g for g in groups if isinstance(g.get("name"), str) and g["name"].endswith(suffix)]

        for group in family_groups:
            group_id = str(group.get("id") or "")
            group_name = str(group.get("name") or "")
            if not group_id or not group_name:
                continue

            family = db.execute(
                select(Family).where(
                    Family.external_source == "keycloak",
                    Family.external_id == group_id,
                )
            ).scalar_one_or_none()

            if family is None:
                family = Family(
                    name=group_name,
                    external_source="keycloak",
                    external_id=group_id,
                    external_name=group_name,
                )
                db.add(family)
                db.flush()
                stats = KeycloakSyncStats(
                    families_created=stats.families_created + 1,
                    families_updated=stats.families_updated,
                    members_created=stats.members_created,
                    members_updated=stats.members_updated,
                    members_deleted=stats.members_deleted,
                )
            else:
                changed = False
                if family.external_name != group_name:
                    family.external_name = group_name
                    changed = True
                if family.name != group_name:
                    family.name = group_name
                    changed = True
                if changed:
                    stats = KeycloakSyncStats(
                        families_created=stats.families_created,
                        families_updated=stats.families_updated + 1,
                        members_created=stats.members_created,
                        members_updated=stats.members_updated,
                        members_deleted=stats.members_deleted,
                    )

            members = await _list_group_members(client, token, group_id)
            remote_by_id: dict[str, dict] = {}
            for u in members:
                uid = u.get("id")
                if uid:
                    remote_by_id[str(uid)] = u

            # Upsert remote members.
            existing_members = db.execute(
                select(FamilyMember).where(
                    FamilyMember.family_id == family.id,
                    FamilyMember.external_source == "keycloak",
                )
            ).scalars().all()
            existing_by_ext_id = {str(m.external_id): m for m in existing_members if m.external_id}

            for ext_id, u in remote_by_id.items():
                email = (u.get("email") or "").strip()
                if not email:
                    # Without email, the app can't identify the user at the auth boundary.
                    continue
                email = email.lower()

                display = _display_name(u)
                member = existing_by_ext_id.get(ext_id)
                if member is None:
                    member = FamilyMember(
                        family_id=family.id,
                        email=email,
                        display_name=display,
                        role=RoleEnum.editor,
                        external_source="keycloak",
                        external_id=ext_id,
                    )
                    db.add(member)
                    stats = KeycloakSyncStats(
                        families_created=stats.families_created,
                        families_updated=stats.families_updated,
                        members_created=stats.members_created + 1,
                        members_updated=stats.members_updated,
                        members_deleted=stats.members_deleted,
                    )
                else:
                    changed = False
                    if member.email != email:
                        member.email = email
                        changed = True
                    if member.display_name != display:
                        member.display_name = display
                        changed = True
                    if changed:
                        stats = KeycloakSyncStats(
                            families_created=stats.families_created,
                            families_updated=stats.families_updated,
                            members_created=stats.members_created,
                            members_updated=stats.members_updated + 1,
                            members_deleted=stats.members_deleted,
                        )

            # Remove members no longer in the Keycloak group.
            remote_ids = set(remote_by_id.keys())
            for member in existing_members:
                if member.external_id and str(member.external_id) not in remote_ids:
                    db.delete(member)
                    stats = KeycloakSyncStats(
                        families_created=stats.families_created,
                        families_updated=stats.families_updated,
                        members_created=stats.members_created,
                        members_updated=stats.members_updated,
                        members_deleted=stats.members_deleted + 1,
                    )

        db.commit()
        return stats
