"""User data: profiles, courses, progress, uploads and history (docs/contracts-userdata.md).

Plain functions, no web code. Every function takes the user's id (Cognito `sub`) first, and every key is
built from it, so one user can never read another's data by passing a different id in a request.
DynamoDB holds small, listable things; S3 holds big things (a course's full progress, uploaded files).
Nothing is kept on the server's disk or in memory, so this runs unchanged on EC2 or Lambda.
"""

import json
import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import boto3
from boto3.dynamodb.conditions import Key

_ids_file = Path(__file__).with_name("userdb_ids.json")
_ids = json.loads(_ids_file.read_text()) if _ids_file.exists() else {}
REGION = os.getenv("AWS_REGION", _ids.get("region", "us-west-2"))
TABLE = os.getenv("USERDB_TABLE", _ids.get("table", "phact-app"))
BUCKET = os.getenv("USERDATA_BUCKET", _ids.get("bucket", ""))

_table = None
_s3 = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    return _table


def s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=REGION)
    return _s3


def _pk(sub: str) -> str:
    if not sub or "#" in sub or "/" in sub:
        raise ValueError("bad user id")
    return f"USER#{sub}"


def _code(code: str) -> str:
    return quote(code, safe="")  # course codes have spaces: "EPID 601"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _plain(x):  # DynamoDB returns Decimal for numbers; JSON wants int/float
    if isinstance(x, list):
        return [_plain(v) for v in x]
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, Decimal):
        return int(x) if x == int(x) else float(x)
    return x


def _ddb(x):  # and wants Decimal, not float
    return json.loads(json.dumps(x), parse_float=Decimal)


# ---------- profile ----------
def get_profile(sub: str) -> dict | None:
    item = table().get_item(Key={"PK": _pk(sub), "SK": "PROFILE"}).get("Item")
    return _plain(item) if item else None


def put_profile(sub: str, **fields) -> dict:
    current = get_profile(sub) or {"created_at": now()}
    current.update({k: v for k, v in fields.items() if v is not None})
    current.update({"PK": _pk(sub), "SK": "PROFILE"})
    table().put_item(Item=_ddb(current))
    return current


# ---------- courses (list in DynamoDB, full progress in S3) ----------
def list_courses(sub: str) -> list[dict]:
    items = table().query(KeyConditionExpression=Key("PK").eq(_pk(sub)) & Key("SK").begins_with("COURSE#"))["Items"]
    return [_plain(i) for i in items]


def put_course(sub: str, course: dict, summary: dict | None = None) -> dict:
    code = course["code"]
    old = table().get_item(Key={"PK": _pk(sub), "SK": f"COURSE#{_code(code)}"}).get("Item") or {}
    item = {"PK": _pk(sub), "SK": f"COURSE#{_code(code)}", "course": course,
            "summary": {**_plain(old.get("summary", {})), **(summary or {}), "updated_at": now()},
            "progress_key": f"users/{sub}/courses/{_code(code)}.json"}
    table().put_item(Item=_ddb(item))
    return _plain(item)


def delete_course(sub: str, code: str) -> None:
    table().delete_item(Key={"PK": _pk(sub), "SK": f"COURSE#{_code(code)}"})
    s3().delete_object(Bucket=BUCKET, Key=f"users/{sub}/courses/{_code(code)}.json")


def get_progress(sub: str, code: str) -> dict | None:
    try:
        body = s3().get_object(Bucket=BUCKET, Key=f"users/{sub}/courses/{_code(code)}.json")["Body"].read()
    except s3().exceptions.NoSuchKey:
        return None
    return json.loads(body)


def put_progress(sub: str, code: str, progress: dict) -> None:
    s3().put_object(Bucket=BUCKET, Key=f"users/{sub}/courses/{_code(code)}.json",
                    Body=json.dumps(progress).encode(), ContentType="application/json")


def progress_summary(progress: dict) -> dict:
    """What the course list shows without opening the big file."""
    docs = [progress] + list((progress.get("materials") or {}).values())
    edits = sum(len(d.get("edits") or []) for d in docs)
    accepted = sum(sum(1 for v in (d.get("decisions") or {}).values() if v == "accepted") for d in docs)
    return {"documents": (1 if progress.get("outline") else 0) + len(progress.get("materials") or {}) + len(progress.get("refs") or []),
            "changes": edits, "accepted": accepted}


# ---------- uploaded files (original + hidden-name map) ----------
def upload_key(sub: str, doc_id: str, suffix: str) -> str:
    if not doc_id.isalnum():
        raise ValueError("bad document id")
    return f"users/{sub}/uploads/{doc_id}{suffix}"


def put_upload(sub: str, doc_id: str, suffix: str, data: bytes) -> None:
    s3().put_object(Bucket=BUCKET, Key=upload_key(sub, doc_id, suffix), Body=data)


def get_upload(sub: str, doc_id: str, suffix: str) -> bytes | None:
    try:
        return s3().get_object(Bucket=BUCKET, Key=upload_key(sub, doc_id, suffix))["Body"].read()
    except s3().exceptions.NoSuchKey:
        return None


# ---------- history ----------
def log_event(sub: str, type_: str, course: str = "", detail: str = "") -> None:
    table().put_item(Item={"PK": _pk(sub), "SK": f"EVENT#{now()}#{secrets.token_hex(2)}",
                           "type": type_[:30], "course": course[:60], "detail": detail[:300]})


def list_events(sub: str, limit: int = 50) -> list[dict]:
    items = table().query(KeyConditionExpression=Key("PK").eq(_pk(sub)) & Key("SK").begins_with("EVENT#"),
                          ScanIndexForward=False, Limit=limit)["Items"]
    return [{"at": i["SK"].split("#")[1], "type": i["type"], "course": i.get("course", ""), "detail": i.get("detail", "")}
            for i in items]


def delete_user_data(sub: str) -> None:
    """Remove everything a user has (used by tests; the basis of a future 'delete my account')."""
    pk = _pk(sub)
    items = table().query(KeyConditionExpression=Key("PK").eq(pk), ProjectionExpression="PK, SK")["Items"]
    with table().batch_writer() as w:
        for i in items:
            w.delete_item(Key={"PK": i["PK"], "SK": i["SK"]})
    listed = s3().list_objects_v2(Bucket=BUCKET, Prefix=f"users/{sub}/").get("Contents", [])
    for obj in listed:
        s3().delete_object(Bucket=BUCKET, Key=obj["Key"])
