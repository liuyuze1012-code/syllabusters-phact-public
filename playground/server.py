"""PHACT Playground: a local test page for the REAL pipeline (real Claude, real knowledge base).

    cd playground && python server.py      →  http://localhost:8787

Not the product UI (that's frontend/). This is Gavin's workbench for experiencing the whole flow:
upload → read → map to CEPH → find sources → write edits → chat, and checking every citation.
Uses the AWS credentials in ~/.aws (the sandbox). Runs on this Mac only.
State lives in the browser; every request sends what it needs.
"""

import json
import sys
import time
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "agent" / "eval"), str(ROOT / "backend")]

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from phact_contracts.agent import ChatTurn, Context, Edit, Outline, Passage, SchoolRule  # noqa: E402

import llm  # noqa: E402
import retrieval  # noqa: E402
import safety  # noqa: E402
from app.services import export_docx  # noqa: E402
from pipeline.analyze import analyze_more, analyze_outline  # noqa: E402
from pipeline.assess import analyze_assessment  # noqa: E402
from steps import assess_structure, classify  # noqa: E402
from steps import chat, map_ceph, structure  # noqa: E402
from try_structure import extract  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import accounts  # noqa: E402
import agent_client  # noqa: E402  (the PHACT agent: in-process locally, on AgentCore on AWS)
import jobs  # noqa: E402
import universities  # noqa: E402
import userdata  # noqa: E402
from accounts import current_user  # noqa: E402

app = FastAPI(title="PHACT Playground")
# The professor's original upload and the PII map (tag -> real value) stay on THIS machine, never in the
# browser and never sent to Claude. Export uses them to edit the original file and put the real names back.
import os  # noqa: E402
UPLOADS = Path("/tmp/phact-uploads") if os.getenv("AWS_LAMBDA_FUNCTION_NAME") else Path(__file__).with_name(".uploads")
UPLOADS.mkdir(parents=True, exist_ok=True)  # on Lambda the code folder is read-only; uploads go to S3 there anyway


def _ok_id(doc_id: str | None) -> bool:
    return bool(doc_id) and doc_id.isalnum()  # ids we made ourselves: hex only


def file_get(user: dict, doc_id: str | None, suffix: str) -> bytes | None:
    """An uploaded file or name map. With accounts on: the user's own S3 folder (another user's id can't
    reach it, and nothing depends on the server's disk, so this works on Lambda). Off: this machine."""
    if not _ok_id(doc_id):
        return None
    if accounts.enabled():
        return userdata.get_upload(user["sub"], doc_id, suffix)
    f = UPLOADS / f"{doc_id}{suffix}"
    return f.read_bytes() if f.exists() else None


def file_put(user: dict, doc_id: str | None, suffix: str, data: bytes) -> None:
    if not _ok_id(doc_id):
        return
    if accounts.enabled():
        userdata.put_upload(user["sub"], doc_id, suffix, data)
    else:
        (UPLOADS / f"{doc_id}{suffix}").write_bytes(data)


def pii_get(user: dict, doc_id: str | None) -> dict:
    raw = file_get(user, doc_id, ".pii.json")
    return json.loads(raw) if raw else {}


@app.middleware("http")
async def require_login(request: Request, call_next):
    """With accounts on, every /api route except login/sign-up needs a valid session, so strangers can't
    run analyses on the public link. The page itself loads and shows the login screen."""
    path = request.url.path
    if accounts.enabled() and path.startswith("/api/") and not path.startswith("/api/auth/") and path != "/api/health" \
            and not accounts.request_user(request):
        return JSONResponse({"detail": "Please log in."}, status_code=401)
    return await call_next(request)
DEFAULT_POLICY = json.loads((ROOT / "knowledge-base/policies/phact_default.json").read_text())
STANCES = {
    "ban": "AI use is NOT allowed in this course. Prefer AI-resistant assessments and teaching ABOUT AI, not AI tools.",
    "restricted": "AI use is restricted: allowed only for brainstorming and editing, with disclosure.",
    "open": "AI use is open: collaborative AI use is welcome when disclosed and reflected on.",
}
FORMATS = {"in_person": "in person", "online_sync": "online, live (synchronous)",
           "online_async": "online, self-paced (asynchronous)", "hybrid": "hybrid"}


class CourseIn(BaseModel):
    """What the professor enters when creating a course. Becomes part of the AI's context."""
    code: str = ""
    name: str = ""
    level: str = "MPH"
    format: str = "in_person"
    size: int | None = None
    ai_stance: str = "restricted"
    ai_comfort: str = "beginner"
    notes: str = ""


def make_context(course: CourseIn, user: dict | None = None) -> Context:
    """The AI's context. A professor at a university gets the UNIVERSITY's AI rules, and their course AI stance is
    capped by the university's maximum (the stricter wins), enforced here on the server, not only in the page."""
    uni = universities.get((user or {}).get("university_id")) if (user or {}).get("university_id") else None
    pol = (uni or {}).get("policy") or {}
    if uni:
        course.ai_stance = universities.cap_stance(course.ai_stance, pol.get("max_ai_stance"))
    size = f"{course.size} students" if course.size else "class size not given"
    professor = (
        f"Course: {course.code} {course.name} ({course.level}); format: {FORMATS.get(course.format, course.format)}; {size}.\n"
        f"AI stance for this course: {STANCES.get(course.ai_stance, STANCES['restricted'])}\n"
        f"Professor's own comfort with AI: {course.ai_comfort}.\n"
        f"Professor's notes: {course.notes or 'none'}"
        + (f"\nUniversity policy ({uni['name']}), which overrides the professor: student AI use at most "
           f"'{universities.LEVEL_NAME[universities.level_of(pol)]}'." if uni else "")
    )
    if uni and pol.get("rules"):
        return Context(school_rules=[SchoolRule(**r) for r in pol["rules"]], policy_source="school", professor=professor)
    return Context(school_rules=[SchoolRule(**r) for r in DEFAULT_POLICY["rules"]], policy_source="phact_default",
                   professor=professor)


