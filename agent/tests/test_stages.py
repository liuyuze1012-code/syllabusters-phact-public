"""The Strands Graph orchestrator must run PHACT's stages in order, share state, and surface errors,
exactly like the plain loop it replaces."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import stages  # noqa: E402


def _pipeline():
    order = []
    def a(s): order.append("a"); s["x"] = 2
    def b(s): order.append("b"); s["y"] = s["x"] * 3
    def c(s): order.append("c"); s["z"] = s["y"] + 1
    return order, [("a", a), ("b", b), ("c", c)]


@pytest.mark.parametrize("mode", ["strands", "plain"])
def test_runs_in_order_and_shares_state(monkeypatch, mode):
    monkeypatch.setenv("PHACT_ORCHESTRATOR", mode)
    order, pipe = _pipeline()
    st = stages.run_stages("t", pipe, {})
    assert order == ["a", "b", "c"] and st["z"] == 7
    assert set(st["timings"]) == {"a", "b", "c"}
    assert st["orchestrator"]["name"] == ("strands-graph" if mode == "strands" else "plain")


@pytest.mark.parametrize("mode", ["strands", "plain"])
def test_a_failing_stage_stops_the_pipeline(monkeypatch, mode):
    monkeypatch.setenv("PHACT_ORCHESTRATOR", mode)
    ran = []
    def boom(s): raise ValueError("stage failed")
    with pytest.raises(ValueError, match="stage failed"):
        stages.run_stages("t", [("ok", lambda s: ran.append(1)), ("boom", boom), ("never", lambda s: ran.append(2))], {})
    assert ran == [1]
