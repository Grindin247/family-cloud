from datetime import date

from pydantic import BaseModel, Field


class PersonAllowanceUpdate(BaseModel):
    person_id: str
    allowance: int = Field(ge=0, le=50)


class BudgetPolicyUpdate(BaseModel):
    threshold_1_to_5: float = Field(ge=1.0, le=5.0)
    period_days: int = Field(ge=7, le=365)
    default_allowance: int = Field(ge=0, le=50)
    person_allowances: list[PersonAllowanceUpdate] = Field(default_factory=list)


class PersonBudgetSummary(BaseModel):
    person_id: str
    display_name: str
    role: str
    allowance: int
    used: int
    remaining: int


class BudgetSummaryResponse(BaseModel):
    family_id: int
    threshold_1_to_5: float
    period_days: int
    default_allowance: int
    period_start_date: date
    period_end_date: date
    members: list[PersonBudgetSummary]
