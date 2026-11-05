"""The university layer: universities, their AI policy, invite codes, members, and a per-university course index.

Hierarchy: ASPPH admin (all universities) > university admin (one university) > professor (own courses).
A user's university is the Cognito attribute custom:university_id. Users can't write it; the server sets it only
after a valid invite code. Every university-scoped query starts from the CALLER's verified university id,
so one university can never read another's professors or courses.

DynamoDB items (table phact-app, single-table design, no new indexes needed):
  UNI#<id>      META               name, policy, created_at
  UNI#<id>      MEMBER#<sub>       email, name, role, joined_at
  UNI#<id>      COURSE#<sub>#<c>   course summary for the admin's list (written whenever the professor saves)
  UNI#<id>      INVITE#<code>      the university's view of an invite (for listing)
  INVITE#<code> META               uni_id, role, expires_at, uses, max_uses, revoked (what sign-up checks)
"""

import re
import secrets
import time

from boto3.dynamodb.conditions import Key

import userdata

STANCES = ("ban", "restricted", "open")  # strictest first
# The four AI levels the professor app uses (strictest first) and the stance each one maps to for the AI's context
LEVELS = ("none", "assistive", "guided", "integrated")
LEVEL_STANCE = {"none": "ban", "assistive": "restricted", "guided": "restricted", "integrated": "open"}
STANCE_LEVEL = {"ban": "none", "restricted": "guided", "open": "integrated"}  # policies saved before levels existed
LEVEL_NAME = {"none": "None", "assistive": "Assistive", "guided": "Guided", "integrated": "Integrated"}
# The 22 CEPH MPH foundational competencies, in five words or fewer (the full statements are in the checklist)
CEPH_SHORT = {1: "Apply epidemiological methods", 2: "Select data collection methods", 3: "Analyze data with biostatistics",
              4: "Interpret data analysis results", 5: "Compare health systems", 6: "Structural bias and health inequities",
              7: "Assess community needs and assets", 8: "Apply cultural awareness", 9: "Design population-based interventions",
              10: "Budget and resource management", 11: "Select program evaluation methods", 12: "Explain policy-making process",
              13: "Build coalitions and partnerships", 14: "Advocate for health policies", 15: "Evaluate policy equity impact",
              16: "Apply leadership principles", 17: "Negotiation and mediation skills", 18: "Select communication strategies",
              19: "Communicate to diverse audiences", 20: "Cultural humility in communication", 21: "Integrate cross-sector perspectives",
              22: "Apply systems thinking tools"}
