"""Agent monitor: the usage record holds counts and times only, and the aggregate math is right. Pure: no AWS."""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "playground")]
import usage  # noqa: E402

NOW = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)
USER = {"sub": "u1", "role": "faculty", "university_id": "westbridge", "email": "prof@example.edu", "name": "Dr. Secret"}
BODY = {"stats": [{"model": "us.anthropic.claude-opus-5-5", "input_tokens": 100_000, "output_tokens": 10_000, "latency_ms": 40_000},
                  {"model": "us.anthropic.claude-haiku-5-5", "input_tokens": 20_000, "output_tokens": 2_000, "latency_ms": 3_000},
                  {"model": "us.anthropic.claude-haiku-5-5", "input_tokens": 0, "output_tokens": 0, "latency_ms": 1_000}],
        "timings_ms": {"map_ceph": 10_000, "propose": 50_000, "note": "x"},
        "edits": [{"supervisor": "ok", "new_text": "SYLLABUS TEXT"}, {"supervisor": "flagged"}],
        "source_finder": {"flagged_before": 2, "report": [{"outcome": "verified"}, {"outcome": "none"}]},
        "doc_type": "syllabus", "syllabus_text": "PRIVATE"}


def test_build_counts_only():
    r = usage.build("j1", "/api/analyze", USER, 200, 70_000, BODY, at=NOW)
    flat = repr(r)
    for secret in ("prof@example.edu", "Dr. Secret", "SYLLABUS TEXT", "PRIVATE"):
        assert secret not in flat
    assert r["PK"] == "USAGE#2026-11-04" and r["SK"].endswith("#j1")
    assert r["status"] == "DONE" and r["university_id"] == "westbridge"
    assert r["stages"] == {"map_ceph": 10_000, "propose": 50_000}  # non-numbers dropped
    assert r["models"]["us.anthropic.claude-haiku-5-5"]["calls"] == 2
    assert (r["suggestions"], r["flagged"], r["flagged_before_finder"], r["finder_verified"]) == (2, 1, 2, 1)


def test_build_failure_and_independent():
    r = usage.build("j2", "/api/chat", {"sub": "u2"}, 500, 1_000, None, error="boom " * 200, at=NOW)
    assert r["status"] == "FAILED" and r["university_id"] == "independent"
    assert len(r["error"]) <= 300 and r["models"] == {} and r["flagged_before_finder"] is None


def test_cost():
    # Opus: 100k in at $4/M + 10k out at $20/M = 0.40 + 0.20
    assert abs(usage.cost("claude-opus-5-5", 100_000, 10_000) - 0.60) < 1e-9
    assert usage.cost("some-other-model", 10**6, 10**6) == 0


def test_pct():
    assert usage.pct([], 50) is None
    assert usage.pct([5], 90) == 5
    assert usage.pct(list(range(1, 11)), 50) == 5 and usage.pct(list(range(1, 11)), 90) == 9


def test_aggregate():
    ok = usage.build("j1", "/api/analyze", USER, 200, 70_000, BODY, at=NOW)
    bad = usage.build("j2", "/api/analyze", {"sub": "u2"}, 500, 5_000, None, error="x", at=NOW)
    chat = usage.build("j3", "/api/chat", USER, 200, 2_000, {"stats": [BODY["stats"][1]]}, at=NOW.replace(day=2))
    m = usage.aggregate([ok, bad, chat], 7, {"westbridge": "Westbridge University"}, now=NOW)
    t = m["totals"]
    assert (t["runs"], t["analyses"], t["errors"], t["universities"], t["professors"]) == (3, 2, 1, 1, 2)
    assert t["analysis_p50_ms"] == 70_000  # only finished analyses count toward time
    assert m["quality"]["finished"] == 1 and m["quality"]["per_analysis"] == 2
    assert abs(t["cost"] - (0.60 + 2 * (20_000 * 0.10 + 2_000 * 0.50) / 1e6)) < 1e-4
    assert [d["date"] for d in m["daily"]][-1] == "2026-11-04" and len(m["daily"]) == 7
    assert m["daily"][-1]["runs"] == 2 and m["daily"][-3]["runs"] == 1
    names = {u["university_id"]: u["name"] for u in m["universities"]}
    assert names == {"westbridge": "Westbridge University", "independent": "Independent faculty"}
    assert m["stages"][0]["stage"] == "map_ceph" and m["recent"][0]["job_id"] in ("j1", "j2")
    assert {o["op"]: o["errors"] for o in m["by_op"]} == {"/api/analyze": 1, "/api/chat": 0}


def test_aggregate_empty():
    m = usage.aggregate([], 1, now=NOW)
    assert m["totals"]["runs"] == 0 and m["totals"]["error_rate"] == 0 and m["stages"] == [] and len(m["daily"]) == 1
