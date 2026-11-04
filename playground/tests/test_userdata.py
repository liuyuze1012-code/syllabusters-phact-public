"""Phase 2 gate: the data functions against the REAL table and bucket, with throwaway test users."""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import userdata  # noqa: E402


@pytest.fixture
def users():
    a, b = f"test-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    yield a, b
    userdata.delete_user_data(a)
    userdata.delete_user_data(b)


def test_profile_course_progress_roundtrip(users):
    a, _ = users
    userdata.put_profile(a, email="a@example.edu", name="Prof A", role="faculty", prefs={"stance": "restricted"})
    assert userdata.get_profile(a)["prefs"]["stance"] == "restricted"
    course = {"code": "EPID 601", "name": "Applied Epi", "size": 30}
    progress = {"outline": {"sections": []}, "edits": [{"edit_id": "E1"}], "decisions": {"E1": "accepted"},
                "materials": {"m1": {"edits": [{"edit_id": "E1"}, {"edit_id": "E2"}], "decisions": {}}}}
    userdata.put_progress(a, "EPID 601", progress)
    userdata.put_course(a, course, userdata.progress_summary(progress))
    listed = userdata.list_courses(a)
    assert [c["course"]["code"] for c in listed] == ["EPID 601"]
    assert listed[0]["summary"]["changes"] == 3 and listed[0]["summary"]["accepted"] == 1
    assert userdata.get_progress(a, "EPID 601") == progress
    userdata.delete_course(a, "EPID 601")
    assert userdata.list_courses(a) == [] and userdata.get_progress(a, "EPID 601") is None


def test_users_are_isolated(users):
    a, b = users
    userdata.put_course(a, {"code": "PHC 6149", "name": "Leadership"})
    userdata.put_progress(a, "PHC 6149", {"secret": "A's work"})
    assert userdata.list_courses(b) == []
    assert userdata.get_progress(b, "PHC 6149") is None


def test_large_progress_goes_to_s3(users):
    a, _ = users
    big = {"outline": {"sections": [{"text": "x" * 1000} for _ in range(600)]}}  # ~600 KB: over DynamoDB's 400 KB
    userdata.put_progress(a, "BIG 1", big)
    assert len(userdata.get_progress(a, "BIG 1")["outline"]["sections"]) == 600


def test_uploads_and_events(users):
    a, b = users
    userdata.put_upload(a, "abc123", ".docx", b"file bytes")
    assert userdata.get_upload(a, "abc123", ".docx") == b"file bytes"
    assert userdata.get_upload(b, "abc123", ".docx") is None  # another user can't fetch it by guessing the id
    with pytest.raises(ValueError):
        userdata.upload_key(a, "../x", ".docx")
    userdata.log_event(a, "analyze", "EPID 601", "syllabus")
    userdata.log_event(a, "decision", "EPID 601", "E1 accepted")
    ev = userdata.list_events(a)
    assert [e["type"] for e in ev] == ["decision", "analyze"]  # newest first


def test_bad_user_ids_are_refused():
    for bad in ["", "a#b", "a/b"]:
        with pytest.raises(ValueError):
            userdata.list_courses(bad)
