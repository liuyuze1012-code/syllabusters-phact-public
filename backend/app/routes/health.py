"""GET /health: public status check (no auth). Used by smoke tests and uptime checks."""

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True, "agent_mode": settings.agent_mode}
