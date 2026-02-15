from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Person(BaseModel):
    id: str
    name: str
    role: str | None = None
    notes: str | None = None


class Goal(BaseModel):
    id: str
    name: str
    description: str | None = None
    weight: float = Field(default=1.0, ge=0.0)
    constraints: list[str] = Field(default_factory=list)


class Policy(BaseModel):
    name: str
    rules: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    a: str
    b: str
    type: str
    notes: str | None = None


class System(BaseModel):
    name: str
    description: str | None = None
    owner: str | None = None


class Plan(BaseModel):
    name: str
    items: list[dict[str, Any]] = Field(default_factory=list)


class FamilyDnaSnapshot(BaseModel):
    """
    Strict-ish schema for Family DNA. Keep it extensible but validate structure.
    """

    people: list[Person] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    policies: list[Policy] = Field(default_factory=list)
    systems: list[System] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    plans: list[Plan] = Field(default_factory=list)