def stats_json(stats) -> list[dict]:
    return [s.__dict__ if hasattr(s, "__dict__") else s for s in stats]


def friendly(e: Exception) -> HTTPException:
    msg = str(e)
    if "ExpiredToken" in msg or "expired" in msg.lower():
        msg = "Your AWS sandbox credentials expired. Copy fresh ones from Workshop Studio, run the pbpaste line, then retry."
    return HTTPException(500, msg[:500])


@app.get("/")
def index():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/api/checklist")
def checklist():
    return [{"id": c["id"], "domain": c["domain"], "statement": c["statement"]} for c in map_ceph.CHECKLIST.values()]


@app.post("/api/extract")
async def api_extract(file: UploadFile = File(...), user: dict = Depends(current_user)):
    suffix = (Path(file.filename or "upload.txt").suffix or ".txt").lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, "Upload a PDF, Word (.docx) or text file.")
    doc_id = uuid.uuid4().hex
    data = await file.read()
    file_put(user, doc_id, suffix, data)
    with tempfile.TemporaryDirectory() as tmp:  # the readers need a file path; /tmp exists on Lambda too
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(data)
        text = extract(path)
    return {"filename": file.filename, "text": text, "lines": len(text.splitlines()), "doc_id": doc_id}


class StructureIn(BaseModel):
    text: str
    doc_id: str | None = None
    with_info: bool = False  # also read the course details + suggest competencies (step 1 of the professor flow)


@app.post("/api/structure")
def api_structure(body: StructureIn, user: dict = Depends(current_user)):
    """Safety gate first (US-8): personal data is scrubbed BEFORE the syllabus reaches Claude."""
    try:
        clean, pii, mapping = safety.scrub(body.text)
        file_put(user, body.doc_id, ".pii.json", json.dumps(mapping).encode())
        r = agent_client.call("structure", {"text": clean, "with_info": body.with_info})
    except Exception as e:
        raise friendly(e)
    return {"outline": r["outline"], "stats": r["stats"], "pii_removed": pii, "scrubbed_text": clean, "info": r.get("info") or {}}


@app.post("/api/agent/warm")
def api_agent_warm(user: dict = Depends(current_user)):
    """The page calls this when a professor opens step 2, so the AgentCore session is warm by the time they
    click "Run AI analysis" (a cold start measured ~5.5 s; a warm call ~0.2 s). Locally it's a no-op."""
    if agent_client.MODE != "agentcore":
        return {"ok": True, "mode": agent_client.MODE}
    token = accounts.JOB_USER.set(user)  # same session id the worker will use for this professor
    try:
        t = time.monotonic()
        agent_client.call("warm", {})
        return {"ok": True, "mode": "agentcore", "ms": int((time.monotonic() - t) * 1000)}
    except Exception as e:  # noqa: BLE001 — warming is best effort
        return {"ok": False, "error": str(e)[:200]}
    finally:
        accounts.JOB_USER.reset(token)


class AnalyzeIn(BaseModel):
    outline: dict
    confirmed: list[int]
    course: CourseIn
    memory: str = ""  # course memory: other documents, past decisions


@app.post("/api/analyze")
def api_analyze(body: AnalyzeIn, user: dict = Depends(current_user)):
    try:
        ctx = make_context(body.course, user)
        ctx.memory = body.memory[:2500]
        return agent_client.call("analyze", {"outline": body.outline, "confirmed": body.confirmed, "context": ctx.model_dump(),
                                             "ai_stance": body.course.ai_stance})
    except Exception as e:
        raise friendly(e)


# ---------- any upload: what kind of course document is it? ----------
class ClassifyIn(BaseModel):
    text: str


@app.post("/api/classify")
def api_classify(body: ClassifyIn):
    """Safety gate first (names never reach Claude), then a quick type detection + summary."""
    try:
        clean, _ = safety.scrub_pii(body.text[:8000])
        doc = agent_client.call("classify", {"text": clean})
    except Exception as e:
        raise friendly(e)
    if doc.get("looks_like_student_work"):
        raise HTTPException(422, "This looks like student work, which PHACT must not receive (student privacy). "
                                 "Upload the blank assignment, its rubric or an answer key instead.")
    return doc


# ---------- semester agent: assessments (homework, exams, projects, written assignments) ----------
class AssessStructureIn(BaseModel):
    text: str
    doc_id: str | None = None
    type_hint: str | None = None


@app.post("/api/assessment/structure")
def api_assessment_structure(body: AssessStructureIn, user: dict = Depends(current_user)):
    """Same Safety gate as the syllabus, then the assessment reader. Student work is refused (FERPA)."""
    try:
        clean, pii, mapping = safety.scrub(body.text)
        file_put(user, body.doc_id, ".pii.json", json.dumps(mapping).encode())
        r = agent_client.call("assessment_structure", {"text": clean, "type_hint": body.type_hint})
    except agent_client.AgentError as e:
        if e.kind != "student_work":
            raise friendly(e)
        raise HTTPException(422, f"This looks like student work, which PHACT must not receive (student privacy). {e} "
                                 "Upload the blank assignment, its rubric or an answer key instead.")
    except Exception as e:
        raise friendly(e)
    return {"outline": r["outline"], "meta": r["meta"], "stats": r["stats"], "pii_removed": pii}


