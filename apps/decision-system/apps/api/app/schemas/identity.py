from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonResponse(BaseModel):
    person_id: str
    family_id: int
    legacy_member_id: int | None = None
    canonical_name: str
    display_name: str
    role_in_family: str | None = None
    is_admin: bool
    status: str
    aliases: list[str] = Field(default_factory=list)
    accounts: dict[str, list[str]] = Field(default_factory=dict)


class PersonListResponse(BaseModel):
    items: list[PersonResponse] = Field(default_factory=list)


class AliasResolutionResponse(BaseModel):
    family_id: int
    query: str
    person_id: str | None = None
    display_name: str | None = None
    resolution_source: str
    confidence: float
    matched_alias: str | None = None


class SenderResolutionRequest(BaseModel):
    family_id: int
    source_channel: str = Field(min_length=1, max_length=64)
    source_sender_id: str = Field(min_length=1, max_length=255)


class SenderResolutionResponse(BaseModel):
    family_id: int
    source_channel: str
    source_sender_id: str
    person_id: str | None = None
    display_name: str | None = None
    resolution_source: str
    confidence: float


class ResolvedContextResponse(BaseModel):
    family_id: int
    family_slug: str
    person_id: str
    actor_person_id: str
    target_person_id: str
    is_family_admin: bool
    directory_account_id: str | None = None
    primary_email: str | None = None
    source_channel: str | None = None
    source_sender_id: str | None = None
    resolution_source: str
    member_id: int | None = None


class FamilyFeatureUpdate(BaseModel):
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


class FamilyFeatureResponse(BaseModel):
    family_id: int
    feature_key: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class FamilyFeatureListResponse(BaseModel):
    items: list[FamilyFeatureResponse] = Field(default_factory=list)
