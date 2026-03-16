from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class FamilyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class FamilyUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class FamilyResponse(BaseModel):
    id: int
    name: str
    created_at: datetime


class FamilyListResponse(BaseModel):
    items: list[FamilyResponse]


class FamilyMemberCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=255)
    role: str = Field(pattern="^(admin|editor|viewer)$")


class FamilyMemberUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, pattern="^(admin|editor|viewer)$")


class FamilyMemberResponse(BaseModel):
    id: int
    family_id: int
    email: EmailStr
    display_name: str
    role: str


class FamilyMemberListResponse(BaseModel):
    items: list[FamilyMemberResponse]
