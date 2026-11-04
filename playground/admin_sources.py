"""ASPPH admin: the knowledge-base source library (docs/team/PLAN-accounts-admin.md, Phases 9–11).

The S3 knowledge bucket is the source of truth: `kb/<type>/<doc_id>__<n>.md` + `.metadata.json` per section
(what Bedrock indexes) and `originals/<doc_id>.pdf` (citation links). Admin actions only change those files and
re-sync, so there's no second copy to drift. Every action is written to the audit log.

Lifecycle per document: active (searched) · secondary (older edition, fallback only) · retired (never searched).
"""

import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

import userdata

ROOT = Path(__file__).resolve().parents[1]
_kb = json.loads((ROOT / "knowledge-base" / "kb_ids.json").read_text())
REGION = _kb.get("region", "us-west-2")
KB_BUCKET = os.getenv("KNOWLEDGE_BUCKET", _kb["knowledge_bucket"])
KB_ID = os.getenv("KB_ID", _kb["kb_id"])
DS_ID = os.getenv("DATA_SOURCE_ID", _kb["data_source_id"])
TYPES = ("guidance", "workforce", "practice", "exemplar")
STATUSES = ("active", "secondary", "retired")


def _s3():
    return boto3.client("s3", region_name=REGION)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:60] or "source"


# ---------- audit log ----------
def audit(actor: dict, action: str, target: str, detail: str = "") -> None:
    userdata.table().put_item(Item={"PK": "AUDIT", "SK": f"{_now()}#{secrets.token_hex(2)}", "actor_sub": actor["sub"],
                                    "actor_email": actor.get("email", ""), "action": action, "target": target, "detail": detail[:300]})


def list_audit(limit: int = 50) -> list[dict]:
    from boto3.dynamodb.conditions import Key
    items = userdata.table().query(KeyConditionExpression=Key("PK").eq("AUDIT"), ScanIndexForward=False, Limit=limit)["Items"]
    return [{"at": i["SK"].split("#")[0], "by": i.get("actor_email", ""), "action": i["action"], "target": i["target"],
             "detail": i.get("detail", "")} for i in items]


# ---------- the library ----------
def _metadata_keys() -> list[str]:
    keys, token = [], None
    while True:
        kw = {"Bucket": KB_BUCKET, "Prefix": "kb/", **({"ContinuationToken": token} if token else {})}
        r = _s3().list_objects_v2(**kw)
        keys += [o["Key"] for o in r.get("Contents", []) if o["Key"].endswith(".metadata.json")]
        if not r.get("IsTruncated"):
            return keys
        token = r["NextContinuationToken"]


def list_sources() -> list[dict]:
    """One row per document (a document is several section files sharing a doc_id)."""
    docs: dict[str, dict] = {}
    s3 = _s3()
    for key in _metadata_keys():
        a = json.loads(s3.get_object(Bucket=KB_BUCKET, Key=key)["Body"].read())["metadataAttributes"]
        d = docs.setdefault(a.get("doc_id", key), {"doc_id": a.get("doc_id", key), "title": a.get("title", ""),
                                                    "source_type": a.get("source_type", ""), "year": a.get("year"),
                                                    "status": a.get("status", "active"), "family": a.get("family", a.get("doc_id")),
                                                    "publisher": a.get("publisher", ""), "sections": 0, "keys": [],
                                                    # for the library's grouping and filters
                                                    "area": a.get("area", ""), "material_type": a.get("material_type", ""),
                                                    "aias_level": a.get("aias_level"), "original": a.get("original", ""), "section_titles": []})
        d["sections"] += 1
        d["keys"].append(key)
        if a.get("section"):
            d["section_titles"].append(a["section"])
    return sorted(docs.values(), key=lambda d: (d["source_type"], d["title"]))


def _rewrite_status(doc: dict, status: str) -> None:
    s3 = _s3()
    for key in doc["keys"]:
        m = json.loads(s3.get_object(Bucket=KB_BUCKET, Key=key)["Body"].read())
        m["metadataAttributes"]["status"] = status
        s3.put_object(Bucket=KB_BUCKET, Key=key, Body=(json.dumps(m, indent=2) + "\n").encode(), ContentType="application/json")


