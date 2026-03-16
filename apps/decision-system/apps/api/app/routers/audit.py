from fastapi import APIRouter

router = APIRouter(prefix="/v1/audit", tags=["audit"])


@router.get("")
def list_audit_events():
    return {"items": []}