class AssessAnalyzeIn(BaseModel):
    outline: dict
    meta: dict
    confirmed: list[int]
    course: CourseIn
    memory: str = ""   # the course memory: syllabus AI policy, competencies, past decisions


@app.post("/api/assessment/analyze")
def api_assessment_analyze(body: AssessAnalyzeIn, user: dict = Depends(current_user)):
    ctx = make_context(body.course, user)
    ctx.memory = body.memory[:2500]
    try:
        return agent_client.call("assessment_analyze", {"outline": body.outline, "meta": body.meta, "confirmed": body.confirmed,
                                                        "context": ctx.model_dump(), "ai_stance": body.course.ai_stance})
    except Exception as e:
        raise friendly(e)


class AnalyzeMoreIn(BaseModel):
    outline: dict
    new_ids: list[int]
    edits: list[dict]
    passages: list[dict]
    course: CourseIn


@app.post("/api/analyze_more")
def api_analyze_more(body: AnalyzeMoreIn, user: dict = Depends(current_user)):
    """Competencies added after the first analysis: only those are analyzed."""
    try:
        return agent_client.call("analyze_more", {"outline": body.outline, "new_ids": body.new_ids, "edits": body.edits,
                                                  "passages": body.passages, "context": make_context(body.course, user).model_dump(),
                                                  "ai_stance": body.course.ai_stance})
    except Exception as e:
        raise friendly(e)


class ChatIn(BaseModel):
    message: str
    history: list[ChatTurn] = []
    outline: dict
    edits: list[dict]
    passages: list[dict]
    course: CourseIn
    mode: str = "syllabus"
    memory: str = ""


@app.post("/api/chat")
def api_chat(body: ChatIn, user: dict = Depends(current_user)):
    try:
        clean, pii = safety.scrub_pii(body.message)
        allowed, refusal = safety.check_message(clean)
        if not allowed:  # US-8: off-topic or unsafe → friendly refusal, nothing reaches Claude
            return {"kind": "blocked", "reply": refusal, "edits": [], "removed_edit_ids": [], "new_passages": [],
                    "dropped": [], "searches": [], "stats": []}
        body.message = clean
        ctx = make_context(body.course, user)
        ctx.memory = body.memory[:2500]
        return agent_client.call("chat", {"message": body.message, "history": [t.model_dump() for t in body.history],
                                          "outline": body.outline, "edits": body.edits, "passages": body.passages,
                                          "context": ctx.model_dump(), "ai_stance": body.course.ai_stance, "mode": body.mode})
    except Exception as e:
        raise friendly(e)


class ExportIn(BaseModel):
    outline: dict
    edits: list[dict]
    course: CourseIn
    approvals: dict = {}
    doc_id: str | None = None
    review: bool = False  # False = clean final syllabus; True = highlighted review copy + sources appendix
    manual: dict = {}     # {section_id: text} hand edits from the Editor tab (already scrubbed)
    added: list = []      # [{after, title, text}] sections the professor added
    style: dict | None = None


@app.post("/api/export")
def api_export(body: ExportIn, user: dict = Depends(current_user)):
    """US-11: DOCX of ACCEPTED edits only, with a sources appendix. A Word upload is edited in place
    (its formatting kept); a PDF or pasted text is rebuilt. Either way the professor's real details come back."""
    pii_map = pii_get(user, body.doc_id)
    original = file_get(user, body.doc_id, ".docx")
    args = (body.outline, body.edits, body.course.model_dump(), body.approvals, pii_map, body.review,
            body.manual, body.added, body.style)
    try:
        data = export_docx.edit_original(original, *args) if original else export_docx.build(*args)
    except Exception as e:  # never lose the professor's work: fall back to the rebuilt document
        print(f"in-place export failed ({e}); rebuilding")
        data = export_docx.build(*args)
    name = f"{(body.course.code or 'syllabus').replace(' ', '')}-{'review-copy' if body.review else 'syllabus'}.docx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class ScrubIn(BaseModel):
    text: str
    doc_id: str | None = None


@app.post("/api/scrub")
def api_scrub(body: ScrubIn, user: dict = Depends(current_user)):
    """Hand edits pass the Safety gate too: anything personal the professor types is tagged before it can
    reach Claude in a later chat, and the doc's tag map grows so the download restores it."""
    existing = pii_get(user, body.doc_id)
    try:
        clean, counts, mapping = safety.scrub(body.text, existing)
    except Exception as e:
        raise friendly(e)
    file_put(user, body.doc_id, ".pii.json", json.dumps(mapping).encode())
    return {"text": clean, "pii_removed": counts}


# ---------- accounts (Phase 3) and the user's data (Phase 4) ----------
class SignupIn(BaseModel):
    email: str
    password: str
    name: str = ""
    invite_code: str = ""  # from a university admin (or ASPPH for a university admin account)


class LoginIn(BaseModel):
    email: str
    password: str