# ---------- sync (one ingestion job at a time per data source) ----------
def sync(timeout_s: int = 600) -> dict:
    ag = boto3.client("bedrock-agent", region_name=REGION)
    t0 = time.monotonic()
    while True:  # wait for any job already running (two at once are refused)
        running = ag.list_ingestion_jobs(knowledgeBaseId=KB_ID, dataSourceId=DS_ID, maxResults=5,
                                         sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"})["ingestionJobSummaries"]
        if not any(j["status"] in ("STARTING", "IN_PROGRESS") for j in running):
            break
        if time.monotonic() - t0 > timeout_s:
            raise TimeoutError("another knowledge-base sync is still running")
        time.sleep(4)
    job = ag.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID)["ingestionJob"]["ingestionJobId"]
    while True:
        j = ag.get_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID, ingestionJobId=job)["ingestionJob"]
        if j["status"] in ("COMPLETE", "FAILED", "STOPPED"):
            st = j.get("statistics", {})
            # "COMPLETE" can still mean some files were rejected: treat that as a failure, with the reason
            status = "PARTIAL" if j["status"] == "COMPLETE" and st.get("numberOfDocumentsFailed") else j["status"]
            return {"status": status, "stats": st, "failures": (j.get("failureReasons") or [])[:3]}
        if time.monotonic() - t0 > timeout_s:
            raise TimeoutError("knowledge-base sync took too long")
        time.sleep(4)


