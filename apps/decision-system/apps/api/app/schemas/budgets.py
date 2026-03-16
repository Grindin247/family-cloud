from datetime import date

from pydantic import BaseModel, Field


class MemberAllowanceUpdate(BaseModel):
    member_id: int
    allowance: int = Field(ge=0, le=50)


class BudgetPolicyUpdate(BaseModel):
    threshold_1_to_5: float = Field(ge=1.0, le=5.0)
    period_days: int = Field(ge=7, le=365)
    default_allowance: int = Field(ge=0, le=50)
    member_allowances: list[MemberAllowanceUpdate] = Field(default_factory=list)


class MemberBudgetSummary(BaseModel):
    member_id: int
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
    members: list[MemberBudgetSummary]