def _session_response(user: dict, request: Request) -> JSONResponse:
    public = {k: v for k, v in user.items() if not k.startswith("_")}
    if accounts.jwt_mode():  # API Gateway verifies this token on every call; the page sends it as a Bearer header
        return JSONResponse({**public, "id_token": user.get("_id_token"), "expires_in": user.get("_expires_in", 3600)})
    resp = JSONResponse(public)
    resp.set_cookie(accounts.COOKIE, accounts.make_token(public), max_age=accounts.TTL_S, httponly=True,
                    samesite="lax", secure=request.url.scheme == "https")
    return resp


@app.post("/api/auth/signup")
def api_signup(body: SignupIn, request: Request):
    inv = None
    if body.invite_code.strip():
        try:  # consume one use atomically first; give it back if the account can't be created
            inv = universities.redeem_invite(body.invite_code)
        except Exception:  # noqa: BLE001 — unknown, expired, revoked or used up: same answer, no hints
            raise HTTPException(400, "That invite code isn't valid. Ask your university admin for a new one.")
    try:
        user = accounts.signup(body.email, body.password, body.name, role=inv["role"] if inv else "faculty",
                               university_id=inv["uni_id"] if inv else "")
    except Exception:
        if inv:
            userdata.table().update_item(Key={"PK": f"INVITE#{body.invite_code.strip().upper()}", "SK": "META"},
                                         UpdateExpression="SET uses = uses - :one", ExpressionAttributeValues={":one": 1})
        raise
    if inv:
        universities.add_member(inv["uni_id"], user["sub"], user["email"], user["name"] or body.name, inv["role"])
    userdata.put_profile(user["sub"], email=user["email"], name=user["name"] or body.name, role=user["role"],
                         university_id=user.get("university_id", ""))
    userdata.log_event(user["sub"], "signup")
    return _session_response(user, request)


@app.post("/api/auth/login")
def api_login(body: LoginIn, request: Request):
    user = accounts.login(body.email, body.password)
    if not userdata.get_profile(user["sub"]):
        userdata.put_profile(user["sub"], email=user["email"], name=user["name"], role=user["role"])
    userdata.log_event(user["sub"], "login")
    return _session_response(user, request)


@app.post("/api/auth/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(accounts.COOKIE)
    return resp


@app.get("/api/auth/status")
def api_auth_status(request: Request):
    """Public: is login required here, and who is signed in (if anyone)."""
    user = accounts.request_user(request) if accounts.enabled() else accounts.LOCAL_USER
    return {"accounts": accounts.enabled(), "user": user, "auth_mode": accounts.jwt_mode() and "jwt" or "cookie",
            "jobs": jobs.mode() != "off"}


@app.get("/api/health")
def api_health():
    """Public, safe: no secrets, no data."""
    return {"ok": True, "service": "phact", "lambda": bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))}


# ---------- async jobs for calls that outlast API Gateway's ~30 s ----------
class JobIn(BaseModel):
    path: str
    body: dict | None = None
    file: dict | None = None   # {"name", "b64"} for uploads


