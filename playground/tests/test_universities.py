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
    for path in ("/api/uni", "/api/uni/professors", "/api/uni/courses", "/api/uni/invites"):
        assert client(WB_PROF).get(path).status_code == 403
    assert client(WB_PROF).put("/api/uni/policy", json={"max_ai_stance": "open"}).status_code == 403
    assert client(WB_ADMIN).get("/api/admin/universities").status_code == 403  # nor can a university admin act as ASPPH


def test_university_admin_can_invite_professors_but_not_admins():
    c = client(WB_ADMIN)
    assert c.post("/api/uni/invites", json={"role": "school-admin"}).status_code == 403
    inv = c.post("/api/uni/invites", json={"role": "faculty", "max_uses": 1}).json()
    assert inv["uni_id"] == "westbridge" and inv["role"] == "faculty"
    universities.redeem_invite(inv["code"])            # the only use
    with pytest.raises(Exception):
        universities.redeem_invite(inv["code"])        # used up: can't join twice on one use
    inv2 = c.post("/api/uni/invites", json={"role": "faculty"}).json()
    assert client(NF_ADMIN).delete(f"/api/uni/invites/{inv2['code']}").status_code == 404  # not theirs to revoke
    assert c.delete(f"/api/uni/invites/{inv2['code']}").status_code == 200
    assert universities.check_invite(inv2["code"]) is None
    with pytest.raises(Exception):
        universities.redeem_invite(inv2["code"])       # revoked


def test_policy_goes_above_the_professor():
    ctx_course = server.CourseIn(code="X 1", ai_stance="open")
    ctx = server.make_context(ctx_course, WB_PROF)     # Westbridge allows at most "restricted"
    assert ctx_course.ai_stance == "restricted"
    assert ctx.policy_source == "school" and {r.id for r in ctx.school_rules} == {"WU-AI-1", "WU-AI-2"}
    free = server.CourseIn(code="X 2", ai_stance="open")
    assert server.make_context(free, {"sub": "independent"}).policy_source == "phact_default" and free.ai_stance == "open"


def test_professor_sees_own_university_policy():
    r = client(WB_PROF).get("/api/data/university").json()
    assert r["id"] == "westbridge" and r["policy"]["max_ai_stance"] == "restricted"


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
