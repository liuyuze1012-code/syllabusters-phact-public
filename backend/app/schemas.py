"""Request/response bodies for the web API (what the frontend sends and receives).

The agent contract is NOT here; it lives in shared/phact_contracts/agent.py.
"""

from typing import Literal

from pydantic import BaseModel


class CourseIn(BaseModel):
    code: str
    name: str
    term: str
    level: Literal["MPH", "DrPH", "BS", "other"] = "MPH"
    format: Literal["in_person", "online_sync", "online_async", "hybrid"]
    size: int


class UploadUrlOut(BaseModel):
    upload_url: str
    key: str
    expires_in: int = 300


class JobIn(BaseModel):
    type: Literal["analysis", "revise"]
    course_code: str
    analysis_id: str | None = None       # revise only
    message: str | None = None           # revise only
    target_edit_ids: list[str] = []


class JobOut(BaseModel):
    job_id: str
    status: Literal["QUEUED", "RUNNING", "COMPLETE", "FAILED"]
    result_id: str | None = None         # analysis_id when COMPLETE
    message: str | None = None           # friendly error when FAILED


class DecisionIn(BaseModel):
    decision: Literal["accept", "reject"]
    comment: str | None = None