@app.post("/api/jobs", status_code=202)
def api_create_job(body: JobIn, user: dict = Depends(current_user)):
    try:
        return {"job_id": jobs.create(user, body.path, body.body, body.file)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/jobs/{jid}")
def api_get_job(jid: str, user: dict = Depends(current_user)):
    try:
        return jobs.get(user, jid)
    except KeyError:
        raise HTTPException(404, "No such job.")


@app.get("/api/me")
def api_me(user: dict = Depends(current_user)):
    return user


class ProfileIn(BaseModel):
    prefs: dict = {}
    name: str | None = None


@app.get("/api/data/profile")
def api_get_profile(user: dict = Depends(current_user)):
    return userdata.get_profile(user["sub"]) or {"prefs": {}}


@app.put("/api/data/profile")
def api_put_profile(body: ProfileIn, user: dict = Depends(current_user)):
    p = userdata.put_profile(user["sub"], prefs=body.prefs, name=body.name)
    return {k: v for k, v in p.items() if k not in ("PK", "SK")}


@app.get("/api/data/courses")
def api_courses(user: dict = Depends(current_user)):
    return [{**c["course"], "summary": c.get("summary", {})} for c in userdata.list_courses(user["sub"])]


class CourseSaveIn(BaseModel):
    course: dict


@app.put("/api/data/courses/{code}")
def api_put_course(code: str, body: CourseSaveIn, user: dict = Depends(current_user)):
    if body.course.get("code") != code:
        raise HTTPException(400, "Course code mismatch.")
    item = userdata.put_course(user["sub"], body.course)
    _index(user, item["course"], item.get("summary", {}))
    return item["course"]


def _index(user: dict, course: dict, summary: dict) -> None:
    """A professor's course appears in their university's list (read-only for the university admin)."""
    if user.get("university_id"):
        universities.index_course(user["university_id"], user["sub"], user.get("name") or user.get("email", ""), course, summary)


@app.delete("/api/data/courses/{code}")
def api_delete_course(code: str, user: dict = Depends(current_user)):
    userdata.delete_course(user["sub"], code)
    if user.get("university_id"):
        universities.unindex_course(user["university_id"], user["sub"], code)
    userdata.log_event(user["sub"], "delete_course", code)
    return {"ok": True}


@app.get("/api/data/progress/{code}")
def api_get_progress(code: str, user: dict = Depends(current_user)):
    return userdata.get_progress(user["sub"], code) or {}


@app.put("/api/data/progress/{code}")
async def api_put_progress(code: str, request: Request, user: dict = Depends(current_user)):
    progress = await request.json()
    userdata.put_progress(user["sub"], code, progress)
    course = next((c["course"] for c in userdata.list_courses(user["sub"]) if c["course"]["code"] == code), {"code": code})
    item = userdata.put_course(user["sub"], course, {**userdata.progress_summary(progress), **_coverage(progress)})
    _index(user, course, item.get("summary", {}))
    return {"ok": True}


def _coverage(progress: dict) -> dict:
    """A competency counts as covered if the syllabus already covered it OR an accepted change closes it."""
    comps = [c for c in progress.get("comps") or [] if c.get("status") != "not_assigned"]
    dec = progress.get("decisions") or {}
    fixed = {cid for e in progress.get("edits") or [] if dec.get(e.get("edit_id")) == "accepted" for cid in e.get("ceph") or []}
    return {"competencies": len(comps), "covered": sum(c.get("status") == "covered" or c.get("id") in fixed for c in comps)}


class EventIn(BaseModel):
    type: str
    course: str = ""
    detail: str = ""


@app.get("/api/data/events")
def api_events(limit: int = 50, user: dict = Depends(current_user)):
    return userdata.list_events(user["sub"], min(limit, 200))


@app.post("/api/data/events")
def api_add_event(body: EventIn, user: dict = Depends(current_user)):
    userdata.log_event(user["sub"], body.type, body.course, body.detail)
    return {"ok": True}


# ---------- the university layer: a professor's university, and the university admin's portal ----------
@app.get("/api/data/university")
def api_my_university(user: dict = Depends(current_user)):
    """The professor's university and its AI policy (the page caps the AI-level choices with it)."""
    uni = universities.get(user.get("university_id"))
    return {"id": uni["id"], "name": uni["name"], "policy": uni.get("policy", {})} if uni else None


def _uni(user: dict, uni: str | None = None) -> str:
    """The university this caller may manage: ONLY a university admin, and ONLY their own university (from the
    verified token; a `uni` parameter is ignored). ASPPH admins run the knowledge base and never see a
    university's professors, courses or policy (Nov 4 decision); professors get 403 too."""
    if user.get("role") != "school-admin":
        raise HTTPException(403, "Only a university admin can open the university portal.")
    uid = user.get("university_id")
    if not uid or not universities.get(uid):
        raise HTTPException(403, "This account isn't linked to a university.")
    return uid


@app.get("/api/uni")
def api_uni(uni: str | None = None, user: dict = Depends(current_user)):
    uid = _uni(user, uni)
    u, members, courses = universities.get(uid), universities.list_members(uid), universities.list_courses(uid)
    return {"id": uid, "name": u["name"], "policy": u.get("policy", {}), "created_at": u.get("created_at"),
            "counts": {"professors": sum(m["role"] == "faculty" for m in members), "admins": sum(m["role"] == "school-admin" for m in members),
                       "courses": len(courses), "analyzed": sum(1 for c in courses if (c.get("summary") or {}).get("changes")),
                       "exported": sum(1 for c in courses if (c.get("course") or {}).get("exportedAt"))}}


class PolicyIn(BaseModel):
    max_ai_level: str = ""
    max_ai_stance: str = ""  # older pages
    rules: list[dict] = []
    adopted_from: str = ""
    name: str = ""


@app.put("/api/uni/policy")
def api_uni_policy(body: PolicyIn, uni: str | None = None, user: dict = Depends(current_user)):
    uid = _uni(user, uni)
    pol = universities.set_policy(uid, body.model_dump(), user.get("email", ""))
    userdata.log_event(user["sub"], "uni_policy", uid, f"max AI {pol['max_ai_level']}, {len(pol['rules'])} rules")
    return pol


@app.get("/api/uni/policy/library")
def api_uni_policy_library(user: dict = Depends(current_user)):
    """ASPPH's suggested policies plus university policies ASPPH approved, and this university's own shares."""
    uid = _uni(user)
    return {"library": policies.list_library(), "my_shares": policies.list_shares(uid=uid)}


@app.post("/api/uni/policy/extract")
async def api_uni_policy_extract(file: UploadFile = File(...), user: dict = Depends(current_user)):
    """A policy document → a clear list of rules (Claude Haiku, after the PII scrub). Nothing is saved until the admin saves."""
    uid = _uni(user)
    suffix = (Path(file.filename or "policy.txt").suffix or ".txt").lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, "Upload a PDF, Word or text file.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"policy{suffix}"
        path.write_bytes(await file.read())
        text = extract(path)
    if len(text.split()) < 20:
        raise HTTPException(400, "Couldn't read enough text from that file.")
    try:
        out = policies.extract_rules(text, (universities.get(uid) or {}).get("name", "UNI").split()[0])
    except Exception as e:
        raise friendly(e)
    userdata.log_event(user["sub"], "uni_policy_extract", uid, f"{len(out['rules'])} rules from {file.filename}")
    return out


@app.post("/api/uni/policy/share")
def api_uni_policy_share(body: PolicyIn, user: dict = Depends(current_user)):
    uid = _uni(user)
    try:
        return policies.share(uid, user, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/uni/competencies")
def api_uni_competencies(user: dict = Depends(current_user)):
    """The program view: for each of the 22 CEPH competencies, how many of this university's courses fulfill it,
    judged by each course's syllabus analysis (not its assessments)."""
    from concurrent.futures import ThreadPoolExecutor
    uid = _uni(user)
    courses = universities.list_courses(uid)

    def one(c):
        code = (c.get("course") or {}).get("code") or ""
        return code, universities.course_coverage(userdata.get_progress(c["prof_sub"], code) or {})
    with ThreadPoolExecutor(8) as ex:
        per = dict(ex.map(one, courses)) if courses else {}
    return {"courses": len(courses), "analyzed": sum(1 for m in per.values() if m), "rows": universities.program_competencies(per)}


@app.get("/api/uni/professors")
def api_uni_professors(uni: str | None = None, user: dict = Depends(current_user)):
    uid = _uni(user, uni)
    courses = universities.list_courses(uid)
    return [{**m, "courses": sum(1 for c in courses if c["prof_sub"] == m["sub"])} for m in universities.list_members(uid)]


@app.get("/api/uni/courses")
def api_uni_courses(uni: str | None = None, user: dict = Depends(current_user)):
    uid = _uni(user, uni)
    return [{k: c.get(k) for k in ("prof_sub", "professor", "course", "summary", "updated_at")} for c in universities.list_courses(uid)]


@app.get("/api/uni/courses/{sub}/{code}")
def api_uni_course(sub: str, code: str, uni: str | None = None, user: dict = Depends(current_user)):
    """Read-only view of one professor's course. The professor must be a member of the CALLER's university;
    otherwise it looks exactly like a course that doesn't exist."""
    uid = _uni(user, uni)
    if not universities.get_member(uid, sub):
        raise HTTPException(404, "No such course.")
    pr = userdata.get_progress(sub, code)
    if not pr:
        raise HTTPException(404, "No such course.")
    dec = pr.get("decisions") or {}
    outline = pr.get("outline") or {}
    return {"ai_policy": outline.get("ai_policy"), "sections": [x.get("title") for x in outline.get("sections") or []],
            "competencies": [{k: c.get(k) for k in ("id", "status", "reason")} for c in pr.get("comps") or [] if c.get("status") != "not_assigned"],
            "edits": [{"id": e.get("edit_id"), "section": e.get("section_id"), "proposed": (e.get("proposed") or "")[:400], "aias_level": e.get("aias_level"),
                       "supervisor": e.get("supervisor"), "decision": dec.get(e.get("edit_id")) or "not decided", "ceph": e.get("ceph")} for e in pr.get("edits") or []],
            "assessments": [{"title": m.get("title"), "type": m.get("type"), "changes": len(m.get("edits") or []),
                             "accepted": sum(1 for v in (m.get("decisions") or {}).values() if v == "accepted")} for m in (pr.get("materials") or {}).values()]}


class InviteIn(BaseModel):
    role: str = "faculty"
    days: int = 14
    max_uses: int = 50


# ---------- ASPPH admin: every member university (the organization's view; separate from the university portal) ----------
class UniversityIn(BaseModel):
    name: str
    city: str = ""
    state: str = ""


def _aspph(user: dict = Depends(current_user)) -> dict:
    """ASPPH staff only: the whole organization. University admins and professors get 403."""
    accounts.require_role(user, "aspph-admin")
    return user


@app.get("/api/admin/universities")
def api_admin_universities(user: dict = Depends(_aspph)):
    return universities.directory()


@app.post("/api/admin/universities")
def api_admin_create_university(body: UniversityIn, user: dict = Depends(_aspph)):
    if len(body.name.strip()) < 3:
        raise HTTPException(400, "Give the university a name.")
    u = universities.create(body.name, city=body.city, state=body.state)
    userdata.log_event(user["sub"], "uni_create", u["id"], body.name)
    return u


@app.put("/api/admin/universities/{uid}/location")
def api_admin_uni_location(uid: str, body: UniversityIn, user: dict = Depends(_aspph)):
    if not universities.get(uid):
        raise HTTPException(404, "No such university.")
    universities.set_location(uid, body.city, body.state)
    return universities.get(uid)


@app.get("/api/admin/universities/{uid}")
def api_admin_university(uid: str, user: dict = Depends(_aspph)):
    u = universities.get(uid)
    if not u:
        raise HTTPException(404, "No such university.")
    return {**u, "members": universities.list_members(uid), "invites": universities.list_invites(uid),
            "courses": [{k: c.get(k) for k in ("prof_sub", "professor", "course", "summary", "updated_at")} for c in universities.list_courses(uid)]}


@app.post("/api/admin/universities/{uid}/invites")
def api_admin_uni_invite(uid: str, body: InviteIn, user: dict = Depends(_aspph)):
    """ASPPH onboards a university by inviting its first admin (or professors directly)."""
    if not universities.get(uid):
        raise HTTPException(404, "No such university.")
    return universities.create_invite(uid, body.role, user.get("email", ""), max(1, min(body.days, 90)), max(1, min(body.max_uses, 500)))


# ---------- ASPPH admin: shared university AI policies (review before they join the library) ----------
import policies  # noqa: E402


@app.get("/api/admin/policies")
def api_admin_policies(user: dict = Depends(_aspph)):
    return {"library": policies.list_library(), "shares": policies.list_shares()}


@app.post("/api/admin/policies/{sid}/approve")
def api_admin_policy_approve(sid: str, user: dict = Depends(_aspph)):
    try:
        return policies.approve(user, sid)
    except KeyError:
        raise HTTPException(404, "No such share.")
    except ValueError as e:
        raise HTTPException(400, str(e))


class NoteIn(BaseModel):
    note: str


@app.post("/api/admin/policies/{sid}/return")
def api_admin_policy_return(sid: str, body: NoteIn, user: dict = Depends(_aspph)):
    try:
        return policies.return_share(user, sid, body.note)
    except KeyError:
        raise HTTPException(404, "No such share.")
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------- ASPPH admin: the Agent monitor (usage records + AgentCore's own CloudWatch metrics) ----------
import usage  # noqa: E402


def _runtime_metrics(days: int) -> dict:
    """AgentCore runtime + Guardrail metrics from CloudWatch, for the same window. Hourly for 1 day, else daily."""
    import boto3
    from datetime import datetime, timedelta, timezone
    arn = os.getenv("AGENT_RUNTIME_ARN") or json.loads((Path(__file__).with_name("agentcore_ids.json")).read_text())["agent_runtime_arn"]
    end = datetime.now(timezone.utc)
    start, period = end - timedelta(days=days), 3600 if days <= 1 else 86400
    dims = [{"Name": "Resource", "Value": arn}, {"Name": "Operation", "Value": "InvokeAgentRuntime"}, {"Name": "Name", "Value": "phact_agent::DEFAULT"}]
    want = {"invocations": ("Invocations", "Sum"), "errors": ("Errors", "Sum"), "system_errors": ("SystemErrors", "Sum"),
            "user_errors": ("UserErrors", "Sum"), "throttles": ("Throttles", "Sum"), "sessions": ("Sessions", "Sum"),
            "latency_avg": ("Latency", "Average"), "latency_p90": ("Latency", "p90")}
    q = [{"Id": k, "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock-AgentCore", "MetricName": m, "Dimensions": dims},
                                  "Period": period, "Stat": st}} for k, (m, st) in want.items()]
    gd = [{"Name": "Operation", "Value": "ApplyGuardrail"}]
    q += [{"Id": "guard_checks", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock/Guardrails", "MetricName": "Invocations", "Dimensions": gd}, "Period": period, "Stat": "Sum"}},
          {"Id": "guard_blocked", "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock/Guardrails", "MetricName": "InvocationsIntervened", "Dimensions": gd}, "Period": period, "Stat": "Sum"}}]
    res = boto3.client("cloudwatch", region_name=os.getenv("AWS_REGION", "us-west-2")).get_metric_data(MetricDataQueries=q, StartTime=start, EndTime=end)
    out = {"period_s": period, "series": {}}
    for r in res["MetricDataResults"]:
        pts = sorted(zip(r["Timestamps"], r["Values"]))
        out["series"][r["Id"]] = [{"t": t.isoformat(), "v": round(v, 1)} for t, v in pts]
        vals = [v for _, v in pts]
        out[r["Id"]] = (round(sum(vals) / len(vals)) if vals else None) if r["Id"].startswith("latency") else int(sum(vals))
    return out


