"""Courses: list, create, upload a syllabus, save the checks (steps 2–6 of the professor flow)."""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import User, current_user
from app.schemas import CourseIn, UploadUrlOut

router = APIRouter(prefix="/api/courses")


@router.get("")
def list_courses(user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: Query PK=user_pk, SK begins_with COURSE#")


@router.post("")
def create_course(body: CourseIn, user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: put COURSE#<code>; pre-fill competencies from the school's COURSEMAP")


@router.post("/{code}/upload-url", response_model=UploadUrlOut)
def upload_url(code: str, filename: str, user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: presigned PUT into the uploads bucket (storage.upload_key)")


@router.post("/{code}/syllabus")
def register_syllabus(code: str, key: str, user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: extract text (services/extract.py) → scrub (services/safety.py) → save SYL#v<n> → return the text for review (US-5)")


@router.put("/{code}/settings")
def save_settings(code: str, user: User = Depends(current_user)):
    raise HTTPException(501, "TODO: save confirmed competencies, AI-level target, assessment types, format/size")
