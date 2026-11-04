"""Edits: read an analysis and accept/reject each proposed edit (US-10)."""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import User, current_user
from app.schemas import DecisionIn

router = APIRouter(prefix="/api")


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: ANALYSIS item + its EDIT# items + passages (for the report and Edit studio)")


@router.post("/edits/{edit_id}/decision")
def decide(edit_id: str, body: DecisionIn, user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: set status, save DECISION#<ts> with user and time; store the comment as FEEDBACK")
