"""The AI-policy library: ready-made university AI policies a university admin can adopt.

- ASPPH's suggested policies are stored in the database (seeded once from DEFAULTS below).
- A university admin can share their own policy; it goes to ASPPH review first and is added to the library
  only after an ASPPH admin approves it (like example syllabi).
- A university admin can upload their policy document; Claude (Haiku) turns it into a clear list of rules.

DynamoDB (table phact-app):
  POLICY#<id>     META   name, publisher, max_ai_level, rules, source, created_at        (the library)
  POLICYSUB#<id>  META   uni_id, uni_name, by, name, max_ai_level, rules, status, ...    (shares awaiting review)
"""

import re
import secrets
import sys
from pathlib import Path

from boto3.dynamodb.conditions import Attr
from pydantic import BaseModel, Field

import universities
import userdata

LEVELS = universities.LEVELS
_BASE = ("Based on ASPPH's AI Framework (2026), Teaching and Learning recommendations. "
         "A starting draft for ASPPH to confirm or replace.")
DEFAULTS = [
    {"id": "aspph-guided", "name": "ASPPH suggested: Guided", "max_ai_level": "guided", "rules": [
        {"id": "ASPPH-AI-1", "text": "Every syllabus states the course's AI-use level and what it allows."},
        {"id": "ASPPH-AI-2", "text": "Students disclose any AI use, naming the tool and what it was used for."},
        {"id": "ASPPH-AI-3", "text": "Students critically reflect on AI output and its limitations."},
        {"id": "ASPPH-AI-4", "text": "Only AI tools reviewed for safety, transparency, privacy and equity are used in the course."},
        {"id": "ASPPH-AI-5", "text": "No personal, patient or confidential data is entered into AI tools."},
        {"id": "ASPPH-AI-6", "text": "Graded work keeps an independent, human-centered component alongside any AI use."}]},
    {"id": "aspph-integrated", "name": "ASPPH suggested: Integrated", "max_ai_level": "integrated", "rules": [
        {"id": "ASPPH-AI-1", "text": "Every syllabus states the course's AI-use level and what it allows."},
        {"id": "ASPPH-AI-2", "text": "Students disclose any AI use, naming the tool and what it was used for."},
        {"id": "ASPPH-AI-3", "text": "Students critically reflect on AI output and its limitations."},
        {"id": "ASPPH-AI-7", "text": "Courses build AI literacy, including prompting and checking AI output against evidence."},
        {"id": "ASPPH-AI-5", "text": "No personal, patient or confidential data is entered into AI tools."},
        {"id": "ASPPH-AI-8", "text": "Faculty teach only the AI skills they are prepared to teach and assess."}]},
    {"id": "aspph-none", "name": "ASPPH suggested: None", "max_ai_level": "none", "rules": [
        {"id": "ASPPH-AI-1", "text": "Every syllabus states the course's AI-use level and what it allows."},
        {"id": "ASPPH-AI-9", "text": "Students don't use AI tools for graded work."},
        {"id": "ASPPH-AI-10", "text": "Courses teach about AI's risks, limits and ethics, without requiring its use."}]},
]


def _t():
    return userdata.table()


def _plain(it: dict) -> dict:
    return {k: v for k, v in userdata._plain(it).items() if k not in ("PK", "SK")}


def clean(p: dict) -> dict:
    """A policy as the library stores it: a name, a highest AI level, and a list of rules."""
    pol = universities.clean_policy(p)
    return {"name": str(p.get("name") or "").strip()[:120], "max_ai_level": pol["max_ai_level"], "rules": pol["rules"]}


# ---------- the library ----------
def ensure_defaults() -> None:
    for d in DEFAULTS:
        try:
            _t().put_item(Item={"PK": f"POLICY#{d['id']}", "SK": "META", **d, "publisher": "ASPPH", "source": _BASE,
                                "created_at": userdata.now()}, ConditionExpression="attribute_not_exists(PK)")
        except _t().meta.client.exceptions.ConditionalCheckFailedException:
            pass


def list_library() -> list[dict]:
    def scan():
        items, kw = [], {"FilterExpression": Attr("PK").begins_with("POLICY#") & Attr("SK").eq("META")}
        while True:
            r = _t().scan(**kw)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                return items
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    items = scan()
    if not any(i.get("publisher") == "ASPPH" for i in items):
        ensure_defaults()
        items = scan()
    out = [_plain(i) for i in items]
    return sorted(out, key=lambda p: (p.get("publisher") != "ASPPH", p.get("name", "").lower()))


def get(pid: str) -> dict | None:
    it = _t().get_item(Key={"PK": f"POLICY#{pid}", "SK": "META"}).get("Item")
    return _plain(it) if it else None


