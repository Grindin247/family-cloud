from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RelationshipType = Literal[
    "adult",
    "child",
    "guardian",
    "dependent",
    "spouse",
    "co_parent",
    "coach",
    "tutor",
    "clinician",
    "delegated_caregiver",
]

RoleTag = Literal["adult", "child"]


class OrmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConsentRecord(BaseModel):
    consent_key: str = Field(min_length=1, max_length=128)
    status: str = Field(default="granted", min_length=1, max_length=32)
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    notes: str | None = None


class AccountProfileSection(BaseModel):
    primary_login: str | None = Field(default=None, max_length=255)
    auth_providers: list[str] = Field(default_factory=list)
    auth_methods: list[str] = Field(default_factory=list)
    mfa_enabled: bool = False
    passkeys_enabled: bool = False
    passkey_labels: list[str] = Field(default_factory=list)
    recovery_methods: list[str] = Field(default_factory=list)
    recovery_contacts: list[str] = Field(default_factory=list)
    legal_consents: list[ConsentRecord] = Field(default_factory=list)
    security_notes: str | None = None
    last_reviewed_at: datetime | None = None


class PersonProfileSection(BaseModel):
    birthdate: date | None = None
    pronouns: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=64)
    languages: list[str] = Field(default_factory=list)
    role_tags: list[RoleTag] = Field(default_factory=list)
    traits: list[str] = Field(default_factory=list)
    demographic_notes: str | None = None


class LearningPreferences(BaseModel):
    modalities: list[str] = Field(default_factory=list)
    pace: str | None = Field(default=None, max_length=128)
    environments: list[str] = Field(default_factory=list)
    supports: list[str] = Field(default_factory=list)
    notes: str | None = None


class DietaryPreferences(BaseModel):
    restrictions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    notes: str | None = None


class AccessibilityNeeds(BaseModel):
    accommodations: list[str] = Field(default_factory=list)
    assistive_tools: list[str] = Field(default_factory=list)
    sensory_considerations: list[str] = Field(default_factory=list)
    mobility_considerations: list[str] = Field(default_factory=list)
    notes: str | None = None


class MotivationStyle(BaseModel):
    encouragements: list[str] = Field(default_factory=list)
    rewards: list[str] = Field(default_factory=list)
    triggers_to_avoid: list[str] = Field(default_factory=list)
    routines: list[str] = Field(default_factory=list)
    notes: str | None = None


class CommunicationPreferences(BaseModel):
    preferred_channels: list[str] = Field(default_factory=list)
    response_style: str | None = Field(default=None, max_length=128)
    cadence: str | None = Field(default=None, max_length=128)
    boundaries: list[str] = Field(default_factory=list)
    notes: str | None = None


class PreferencesSection(BaseModel):
    hobbies: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    learning_preferences: LearningPreferences = Field(default_factory=LearningPreferences)
    dietary_preferences: DietaryPreferences = Field(default_factory=DietaryPreferences)
    accessibility_needs: AccessibilityNeeds = Field(default_factory=AccessibilityNeeds)
    motivation_style: MotivationStyle = Field(default_factory=MotivationStyle)
    communication_preferences: CommunicationPreferences = Field(default_factory=CommunicationPreferences)


class ProfileUpdate(BaseModel):
    account_profile: AccountProfileSection = Field(default_factory=AccountProfileSection)
    person_profile: PersonProfileSection = Field(default_factory=PersonProfileSection)
    preferences: PreferencesSection = Field(default_factory=PreferencesSection)


class ViewerMembership(BaseModel):
    family_id: int
    family_name: str
    member_id: int
    person_id: str | None = None
    role: str


class ViewerMeResponse(BaseModel):
    authenticated: bool
    email: str | None = None
    memberships: list[ViewerMembership] = Field(default_factory=list)


class ViewerPersonResponse(BaseModel):
    person_id: str
    display_name: str
    role_in_family: str | None = None
    is_admin: bool = False
    status: str
    accounts: dict[str, list[str]] = Field(default_factory=dict)


class ViewerContextResponse(BaseModel):
    family_id: int
    family_slug: str
    person_id: str
    actor_person_id: str
    target_person_id: str
    is_family_admin: bool
    profile_enabled: bool
    primary_email: str | None = None
    directory_account_id: str | None = None
    member_id: int | None = None
    persons: list[ViewerPersonResponse] = Field(default_factory=list)


class ProfileFeatureUpdate(BaseModel):
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


class ProfileFeatureResponse(BaseModel):
    family_id: int
    feature_key: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | str | None = None


class RelationshipCreate(BaseModel):
    source_person_id: str
    target_person_id: str
    relationship_type: RelationshipType
    status: str = Field(default="active", min_length=1, max_length=32)
    is_mutual: bool | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationshipUpdate(BaseModel):
    source_person_id: str | None = None
    target_person_id: str | None = None
    relationship_type: RelationshipType | None = None
    status: str | None = Field(default=None, min_length=1, max_length=32)
    is_mutual: bool | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class RelationshipResponse(OrmResponse):
    relationship_id: str
    family_id: int
    source_person_id: str
    target_person_id: str
    relationship_type: RelationshipType
    status: str
    is_mutual: bool
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: datetime
    updated_at: datetime


class RelationshipListResponse(BaseModel):
    items: list[RelationshipResponse] = Field(default_factory=list)


class ProfileSummaryResponse(BaseModel):
    person_id: str
    family_id: int
    display_name: str
    canonical_name: str
    role_in_family: str | None = None
    is_admin: bool
    status: str
    role_tags: list[RoleTag] = Field(default_factory=list)
    hobbies: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    relationship_count: int = 0
    updated_at: datetime | None = None


class ProfileListResponse(BaseModel):
    items: list[ProfileSummaryResponse] = Field(default_factory=list)


class ProfileDetailResponse(BaseModel):
    profile_id: str | None = None
    family_id: int
    person_id: str
    display_name: str
    canonical_name: str
    role_in_family: str | None = None
    is_admin: bool
    status: str
    accounts: dict[str, list[str]] = Field(default_factory=dict)
    account_profile: AccountProfileSection = Field(default_factory=AccountProfileSection)
    person_profile: PersonProfileSection = Field(default_factory=PersonProfileSection)
    preferences: PreferencesSection = Field(default_factory=PreferencesSection)
    relationships: list[RelationshipResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
