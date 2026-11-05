"""Async jobs (ASPPH Technical Document: "API writes a QUEUED job and async-invokes a worker Lambda; UI polls").

API Gateway stops waiting after ~30 s, and an analysis takes 100+ s. So long calls become jobs:
  POST /api/jobs {path, body}  → JOB item QUEUED (DynamoDB) + request saved to S3 → worker invoked async → 202 {job_id}
  worker                       → runs the SAME FastAPI route in-process (no duplicated logic), as the job's owner
                                 → result to S3, item DONE (or FAILED with the error)
  GET /api/jobs/{id}           → status; the result once DONE. Only the owner can read their job.
Request and result live in S3 because they can exceed DynamoDB's 400 KB and Lambda's 256 KB async payload.
Locally (PHACT_JOBS=local) a thread plays the worker, so the whole flow is testable without AWS Lambda.
"""

import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone

import boto3

import userdata

LONG_PATHS = {  # routes that can outlast API Gateway's timeout
    "/api/extract", "/api/structure", "/api/analyze", "/api/analyze_more", "/api/chat", "/api/classify",
    "/api/assessment/structure", "/api/assessment/analyze",
    "/api/admin/sources/publish", "/api/admin/submissions/approve", "/api/admin/sources/status", "/api/uni/policy/extract",
}
TTL_DAYS = 7


def mode() -> str:
    return os.getenv("PHACT_JOBS", "off")  # off | local | lambda


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def allowed(path: str) -> bool:
    return path in LONG_PATHS or path.startswith(("/api/admin/sources/", "/api/admin/submissions/"))


def create(user: dict, path: str, body: dict | None, file: dict | None = None) -> str:
    """file = {"name", "b64"} for an upload. Returns the job id."""
    if not allowed(path):
        raise ValueError(f"{path} can't run as a job")
    jid = secrets.token_hex(10)
    s3 = userdata.s3()
    s3.put_object(Bucket=userdata.BUCKET, Key=f"jobs/{jid}/request.json",
                  Body=json.dumps({"path": path, "body": body, "file": file, "user": user}).encode())
    userdata.table().put_item(Item={"PK": f"JOB#{jid}", "SK": "JOB", "owner_sub": user["sub"], "path": path, "status": "QUEUED",
                                    "created_at": _now(), "ttl": int(time.time()) + TTL_DAYS * 86400})
    if mode() == "lambda":
        boto3.client("lambda", region_name=userdata.REGION).invoke(
            FunctionName=os.environ["WORKER_FUNCTION"], InvocationType="Event", Payload=json.dumps({"job_id": jid}).encode())
    else:  # local: a thread plays the worker Lambda
        threading.Thread(target=run, args=(jid,), daemon=True).start()
    return jid


def _update(jid: str, **fields) -> None:
    userdata.table().update_item(Key={"PK": f"JOB#{jid}", "SK": "JOB"},
                                 UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
                                 ExpressionAttributeNames={f"#{k}": k for k in fields},
                                 ExpressionAttributeValues={f":{k}": v for k, v in fields.items()})


def run(jid: str) -> None:
    """The worker. Claims the job (only a QUEUED job can start, so a retried invocation can't run it twice),
    replays the request through the real FastAPI app as the job's owner, and stores the response."""
    import accounts
    from fastapi.testclient import TestClient
    import server
    try:
        userdata.table().update_item(Key={"PK": f"JOB#{jid}", "SK": "JOB"}, UpdateExpression="SET #s = :r, started_at = :t",
                                     ConditionExpression="#s = :q", ExpressionAttributeNames={"#s": "status"},
                                     ExpressionAttributeValues={":r": "RUNNING", ":q": "QUEUED", ":t": _now()})
    except userdata.table().meta.client.exceptions.ConditionalCheckFailedException:
        return  # already taken by another invocation
    req = json.loads(userdata.s3().get_object(Bucket=userdata.BUCKET, Key=f"jobs/{jid}/request.json")["Body"].read())
    token = accounts.JOB_USER.set(req["user"])
    t0, status, body, err = time.monotonic(), 500, None, ""
    try:
        client = TestClient(server.app)
        if req.get("file"):
            import base64
            r = client.post(req["path"], files={"file": (req["file"]["name"], base64.b64decode(req["file"]["b64"]))})
        else:
            method = (req.get("body") or {}).pop("_method", "POST") if isinstance(req.get("body"), dict) else "POST"
            r = client.request(method, req["path"], json=req.get("body"))
        ok = r.status_code < 400
        userdata.s3().put_object(Bucket=userdata.BUCKET, Key=f"jobs/{jid}/result.json", Body=r.content,
                                 ContentType="application/json")
        status = r.status_code
        is_json = r.headers.get("content-type", "").startswith("application/json")
        body = r.json() if is_json else None
        err = "" if ok else ((body or {}).get("detail") if is_json else r.text) or ""
        _update(jid, status="DONE" if ok else "FAILED", http_status=r.status_code, finished_at=_now(),
                **({} if ok else {"error": str(err)[:500]}))
    except Exception as e:  # noqa: BLE001
        err = str(e)[:500]
        _update(jid, status="FAILED", error=err, finished_at=_now())
    finally:
        accounts.JOB_USER.reset(token)
        try:  # the Agent monitor's usage record: counts and times only; it never blocks or fails the job
            import usage
            usage.record(usage.build(jid, req["path"], req["user"], status, int((time.monotonic() - t0) * 1000), body, str(err)))
        except Exception:  # noqa: BLE001
            pass


def get(user: dict, jid: str) -> dict:
    item = userdata.table().get_item(Key={"PK": f"JOB#{jid}", "SK": "JOB"}).get("Item")
    if not item or item["owner_sub"] != user["sub"]:
        raise KeyError(jid)  # another user's job looks exactly like a missing one
    out = {"job_id": jid, "status": item["status"], "path": item["path"], "created_at": item["created_at"]}
    if item["status"] == "DONE":
        out["result"] = json.loads(userdata.s3().get_object(Bucket=userdata.BUCKET, Key=f"jobs/{jid}/result.json")["Body"].read())
    elif item["status"] == "FAILED":
        out["error"] = item.get("error", "The job failed.")
        out["http_status"] = int(item.get("http_status", 500))
    return out