# US Census regions, so ASPPH can group its member schools geographically
REGIONS = {"Northeast": ["CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"],
           "Midwest": ["IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"],
           "South": ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS", "TN", "AR", "LA", "OK", "TX", "PR"],
           "West": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"]}
STATE_REGION = {st: r for r, sts in REGIONS.items() for st in sts}
ROLES_BY_INVITE = ("faculty", "school-admin")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def _t():
    return userdata.table()


def _slug(name: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "uni") + "-" + secrets.token_hex(2)


# ---------- universities and policy ----------
def region_of(state: str) -> str:
    return STATE_REGION.get((state or "").strip().upper(), "Outside the US" if state else "Not set")


def create(name: str, uni_id: str | None = None, city: str = "", state: str = "") -> dict:
    uid = uni_id or _slug(name)
    st = (state or "").strip().upper()[:2]
    item = {"PK": f"UNI#{uid}", "SK": "META", "id": uid, "name": name.strip()[:120], "created_at": userdata.now(),
            "city": city.strip()[:60], "state": st, "region": region_of(st),
            "policy": {"max_ai_level": "integrated", "max_ai_stance": "open", "rules": []}}
    _t().put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    return userdata._plain(item)


def set_location(uid: str, city: str, state: str) -> None:
    st = (state or "").strip().upper()[:2]
    _t().update_item(Key={"PK": f"UNI#{uid}", "SK": "META"}, UpdateExpression="SET city = :c, #s = :s, #r = :r",
                     ExpressionAttributeNames={"#s": "state", "#r": "region"}, ConditionExpression="attribute_exists(PK)",
                     ExpressionAttributeValues={":c": city.strip()[:60], ":s": st, ":r": region_of(st)})


def directory() -> list[dict]:
    """ASPPH's view of every member university in ONE paginated scan (not one query per university):
    location, policy, and counts of professors, admins, courses, analyzed and exported courses."""
    unis: dict[str, dict] = {}
    kw = {"FilterExpression": "begins_with(PK, :u)", "ExpressionAttributeValues": {":u": "UNI#"}}
    while True:
        page = _t().scan(**kw)
        for it in page["Items"]:
            uid = it["PK"][4:]
            u = unis.setdefault(uid, {"id": uid, "professors": 0, "admins": 0, "courses": 0, "analyzed": 0, "exported": 0, "last_activity": ""})
            sk = it["SK"]
            if sk == "META":
                u.update({k: userdata._plain(it.get(k)) for k in ("name", "city", "state", "region", "created_at")})
                u["max_ai_stance"] = (it.get("policy") or {}).get("max_ai_stance", "open")
                u["max_ai_level"] = level_of(it.get("policy"))
                u["rules"] = len((it.get("policy") or {}).get("rules") or [])
            elif sk.startswith("MEMBER#"):
                u["admins" if it.get("role") == "school-admin" else "professors"] += 1
            elif sk.startswith("COURSE#"):
                u["courses"] += 1
                u["analyzed"] += 1 if (it.get("summary") or {}).get("changes") else 0
                u["exported"] += 1 if (it.get("course") or {}).get("exportedAt") else 0
                u["last_activity"] = max(u["last_activity"], it.get("updated_at", ""))
        if "LastEvaluatedKey" not in page:
            break
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    out = [u for u in unis.values() if u.get("name")]
    for u in out:
        u.setdefault("region", region_of(u.get("state", "")))
    return sorted(out, key=lambda u: u["name"].lower())


def get(uid: str | None) -> dict | None:
    if not uid:
        return None
    it = _t().get_item(Key={"PK": f"UNI#{uid}", "SK": "META"}).get("Item")
    return userdata._plain(it) if it else None


def list_all() -> list[dict]:
    items = _t().scan(FilterExpression="SK = :m AND begins_with(PK, :u)", ExpressionAttributeValues={":m": "META", ":u": "UNI#"})["Items"]
    return sorted((userdata._plain(i) for i in items), key=lambda u: u["name"])


def level_of(policy: dict | None) -> str:
    """A policy's highest AI level (older policies only stored a stance)."""
    p = policy or {}
    return p["max_ai_level"] if p.get("max_ai_level") in LEVELS else STANCE_LEVEL.get(p.get("max_ai_stance"), "integrated")


def clean_policy(p: dict) -> dict:
    level = level_of(p)
    rules = []
    for i, r in enumerate((p.get("rules") or [])[:20]):
        text = str(r.get("text", "")).strip()[:600]
        if text:
            rid = re.sub(r"[^A-Za-z0-9-]", "", str(r.get("id") or f"UNI-AI-{i + 1}"))[:20] or f"UNI-AI-{i + 1}"
            rules.append({"id": rid, "text": text})
    out = {"max_ai_level": level, "max_ai_stance": LEVEL_STANCE[level], "rules": rules}
    if p.get("adopted_from"):
        out["adopted_from"] = str(p["adopted_from"])[:60]
    return out


def set_policy(uid: str, policy: dict, by: str) -> dict:
    pol = {**clean_policy(policy), "updated_by": by, "updated_at": userdata.now()}
    _t().update_item(Key={"PK": f"UNI#{uid}", "SK": "META"}, UpdateExpression="SET policy = :p",
                     ConditionExpression="attribute_exists(PK)", ExpressionAttributeValues={":p": pol})
    return pol


def cap_stance(professor: str | None, university_max: str | None) -> str:
    """University policy goes above the professor: the stricter of the two wins."""
    p = professor if professor in STANCES else "restricted"
    u = university_max if university_max in STANCES else "open"
    return STANCES[min(STANCES.index(p), STANCES.index(u))]


def cap_level(professor: str | None, university_max: str | None) -> str:
    p = professor if professor in LEVELS else "guided"
    u = university_max if university_max in LEVELS else "integrated"
    return LEVELS[min(LEVELS.index(p), LEVELS.index(u))]


# ---------- program view: how the university's courses cover the 22 CEPH competencies ----------
def course_coverage(progress: dict) -> dict[int, str]:
    """Each assigned competency's status for ONE course, judged by the syllabus only (not assessments):
    covered if the syllabus covers it or an accepted syllabus change closes it, else partial / missing."""
    dec = progress.get("decisions") or {}
    fixed = {int(c) for e in progress.get("edits") or [] if dec.get(e.get("edit_id")) == "accepted" for c in e.get("ceph") or [] if str(c).isdigit()}
    out = {}
    for c in progress.get("comps") or []:
        cid, st = c.get("id"), c.get("status")
        if not isinstance(cid, int) or st == "not_assigned":
            continue
        out[cid] = "covered" if st == "covered" or cid in fixed else ("partial" if st == "partial" else "missing")
    return out


def program_competencies(per_course: dict[str, dict[int, str]]) -> list[dict]:
    """per_course: {course code: {competency id: status}}. Color: green if at least 1 course fully covers it;
    yellow if none does but 2 or more cover it partially ("limited"); red otherwise."""
    rows = []
    for cid, short in CEPH_SHORT.items():
        full = sorted(code for code, m in per_course.items() if m.get(cid) == "covered")
        part = sorted(code for code, m in per_course.items() if m.get(cid) == "partial")
        color = "green" if full else "yellow" if len(part) >= 2 else "red"
        rows.append({"id": cid, "short": short, "fulfilled": len(full), "courses": full, "limited": part, "color": color})
    return rows


# ---------- invite codes ----------
def create_invite(uid: str, role: str, by: str, days: int = 14, max_uses: int = 50) -> dict:
    if role not in ROLES_BY_INVITE:
        raise ValueError("role must be faculty or school-admin")
    code = "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(2))  # e.g. K7QM-3XRT
    exp = int(time.time()) + days * 86400
    meta = {"uni_id": uid, "role": role, "expires_at": exp, "uses": 0, "max_uses": max_uses, "revoked": False,
            "created_by": by, "created_at": userdata.now()}
    _t().put_item(Item={"PK": f"INVITE#{code}", "SK": "META", **meta, "ttl": exp + 30 * 86400}, ConditionExpression="attribute_not_exists(PK)")
    _t().put_item(Item={"PK": f"UNI#{uid}", "SK": f"INVITE#{code}", "code": code, **meta})
    return {"code": code, **meta}


def list_invites(uid: str) -> list[dict]:
    items = _t().query(KeyConditionExpression=Key("PK").eq(f"UNI#{uid}") & Key("SK").begins_with("INVITE#"))["Items"]
    out = []
    for i in items:  # the live counters live on the INVITE# item
        live = _t().get_item(Key={"PK": f"INVITE#{i['code']}", "SK": "META"}).get("Item") or {}
        out.append(userdata._plain({**i, "uses": live.get("uses", i.get("uses", 0)), "revoked": live.get("revoked", i.get("revoked"))}))
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def revoke_invite(uid: str, code: str) -> None:
    _t().update_item(Key={"PK": f"INVITE#{code}", "SK": "META"}, UpdateExpression="SET revoked = :t",
                     ConditionExpression="uni_id = :u", ExpressionAttributeValues={":t": True, ":u": uid})
    _t().update_item(Key={"PK": f"UNI#{uid}", "SK": f"INVITE#{code}"}, UpdateExpression="SET revoked = :t", ExpressionAttributeValues={":t": True})


def check_invite(code: str) -> dict | None:
    """Look only (no use consumed): valid, unexpired, not revoked, not used up."""
    it = _t().get_item(Key={"PK": f"INVITE#{(code or '').strip().upper()}", "SK": "META"}).get("Item")
    if not it or it.get("revoked") or int(it["expires_at"]) < time.time() or int(it["uses"]) >= int(it["max_uses"]):
        return None
    return userdata._plain(it)


def redeem_invite(code: str) -> dict:
    """Consume one use, atomically (two sign-ups can't both take the last use)."""
    code = (code or "").strip().upper()
    r = _t().update_item(Key={"PK": f"INVITE#{code}", "SK": "META"}, UpdateExpression="SET uses = uses + :one",
                         ConditionExpression="revoked = :f AND uses < max_uses AND expires_at > :now",
                         ExpressionAttributeValues={":one": 1, ":f": False, ":now": int(time.time())}, ReturnValues="ALL_NEW")
    return userdata._plain(r["Attributes"])


# ---------- members and the course index ----------
def add_member(uid: str, sub: str, email: str, name: str, role: str) -> None:
    _t().put_item(Item={"PK": f"UNI#{uid}", "SK": f"MEMBER#{sub}", "sub": sub, "email": email, "name": name,
                        "role": role, "joined_at": userdata.now()})


def get_member(uid: str, sub: str) -> dict | None:
    it = _t().get_item(Key={"PK": f"UNI#{uid}", "SK": f"MEMBER#{sub}"}).get("Item")
    return userdata._plain(it) if it else None


def list_members(uid: str) -> list[dict]:
    items = _t().query(KeyConditionExpression=Key("PK").eq(f"UNI#{uid}") & Key("SK").begins_with("MEMBER#"))["Items"]
    return sorted((userdata._plain(i) for i in items), key=lambda m: (m["role"] != "school-admin", m["name"].lower()))


def index_course(uid: str, sub: str, professor: str, course: dict, summary: dict) -> None:
    code = userdata._code(course["code"])
    keep = {k: course.get(k) for k in ("code", "name", "term", "level", "format", "ai_stance", "ai_level", "department", "exportedAt") if course.get(k) is not None}
    _t().put_item(Item=userdata._ddb({"PK": f"UNI#{uid}", "SK": f"COURSE#{sub}#{code}", "prof_sub": sub, "professor": professor,
                                      "course": keep, "summary": summary or {}, "updated_at": userdata.now()}))


def unindex_course(uid: str, sub: str, code: str) -> None:
    _t().delete_item(Key={"PK": f"UNI#{uid}", "SK": f"COURSE#{sub}#{userdata._code(code)}"})


def list_courses(uid: str) -> list[dict]:
    items = _t().query(KeyConditionExpression=Key("PK").eq(f"UNI#{uid}") & Key("SK").begins_with("COURSE#"))["Items"]
    return sorted((userdata._plain(i) for i in items), key=lambda c: c.get("updated_at", ""), reverse=True)
