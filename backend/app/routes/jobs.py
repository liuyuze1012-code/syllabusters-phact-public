"""Jobs: start an analysis or a revise in the background and poll its status.

POST returns 202 immediately; the worker Lambda does the slow part (API Gateway stops at 29 s).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import User, current_user
from app.schemas import JobIn, JobOut

router = APIRouter(prefix="/api/jobs")


@router.post("", status_code=202, response_model=JobOut)
def start_job(body: JobIn, user: User = Depends(current_user)):
    # TODO: put JOB#<id> as QUEUED (TTL 7 days) with user_id/school_id from the token,
    #       then lambda.invoke(FunctionName=settings.worker_function, InvocationType="Event", Payload=...)
    raise HTTPException(501, "TODO")


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: User = Depends(current_user)):
    # TODO: read JOB#<id>; 404 unless it belongs to this user
    raise HTTPException(501, "TODO")