@app.get("/api/admin/monitor")
def api_admin_monitor(days: int = 7, user: dict = Depends(_aspph)):
    """Every AI run across the organization: health, time per stage, tokens and estimated cost, quality, by university."""
    days = max(1, min(days, 90))
    names = {u["id"]: u["name"] for u in universities.list_all()}
    out = usage.aggregate(usage.load(days), days, names)
    try:
        out["runtime"] = _runtime_metrics(days)
    except Exception as e:  # noqa: BLE001 — the usage numbers still show if CloudWatch can't be read
        out["runtime"] = {"error": str(e)[:200]}
    return out


@app.get("/university")
def university_page():
    return FileResponse(Path(__file__).with_name("university.html"))


# ---------- ASPPH admin: the knowledge-base source library (aspph-staff only) ----------
import admin_sources  # noqa: E402


def _staff(user: dict = Depends(current_user)) -> dict:
    accounts.require_role(user, "aspph-admin")
    return user


@app.get("/client.js")
def client_js():
    return FileResponse(Path(__file__).with_name("client.js"), media_type="application/javascript")


@app.get("/admin")
def admin_page():
    return FileResponse(Path(__file__).with_name("admin.html"))


@app.get("/api/admin/sources")
def api_admin_sources(user: dict = Depends(_staff)):
    return [{k: v for k, v in d.items() if k != "keys"} for d in admin_sources.list_sources()]


