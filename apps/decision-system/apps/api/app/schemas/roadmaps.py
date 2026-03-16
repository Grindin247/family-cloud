from datetime import date

from pydantic import BaseModel, Field


class RoadmapCreate(BaseModel):
    decision_id: int
    bucket: str = Field(min_length=1, max_length=50)
    start_date: date | None = None
    end_date: date | None = None
    status: str = Field(default="Scheduled", min_length=1, max_length=50)
    dependencies: list[int] = Field(default_factory=list)
    use_discretionary_budget: bool = False


class RoadmapUpdate(BaseModel):
    bucket: str | None = Field(default=None, min_length=1, max_length=50)
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = Field(default=None, min_length=1, max_length=50)
    dependencies: list[int] | None = None


class RoadmapResponse(BaseModel):
    id: int
    decision_id: int
    bucket: str
    start_date: date | None
    end_date: date | None
    status: str
    dependencies: list[int]


class RoadmapListResponse(BaseModel):
    items: list[RoadmapResponse]
