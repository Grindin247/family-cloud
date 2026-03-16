from pydantic import BaseModel, Field


class GoalCreate(BaseModel):
    family_id: int
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    weight: float = Field(gt=0)
    action_types: list[str] = Field(default_factory=list)
    active: bool = True


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    weight: float | None = Field(default=None, gt=0)
    action_types: list[str] | None = None
    active: bool | None = None


class GoalResponse(BaseModel):
    id: int
    family_id: int
    name: str
    description: str
    weight: float
    action_types: list[str]
    active: bool


class GoalListResponse(BaseModel):
    items: list[GoalResponse]
