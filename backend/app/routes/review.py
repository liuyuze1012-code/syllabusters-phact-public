"""ASPPH reviewer routes for the Review console (group aspph-reviewer only).

One person, one gate: the reviewer checks a document and clicks "Approve & publish".
That sends the stored Step Functions task token back, and the pipeline (not the reviewer)
publishes, syncs the knowledge base, runs the search tests, and reports the result here.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import User, current_user, require_group

router = APIRouter(prefix="/api/review")


class ReviewDecision(BaseModel):
    decision: Literal["approve_publish", "send_back", "reject"]
    notes: str | None = None
    metadata: dict | None = None   # corrected title / source_type / year


@router.get("/queue")
def queue(user: User = Depends(current_user)):
    require_group(user, "aspph-reviewer")
    raise HTTPException(501, "TODO: list SOURCE# items by status: in_review, publishing, published, failed")


@router.get("/{source_id}")
def detail(source_id: str, user: User = Depends(current_user)):
    require_group(user, "aspph-reviewer")
    raise HTTPException(501, "TODO: presigned links to the original PDF and the cleaned preview + check results")


@router.post("/{source_id}/decision")
def decision(source_id: str, body: ReviewDecision, user: User = Depends(current_user)):
    require_group(user, "aspph-reviewer")
    # approve_publish → stepfunctions.send_task_success(taskToken=<stored>, output=metadata)
    # send_back / reject → send_task_failure; save reviewer name, time, notes on SOURCE#<id>
    raise HTTPException(501, "TODO")


@router.post("/{source_id}/retire")
def retire(source_id: str, user: User = Depends(current_user)):
    require_group(user, "aspph-reviewer")
    raise HTTPException(501, "TODO: start the retire flow (remove from kb/ + originals/, re-sync)")


@router.post("/submit")
def submit(user: User = Depends(current_user)):
    require_group(user, "aspph-reviewer")
    raise HTTPException(501, "TODO: presigned PUT into intake/incoming/ + create SOURCE#<id>")