def found_by_search(doc_id: str, query: str) -> bool:
    rt = boto3.client("bedrock-agent-runtime", region_name=REGION)
    for _ in range(3):  # the index can lag the sync by a few seconds
        res = rt.retrieve(knowledgeBaseId=KB_ID, retrievalQuery={"text": query[:900]}, retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": 5, "filter": {"equals": {"key": "status", "value": "active"}}}})
        if any(r.get("metadata", {}).get("doc_id") == doc_id for r in res["retrievalResults"]):
            return True
        time.sleep(5)
    return False


# ---------- upload → preview → publish ----------
HEADING = re.compile(r"^(#{1,3}\s+.+|\d+(\.\d+)*\.?\s+[A-Z].{2,80}|[A-Z][A-Za-z0-9 ,&:'()/-]{3,80})$")


def split_sections(text: str, max_words: int = 450) -> list[dict]:
    """Code-only splitter: start a new section at heading-like lines, and keep each section under ~450 words
    so it stays readable as one citation. The admin can edit titles and text in the preview."""
    sections, title, buf = [], "Introduction", []

    def flush():
        body = "\n".join(buf).strip()
        if len(body.split()) >= 25:
            sections.append({"title": title[:120], "text": body})
    for line in text.splitlines():
        s = line.strip()
        words = sum(len(x.split()) for x in buf)
        if s and len(s.split()) <= 12 and HEADING.match(s) and not s.endswith(".") and words >= 60:
            flush(); title, buf = s.lstrip("# ").strip(), []
        elif words >= max_words and not s:
            flush(); buf = []
        else:
            buf.append(line)
    flush()
    return sections or [{"title": title, "text": text.strip()}]


def save_preview(original: bytes, suffix: str, sections: list[dict]) -> str:
    pid = secrets.token_hex(8)
    s3 = boto3.client("s3", region_name=REGION)
    s3.put_object(Bucket=userdata.BUCKET, Key=f"admin/previews/{pid}{suffix}", Body=original)
    s3.put_object(Bucket=userdata.BUCKET, Key=f"admin/previews/{pid}.json",
                  Body=json.dumps({"suffix": suffix, "sections": sections}).encode())
    return pid


def publish(actor: dict, preview_id: str | None, meta: dict, sections: list[dict], replaces: str | None = None,
            old_status: str = "secondary") -> dict:
    """Write the sections + metadata to kb/, the original to originals/, demote the edition it replaces,
    sync, and confirm with a live search before reporting success."""
    if meta.get("source_type") not in TYPES:
        raise ValueError(f"source_type must be one of {TYPES}")
    if not sections:
        raise ValueError("nothing to publish")
    s3 = _s3()
    us3 = boto3.client("s3", region_name=REGION)
    prev = (json.loads(us3.get_object(Bucket=userdata.BUCKET, Key=f"admin/previews/{preview_id}.json")["Body"].read())
            if preview_id else {"suffix": ""})
    doc_id = slug(f"{meta['title']} {meta.get('year', '')}")
    if any(d["doc_id"] == doc_id for d in list_sources()):
        doc_id = f"{doc_id}-{secrets.token_hex(2)}"
    original_key = ""
    if prev["suffix"] == ".pdf":
        raw = us3.get_object(Bucket=userdata.BUCKET, Key=f"admin/previews/{preview_id}{prev['suffix']}")["Body"].read()
        original_key = f"originals/{doc_id}.pdf"
        s3.put_object(Bucket=KB_BUCKET, Key=original_key, Body=raw, ContentType="application/pdf")
    family = meta.get("family") or (replaces and next((d["family"] for d in list_sources() if d["doc_id"] == replaces), None)) or doc_id
    for i, sec in enumerate(sections, 1):
        base = f"kb/{meta['source_type']}/{doc_id}__{i:02d}-{slug(sec['title'])[:40]}.md"
        s3.put_object(Bucket=KB_BUCKET, Key=base, Body=f"# {meta['title']}: {sec['title']}\n\n{sec['text']}\n".encode(),
                      ContentType="text/markdown")
        attrs = {"doc_id": doc_id, "title": meta["title"], "section": sec["title"][:200], "source_type": meta["source_type"],
                 "year": int(meta.get("year") or datetime.now().year), "publisher": meta.get("publisher") or "ASPPH",
                 "status": "active", "family": family,
                 "original": f"{original_key}#page=1" if original_key else meta.get("url", ""),
                 **{k: meta[k] for k in ("area", "competencies", "aias_level") if meta.get(k) not in (None, "", [])}}
        # Bedrock rejects the WHOLE file for an empty metadata value (a source with no PDF or link had
        # original="" and silently wasn't indexed, Nov 4), so empty values are left out.
        attrs = {k: v for k, v in attrs.items() if v not in ("", None)}
        s3.put_object(Bucket=KB_BUCKET, Key=base + ".metadata.json", Body=json.dumps({"metadataAttributes": attrs}, indent=2).encode(),
                      ContentType="application/json")
    demoted = None
    if replaces:
        old = next((d for d in list_sources() if d["doc_id"] == replaces), None)
        if old:
            _rewrite_status(old, old_status if old_status in ("secondary", "retired") else "secondary")
            demoted = {"doc_id": replaces, "status": old_status}
    result = sync()
    ok = result["status"] == "COMPLETE" and found_by_search(doc_id, sections[0]["text"][:600])
    if not ok and result["status"] != "COMPLETE":
        result["hint"] = "Bedrock rejected some files; see failures. The document is NOT searchable yet."
    userdata.table().put_item(Item={"PK": f"SOURCE#{doc_id}", "SK": "META", "title": meta["title"],
                                    "source_type": meta["source_type"], "year": int(meta.get("year") or 0), "family": family,
                                    "status": "active", "published_by": actor.get("email", ""), "published_at": _now()})
    audit(actor, "publish", doc_id, f"{meta['title']} · {len(sections)} sections · {meta['source_type']}"
          + (f" · replaces {replaces} ({demoted['status']})" if demoted else "") + ("" if ok else " · SEARCH TEST FAILED"))
    return {"doc_id": doc_id, "sections": len(sections), "sync": result, "search_test_passed": ok, "demoted": demoted}


def set_status(actor: dict, doc_id: str, status: str) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    doc = next((d for d in list_sources() if d["doc_id"] == doc_id), None)
    if not doc:
        raise KeyError(doc_id)
    before = doc["status"]
    _rewrite_status(doc, status)
    result = sync()
    audit(actor, "status", doc_id, f"{before} → {status}")
    return {"doc_id": doc_id, "from": before, "to": status, "sync": result}


# ---------- example syllabi shared by professors (Phase 11) ----------
TAG = re.compile(r"\[(NAME|EMAIL|PHONE|ADDRESS|USERNAME)_\d+\]")


def anonymize(text: str) -> str:
    """Submissions arrive already scrubbed ([NAME_1]…); published examples say [instructor], [email], …"""
    return TAG.sub(lambda m: {"NAME": "[instructor]", "EMAIL": "[email]", "PHONE": "[phone]"}.get(m.group(1), "[removed]"), text)


def submit(owner: dict, payload: dict) -> dict:
    if not payload.get("consent"):
        raise ValueError("consent is required")
    sid = secrets.token_hex(6)
    us3 = boto3.client("s3", region_name=REGION)
    us3.put_object(Bucket=userdata.BUCKET, Key=f"submissions/{sid}.json", Body=json.dumps(payload).encode())
    item = {"PK": f"SUBMISSION#{sid}", "SK": "META", "id": sid, "owner_sub": owner["sub"], "owner_email": owner.get("email", ""),
            "course_code": payload.get("course", {}).get("code", ""), "title": payload.get("title", "")[:200],
            "status": "pending", "consent_at": _now(), "summary": json.dumps(payload.get("summary", {}))[:3000]}
    userdata.table().put_item(Item=item)
    userdata.log_event(owner["sub"], "submit", item["course_code"], "shared as an example syllabus")
    return {"id": sid, "status": "pending"}


def _sub_item(sid: str) -> dict:
    it = userdata.table().get_item(Key={"PK": f"SUBMISSION#{sid}", "SK": "META"}).get("Item")
    if not it:
        raise KeyError(sid)
    return userdata._plain(it)


def list_submissions(owner_sub: str | None = None, status: str | None = None) -> list[dict]:
    from boto3.dynamodb.conditions import Attr
    flt = Attr("PK").begins_with("SUBMISSION#")
    if owner_sub:
        flt = flt & Attr("owner_sub").eq(owner_sub)
    if status:
        flt = flt & Attr("status").eq(status)
    items, kw = [], {"FilterExpression": flt}
    while True:  # small table for the demo; production: a GSI on status
        r = userdata.table().scan(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    out = [{k: v for k, v in userdata._plain(i).items() if k not in ("PK", "SK")} for i in items]
    for o in out:
        o["summary"] = json.loads(o.get("summary") or "{}")
    return sorted(out, key=lambda o: o.get("consent_at", ""), reverse=True)


def get_submission(sid: str) -> dict:
    it = _sub_item(sid)
    body = json.loads(boto3.client("s3", region_name=REGION).get_object(Bucket=userdata.BUCKET, Key=f"submissions/{sid}.json")["Body"].read())
    return {**{k: v for k, v in it.items() if k not in ("PK", "SK")}, "summary": json.loads(it.get("summary") or "{}"), "content": body}


def _set(sid: str, **fields) -> None:
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    userdata.table().update_item(Key={"PK": f"SUBMISSION#{sid}", "SK": "META"},
                                 UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
                                 ExpressionAttributeNames=names, ExpressionAttributeValues=userdata._ddb(values))


def approve(actor: dict, sid: str, section_ids: list[str], tags: dict) -> dict:
    sub_ = get_submission(sid)
    if sub_["status"] not in ("pending", "returned"):
        raise ValueError(f"submission is {sub_['status']}")
    secs = {x["id"]: x for x in sub_["content"].get("sections", [])}
    chosen = [{"title": secs[i]["title"], "text": anonymize(secs[i]["text"])} for i in section_ids if i in secs]
    if not chosen:
        raise ValueError("choose at least one section")
    title = tags.get("title") or f"Example syllabus: {sub_['content'].get('course', {}).get('name', sub_['course_code'])}"
    meta = {"title": title, "source_type": "exemplar", "year": datetime.now().year, "publisher": "Shared by a PHACT professor (consented)",
            "area": tags.get("area", ""), "competencies": [str(c) for c in tags.get("competencies", [])]}
    r = publish(actor, None, meta, chosen)
    _set(sid, status="approved", reviewer=actor.get("email", ""), reviewed_at=_now(), published_doc_ids=[r["doc_id"]])
    audit(actor, "approve_example", sid, f"{title} · {len(chosen)} sections → {r['doc_id']}")
    userdata.log_event(sub_["owner_sub"], "example_approved", sub_["course_code"], title)
    return {**r, "submission": sid}


def return_submission(actor: dict, sid: str, note: str) -> dict:
    _sub_item(sid)
    _set(sid, status="returned", reviewer=actor.get("email", ""), reviewed_at=_now(), review_note=note[:500])
    audit(actor, "return_example", sid, note[:120])
    return {"id": sid, "status": "returned"}


def withdraw(owner: dict, sid: str) -> dict:
    it = _sub_item(sid)
    if it["owner_sub"] != owner["sub"]:
        raise PermissionError("not your submission")
    for doc_id in it.get("published_doc_ids", []) or []:
        doc = next((d for d in list_sources() if d["doc_id"] == doc_id), None)
        if doc:
            _rewrite_status(doc, "retired")
    if it.get("published_doc_ids"):
        sync()
    _set(sid, status="withdrawn", withdrawn_at=_now())
    audit(owner, "withdraw_example", sid, "by the professor")
    return {"id": sid, "status": "withdrawn"}
