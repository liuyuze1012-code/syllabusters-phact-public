"""University layer: one university can never see another's professors or courses; the university policy goes
above the professor; invite codes can't be reused or escalated. Real DynamoDB, the fictional demo universities
from scripts/setup_universities.py. Sessions are signed locally (cookie mode) with each demo account's identity."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "agent" / "eval"), str(ROOT / "backend"), str(ROOT / "playground")]
os.environ["PHACT_AUTH"] = "1"
os.environ["PHACT_AUTH_MODE"] = "cookie"
from fastapi.testclient import TestClient  # noqa: E402

import accounts  # noqa: E402
import server  # noqa: E402
import universities  # noqa: E402
import userdata  # noqa: E402

if not universities.get("westbridge") or not universities.get("northfield"):
    pytest.skip("run scripts/setup_universities.py first", allow_module_level=True)


def member(uni, role):
    m = next(m for m in universities.list_members(uni) if m["role"] == role)
    return {"sub": m["sub"], "email": m["email"], "name": m["name"], "role": role, "university_id": uni}


def client(user):
    c = TestClient(server.app)
    c.cookies.set(accounts.COOKIE, accounts.make_token(user))
    return c


ASPPH = {"sub": "test-aspph", "email": "a@aspph.test", "name": "ASPPH", "role": "aspph-admin", "university_id": ""}
WB_ADMIN, WB_PROF = member("westbridge", "school-admin"), member("westbridge", "faculty")
NF_ADMIN, NF_PROF = member("northfield", "school-admin"), member("northfield", "faculty")


@pytest.fixture(scope="module")
def nf_course():
    """A Northfield professor saves a course, exactly as the app does."""
    c = client(NF_PROF)
    course = {"code": "ISO 101", "name": "Isolation test", "ai_stance": "open"}
    assert c.put("/api/data/courses/ISO 101", json={"course": course}).status_code == 200
    assert c.put("/api/data/progress/ISO 101", json={"outline": {"sections": [], "ai_policy": None},
                                                       "comps": [{"id": 1, "status": "covered", "reason": "x"}], "edits": []}).status_code == 200
    yield course
    c.delete("/api/data/courses/ISO 101")


def test_stricter_policy_wins():
    assert universities.cap_stance("open", "restricted") == "restricted"
    assert universities.cap_stance("ban", "open") == "ban"
    assert universities.cap_stance("restricted", None) == "restricted"
    assert universities.cap_stance("made-up", "ban") == "ban"


def test_professor_course_shows_up_only_in_their_university(nf_course):
    nf = client(NF_ADMIN).get("/api/uni/courses").json()
    assert any(x["prof_sub"] == NF_PROF["sub"] and x["course"]["code"] == "ISO 101" for x in nf)
    wb = client(WB_ADMIN).get("/api/uni/courses").json()
    assert not any(x["prof_sub"] == NF_PROF["sub"] for x in wb)


def test_admin_cannot_read_another_universitys_course(nf_course):
    assert client(NF_ADMIN).get(f"/api/uni/courses/{NF_PROF['sub']}/ISO 101").status_code == 200
    r = client(WB_ADMIN).get(f"/api/uni/courses/{NF_PROF['sub']}/ISO 101")
    assert r.status_code == 404  # looks exactly like a course that doesn't exist


def test_uni_parameter_is_ignored_for_university_admins(nf_course):
    r = client(WB_ADMIN).get("/api/uni?uni=northfield").json()
    assert r["id"] == "westbridge"
    assert not any(x["prof_sub"] == NF_PROF["sub"] for x in client(WB_ADMIN).get("/api/uni/courses?uni=northfield").json())
    assert all(m["sub"] != NF_PROF["sub"] for m in client(WB_ADMIN).get("/api/uni/professors?uni=northfield").json())


def test_professors_cannot_use_the_admin_portal():
    for path in ("/api/uni", "/api/uni/professors", "/api/uni/courses", "/api/uni/competencies", "/api/uni/policy/library"):
        assert client(WB_PROF).get(path).status_code == 403
    assert client(WB_PROF).put("/api/uni/policy", json={"max_ai_level": "integrated"}).status_code == 403
    assert client(WB_PROF).post("/api/uni/policy/share", json={"max_ai_level": "none", "rules": [{"text": "x"}]}).status_code == 403
    assert client(WB_ADMIN).get("/api/admin/universities").status_code == 403  # nor can a university admin act as ASPPH
    assert client(WB_ADMIN).get("/api/admin/policies").status_code == 403


def test_university_admins_no_longer_make_invite_codes():
    """Professors come from ASPPH's member records; only ASPPH issues codes (to onboard a university's admin)."""
    assert client(WB_ADMIN).post("/api/uni/invites", json={"role": "faculty"}).status_code in (404, 405)


def test_program_competencies_only_count_own_university(nf_course):
    rows = {r["id"]: r for r in client(NF_ADMIN).get("/api/uni/competencies").json()["rows"]}
    assert len(rows) == 22 and "ISO 101" in rows[1]["courses"] and rows[1]["color"] == "green"
    wb = {r["id"]: r for r in client(WB_ADMIN).get("/api/uni/competencies").json()["rows"]}
    assert "ISO 101" not in wb[1]["courses"]


def test_shared_policy_goes_through_aspph_review():
    import policies
    wb = client(WB_ADMIN)
    s = wb.post("/api/uni/policy/share", json={"name": "Test share (delete me)", "max_ai_level": "assistive",
                                                "rules": [{"id": "T-1", "text": "Disclose AI use."}]}).json()
    try:
        assert s["status"] == "pending" and s["uni_id"] == "westbridge"
        lib = wb.get("/api/uni/policy/library").json()
        assert all(p["name"] != "Test share (delete me)" for p in lib["library"])            # not in the library before review
        assert any(x["id"] == s["id"] for x in lib["my_shares"])
        assert all(x["id"] != s["id"] for x in client(NF_ADMIN).get("/api/uni/policy/library").json()["my_shares"])
        assert any(p["publisher"] == "ASPPH" for p in lib["library"])                        # ASPPH's suggested policies are there
        r = client(ASPPH).post(f"/api/admin/policies/{s['id']}/approve").json()
        assert r["status"] == "approved"
        assert any(p["id"] == r["policy_id"] for p in wb.get("/api/uni/policy/library").json()["library"])
        assert client(ASPPH).post(f"/api/admin/policies/{s['id']}/approve").status_code == 400  # only once
    finally:
        t = userdata.table()
        t.delete_item(Key={"PK": f"POLICYSUB#{s['id']}", "SK": "META"})
        t.delete_item(Key={"PK": f"POLICY#shared-{s['id']}", "SK": "META"})


def test_policy_goes_above_the_professor():
    ctx_course = server.CourseIn(code="X 1", ai_stance="open")
    ctx = server.make_context(ctx_course, WB_PROF)     # Westbridge allows at most "restricted"
    assert ctx_course.ai_stance == "restricted"
    assert ctx.policy_source == "school" and {r.id for r in ctx.school_rules} == {"WU-AI-1", "WU-AI-2"}
    free = server.CourseIn(code="X 2", ai_stance="open")
    assert server.make_context(free, {"sub": "independent"}).policy_source == "phact_default" and free.ai_stance == "open"


def test_professor_sees_own_university_policy():
    r = client(WB_PROF).get("/api/data/university").json()
    assert r["id"] == "westbridge" and universities.level_of(r["policy"]) in ("assistive", "guided")


ASPPH = {"sub": "test-aspph", "email": "a@aspph.test", "name": "ASPPH", "role": "aspph-admin", "university_id": ""}


def test_aspph_sees_every_university_by_region_but_not_the_portal():
    d = client(ASPPH).get("/api/admin/universities").json()
    by = {u["id"]: u for u in d}
    assert by["westbridge"]["region"] == "Northeast" and by["northfield"]["region"] == "Midwest"
    assert by["westbridge"]["professors"] >= 1 and by["westbridge"]["admins"] >= 1
    assert client(ASPPH).get("/api/admin/universities/westbridge").json()["id"] == "westbridge"
    assert client(ASPPH).get("/api/uni").status_code == 403         # the university portal is for university admins only
    for who in (WB_ADMIN, WB_PROF):                                   # and the organization view is for ASPPH only
        assert client(who).get("/api/admin/universities").status_code == 403
        assert client(who).get("/api/admin/universities/westbridge").status_code == 403
