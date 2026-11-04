"""GET /me: the signed-in user's profile, school and groups (for the Home screen)."""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import User, current_user

router = APIRouter(prefix="/api")


@router.get("/me")
def me(user: User = Depends(current_user)):
    # TODO: load SCHOOL#<sid>#USER#<uid> / PROFILE and the school's name
    return {"user_id": user.user_id, "school_id": user.school_id, "groups": user.groups}


@router.put("/me/preferences")
def update_preferences(user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: save AI stance, comfort, notes to the PROFILE item")