@app.post("/api/admin/sources/preview")
async def api_admin_preview(file: UploadFile = File(...), user: dict = Depends(_staff)):
    """Upload → read (Textract for PDFs) → split into sections for the admin to review before publishing."""
    suffix = (Path(file.filename or "x.txt").suffix or ".txt").lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md"):
        raise HTTPException(400, "Upload a PDF, Word, text or markdown file.")
    data = await file.read()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"source{suffix}"
        path.write_bytes(data)
        try:
            text = extract(path)
        except Exception as e:
            raise friendly(e)
    sections = admin_sources.split_sections(text)
    pid = admin_sources.save_preview(data, suffix, sections)
    title = Path(file.filename or "").stem.replace("_", " ").replace("-", " ").strip()
    return {"preview_id": pid, "title": title, "sections": sections, "words": len(text.split())}


class PublishIn(BaseModel):
    preview_id: str
    meta: dict
    sections: list[dict]
    replaces: str | None = None
    old_status: str = "secondary"


@app.post("/api/admin/sources/publish")
def api_admin_publish(body: PublishIn, user: dict = Depends(_staff)):
    try:
        return admin_sources.publish(user, body.preview_id, body.meta, body.sections, body.replaces, body.old_status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise friendly(e)


class StatusIn(BaseModel):
    status: str


@app.put("/api/admin/sources/{doc_id}/status")
def api_admin_status(doc_id: str, body: StatusIn, user: dict = Depends(_staff)):
    try:
        return admin_sources.set_status(user, doc_id, body.status)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Can't change {doc_id}: {e}")


# ---------- example syllabi: professors share, ASPPH staff review (Phase 11) ----------
@app.post("/api/submissions")
async def api_submit(request: Request, user: dict = Depends(current_user)):
    try:
        return admin_sources.submit(user, await request.json())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/submissions/mine")
def api_my_submissions(user: dict = Depends(current_user)):
    return admin_sources.list_submissions(owner_sub=user["sub"])


@app.post("/api/submissions/{sid}/withdraw")
def api_withdraw(sid: str, user: dict = Depends(current_user)):
    try:
        return admin_sources.withdraw(user, sid)
    except PermissionError:
        raise HTTPException(403, "That isn't your submission.")
    except KeyError:
        raise HTTPException(404, "No such submission.")


@app.get("/api/admin/submissions")
def api_admin_submissions(status: str | None = None, user: dict = Depends(_staff)):
    return admin_sources.list_submissions(status=status)


@app.get("/api/admin/submissions/{sid}")
def api_admin_submission(sid: str, user: dict = Depends(_staff)):
    try:
        return admin_sources.get_submission(sid)
    except KeyError:
        raise HTTPException(404, "No such submission.")


class ApproveIn(BaseModel):
    section_ids: list[str]
    tags: dict = {}


@app.post("/api/admin/submissions/{sid}/approve")
def api_admin_approve(sid: str, body: ApproveIn, user: dict = Depends(_staff)):
    try:
        return admin_sources.approve(user, sid, body.section_ids, body.tags)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


class ReturnIn(BaseModel):
    note: str


@app.post("/api/admin/submissions/{sid}/return")
def api_admin_return(sid: str, body: ReturnIn, user: dict = Depends(_staff)):
    try:
        return admin_sources.return_submission(user, sid, body.note)
    except KeyError:
        raise HTTPException(404, "No such submission.")


@app.get("/api/admin/audit")
def api_admin_audit(user: dict = Depends(_staff)):
    return admin_sources.list_audit()


SAMPLES = {  # fictional demo documents (no real people), so any document type can be shown in seconds
    "EPID 601 syllabus": ROOT / "data/test-syllabi/Synthetic/MPH_Syllabus_01_Northeast_Epidemiology.docx",
    "Problem Set 3 (homework)": ROOT / "data/test-assessments/EPID601_Homework_ProblemSet3.docx",
    "Midterm (exam)": ROOT / "data/test-assessments/EPID601_Exam_Midterm.docx",
    "Surveillance brief (project)": ROOT / "data/test-assessments/EPID601_Project_TeamSurveillanceBrief.docx",
    "Appraisal memo (written)": ROOT / "data/test-assessments/EPID601_Written_CriticalAppraisalMemo.docx",
    "Week 7 reading guide": ROOT / "data/test-assessments/EPID601_Week7_ReadingGuide.docx",
}


@app.get("/api/samples")
def api_samples():
    return [name for name, path in SAMPLES.items() if path.exists()]


@app.get("/api/samples/file")
def api_sample_file(name: str):
    path = SAMPLES.get(name)
    if not path or not path.exists():
        raise HTTPException(404, "No such sample.")
    return FileResponse(path, filename=path.name)


@app.get("/api/demo")
def api_demo():
    """Dev shortcut for /?demo: the last saved analysis, so UI work doesn't need a 1-minute run."""
    f = UPLOADS / "demo.json"
    if not f.exists():
        raise HTTPException(404, "No demo saved.")
    return json.loads(f.read_text())


class SearchIn(BaseModel):
    q: str
    source_type: str = "any"
    k: int = 5


@app.post("/api/search")
def api_search(body: SearchIn):
    types = ["guidance", "workforce"] if body.source_type == "any" else [body.source_type]
    try:
        hits = retrieval.search(body.q, types, k=body.k)
    except Exception as e:
        raise friendly(e)
    for h in hits:
        h["uri"] = f"s3://{retrieval.BUCKET}/{h['original']}" if h["original"] else ""
    return hits


@app.get("/api/source")
def api_source(uri: str, json_out: int = Query(0, alias="json")):
    """The page asks with ?json=1 (it sends the sign-in token) and opens the short-lived link it gets back.
    A plain link can't carry the token, which is why "open PDF" failed on AWS."""
    if uri.startswith("https://"):  # pattern cards cite public web pages
        url = uri
    elif uri.startswith(f"s3://{retrieval.BUCKET}/originals/"):
        url = retrieval.presigned_source_link(uri)
    else:
        raise HTTPException(400, "Only PHACT source PDFs can be opened.")
    return {"url": url} if json_out else RedirectResponse(url)


@app.get("/api/models")
def api_models():
    return {"strong": llm.MODELS["strong"], "fast": llm.MODELS["fast"], "kb_id": retrieval.KB_ID, "region": llm.REGION}


if __name__ == "__main__":
    import os
    import uvicorn  # only for running locally; on Lambda, Mangum serves the app (lambda_handler.py)
    # Local default: this Mac only. On the EC2 demo server the service sets PHACT_HOST=0.0.0.0, PHACT_PORT=80.
    uvicorn.run(app, host=os.getenv("PHACT_HOST", "127.0.0.1"), port=int(os.getenv("PHACT_PORT", "8787")),
                timeout_keep_alive=300)
