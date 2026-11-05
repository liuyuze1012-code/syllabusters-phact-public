"""University AI levels, the program competency rollup, and the policy library rules. Pure: no AWS."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "playground")]
import universities as U  # noqa: E402


def test_levels_and_old_policies():
    assert U.level_of({"max_ai_level": "assistive"}) == "assistive"
    assert U.level_of({"max_ai_stance": "ban"}) == "none" and U.level_of({}) == "integrated"
    p = U.clean_policy({"max_ai_level": "assistive", "rules": [{"text": "Disclose AI use."}], "notes": "dropped"})
    assert p == {"max_ai_level": "assistive", "max_ai_stance": "restricted", "rules": [{"id": "UNI-AI-1", "text": "Disclose AI use."}]}
    assert U.clean_policy({"max_ai_level": "bogus"})["max_ai_level"] == "integrated"
    assert U.cap_level("integrated", "assistive") == "assistive" and U.cap_level("none", "guided") == "none"
    # the AI's context still gets a stance: the stricter of professor and university
    assert U.cap_stance("open", U.clean_policy({"max_ai_level": "guided"})["max_ai_stance"]) == "restricted"


def test_course_coverage_uses_syllabus_and_accepted_edits_only():
    pr = {"comps": [{"id": 1, "status": "covered"}, {"id": 2, "status": "partial"}, {"id": 3, "status": "missing"},
                    {"id": 4, "status": "not_assigned"}, {"id": 5, "status": "missing"}],
          "edits": [{"edit_id": "E1", "ceph": [3]}, {"edit_id": "E2", "ceph": [5]}], "decisions": {"E1": "accepted", "E2": "rejected"},
          "materials": {"m": {"comps": [{"id": 5, "status": "covered"}]}}}  # assessments never count
    assert U.course_coverage(pr) == {1: "covered", 2: "partial", 3: "covered", 5: "missing"}


def test_program_colors():
    rows = {r["id"]: r for r in U.program_competencies({"A": {1: "covered", 2: "partial", 3: "partial"},
                                                         "B": {2: "partial", 3: "missing"}, "C": {1: "covered"}})}
    assert rows[1]["color"] == "green" and rows[1]["fulfilled"] == 2 and rows[1]["courses"] == ["A", "C"]
    assert rows[2]["color"] == "yellow" and rows[2]["fulfilled"] == 0      # 2 limited, none full
    assert rows[3]["color"] == "red"                                         # only 1 limited
    assert rows[22]["color"] == "red" and len(rows) == 22
    assert all(len(r["short"].split()) <= 5 for r in rows.values())
