"""Phase 1 gate: JWT claims → user, role names, and the async job lifecycle (local worker thread, real DynamoDB/S3)."""
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "agent" / "eval"), str(ROOT / "backend"), str(ROOT / "playground")]
import accounts  # noqa: E402


def test_claims_from_api_gateway():
    # HTTP API passes list claims as "[a b]"; REST passes a list
    u = accounts.claims_user({"sub": "abc", "email": "a@x.edu", "cognito:groups": "[faculty aspph-admin]"})
    assert u["role"] == "aspph-admin" and u["sub"] == "abc"
    assert accounts.claims_user({"sub": "abc", "cognito:groups": ["faculty"]})["role"] == "faculty"
    assert accounts.claims_user({"sub": "abc"})["role"] == "faculty"
    assert accounts.claims_user({}) is None


def test_role_names_and_alias():
    accounts.require_role({"role": "aspph-admin"}, "aspph-admin")
    accounts.require_role({"role": "aspph-staff"}, "aspph-admin")  # the old name still counts
    with pytest.raises(Exception):
        accounts.require_role({"role": "faculty"}, "aspph-admin")
    with pytest.raises(Exception):
        accounts.require_role({"role": "made-up"}, "faculty")


def test_jwt_mode_reads_only_verified_claims(monkeypatch):
    monkeypatch.setenv("PHACT_AUTH", "1")
    monkeypatch.setenv("PHACT_AUTH_MODE", "jwt")

    class Req:  # what Mangum hands FastAPI: the API Gateway event in the scope
        def __init__(self, claims):
            self.scope = {"aws.event": {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}}
            self.cookies = {"phact_session": "forged"}
    assert accounts.request_user(Req({"sub": "s1", "email": "p@x.edu"}))["sub"] == "s1"
    assert accounts.request_user(Req({})) is None  # a cookie is ignored in JWT mode


def test_job_lifecycle_and_ownership(monkeypatch):
    monkeypatch.setenv("PHACT_JOBS", "local")
    import jobs
    import userdata
    owner = {"sub": "test-jobowner", "email": "o@x.edu", "name": "", "role": "faculty"}
    other = {"sub": "test-jobother", "email": "x@x.edu", "name": "", "role": "faculty"}
    with pytest.raises(ValueError):
        jobs.create(owner, "/api/data/profile", {})  # only long routes may become jobs
    jid = jobs.create(owner, "/api/classify", {"text": "Homework 3: compute the odds ratio for question 2. Due week 6. 20 points."})
    with pytest.raises(KeyError):
        jobs.get(other, jid)  # another user's job looks missing
    for _ in range(60):
        st = jobs.get(owner, jid)
        if st["status"] in ("DONE", "FAILED"):
            break
        time.sleep(1)
    assert st["status"] == "DONE", st
    assert st["result"]["doc_type"] == "homework"
    jobs.run(jid)  # a duplicate invocation must not run it again
    assert jobs.get(owner, jid)["status"] == "DONE"
    userdata.table().delete_item(Key={"PK": f"JOB#{jid}", "SK": "JOB"})
    for k in ("request", "result"):
        userdata.s3().delete_object(Bucket=userdata.BUCKET, Key=f"jobs/{jid}/{k}.json")
