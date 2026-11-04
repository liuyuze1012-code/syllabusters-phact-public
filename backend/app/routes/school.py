"""School admin routes: the school profile and AI policy (group school-admin only)."""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import User, current_user, require_group

router = APIRouter(prefix="/api/school")


@router.get("")
def get_school(user: User = Depends(current_user)):
    require_group(user, "school-admin")
    raise HTTPException(501, "TODO: SCHOOL#<sid> PROFILE + POLICY")


@router.put("/policy")
def put_policy(user: User = Depends(current_user)):
    require_group(user, "school-admin")
    raise HTTPException(501, "TODO: save confirmed rules to SCHOOL#<sid> POLICY")
