from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "service": "question-management-service", "time": datetime.now(UTC)}