# ---------- sharing: university → ASPPH review → library ----------
def share(uid: str, user: dict, policy: dict) -> dict:
    p = clean(policy)
    if not p["rules"]:
        raise ValueError("Add at least one rule before sharing.")
    uni = universities.get(uid) or {}
    sid = secrets.token_hex(5)
    item = {"PK": f"POLICYSUB#{sid}", "SK": "META", "id": sid, "uni_id": uid, "uni_name": uni.get("name", uid),
            "by": user.get("email", ""), "by_sub": user.get("sub", ""), **p, "name": p["name"] or f"{uni.get('name', uid)} AI policy",
            "status": "pending", "submitted_at": userdata.now()}
    _t().put_item(Item=userdata._ddb(item))
    userdata.log_event(user["sub"], "policy_share", uid, item["name"])
    return _plain(item)


def list_shares(uid: str | None = None, status: str | None = None) -> list[dict]:
    flt = Attr("PK").begins_with("POLICYSUB#")
    if uid:
        flt = flt & Attr("uni_id").eq(uid)
    if status:
        flt = flt & Attr("status").eq(status)
    items, kw = [], {"FilterExpression": flt}
    while True:
        r = _t().scan(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return sorted((_plain(i) for i in items), key=lambda s: s.get("submitted_at", ""), reverse=True)


def _share(sid: str) -> dict:
    it = _t().get_item(Key={"PK": f"POLICYSUB#{sid}", "SK": "META"}).get("Item")
    if not it:
        raise KeyError(sid)
    return _plain(it)


def _set(sid: str, **fields) -> None:
    _t().update_item(Key={"PK": f"POLICYSUB#{sid}", "SK": "META"},
                     UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
                     ExpressionAttributeNames={f"#{k}": k for k in fields},
                     ExpressionAttributeValues=userdata._ddb({f":{k}": v for k, v in fields.items()}))


def approve(actor: dict, sid: str) -> dict:
    s = _share(sid)
    if s["status"] != "pending":
        raise ValueError(f"This share is {s['status']}.")
    pid = f"shared-{sid}"
    _t().put_item(Item=userdata._ddb({"PK": f"POLICY#{pid}", "SK": "META", "id": pid, "name": s["name"], "max_ai_level": s["max_ai_level"],
                                      "rules": s["rules"], "publisher": s["uni_name"], "source": f"Shared by {s['uni_name']}, reviewed by ASPPH",
                                      "created_at": userdata.now()}))
    _set(sid, status="approved", reviewer=actor.get("email", ""), reviewed_at=userdata.now(), policy_id=pid)
    userdata.log_event(actor["sub"], "policy_approve", s["uni_id"], s["name"])
    return {"id": sid, "status": "approved", "policy_id": pid}


def return_share(actor: dict, sid: str, note: str) -> dict:
    s = _share(sid)
    if s["status"] != "pending":
        raise ValueError(f"This share is {s['status']}.")
    _set(sid, status="returned", reviewer=actor.get("email", ""), reviewed_at=userdata.now(), review_note=note.strip()[:500])
    userdata.log_event(actor["sub"], "policy_return", s["uni_id"], note[:120])
    return {"id": sid, "status": "returned"}


# ---------- a policy document → a clear list of rules (Claude Haiku) ----------
class _Rule(BaseModel):
    text: str = Field(description="One rule, one sentence, in plain language")


class _Extracted(BaseModel):
    max_ai_level: str = Field(description="none | assistive | guided | integrated: the MOST student AI use the document allows")
    rules: list[_Rule] = Field(description="The document's AI rules for courses, 1 to 12, most important first")


SYSTEM = """You turn a university's AI-use policy document into a short list of clear rules that a course-design assistant must follow.

AI levels (the most student AI use the policy allows anywhere):
- none: students may not use AI for coursework.
- assistive: AI only for planning and brainstorming, disclosed; the final work is the student's own.
- guided: AI for specific tasks with disclosure and critical reflection; AI does not author the final work.
- integrated: AI as a disclosed collaborator in selected assessments.

Rules:
- Only rules the document actually states or clearly implies about teaching, coursework, assessment or AI tools. Never invent rules.
- One sentence each, plain language, specific. Merge duplicates. Skip boilerplate, history and contact details.
- At most 12 rules, most important first. If the document has no AI rules, return an empty list and level "guided"."""


def extract_rules(text: str, uni_prefix: str = "UNI") -> dict:
    root = Path(__file__).resolve().parents[1] / "agent"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import llm
    import safety
    clean_text = safety.scrub_pii(text[:24000])[0]  # names and contacts never reach Claude
    out, stats = llm.call(station="policy_rules", tier="fast", system=SYSTEM, user=f"<policy_document>\n{clean_text}\n</policy_document>",
                          schema=_Extracted, effort="low", max_tokens=3000, think=False)
    level = out.max_ai_level if out.max_ai_level in LEVELS else "guided"
    prefix = re.sub(r"[^A-Z0-9]", "", uni_prefix.upper())[:6] or "UNI"
    rules = [{"id": f"{prefix}-AI-{i + 1}", "text": r.text.strip()} for i, r in enumerate(out.rules[:12]) if r.text.strip()]
    return {"max_ai_level": level, "rules": rules, "stats": [stats.__dict__]}
