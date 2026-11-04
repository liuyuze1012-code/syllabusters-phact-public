"""POST /api/exports: build the DOCX from ACCEPTED edits only (US-11) and return a download link."""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import User, current_user

router = APIRouter(prefix="/api/exports")


@router.post("")
def export(analysis_id: str, share_as_example: bool = False, user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: services/export_docx.build → exports bucket → SYL#v<n+1> → presigned GET")
