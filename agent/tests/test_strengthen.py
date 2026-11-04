"""The source finder may only ADD evidence the Supervisor then verifies. It never invents ids, never edits the
text, never touches unflagged edits, and a failure leaves everything as the Supervisor left it."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))

from phact_contracts.agent import Context, Edit, Outline, Passage, Section  # noqa: E402

import retrieval  # noqa: E402
from steps import strengthen  # noqa: E402

OUTLINE = Outline(sections=[Section(id="s1", title="Assignments", kind="assignment", text="Final project")], assignments=[],
                  claimed_competencies=[], ai_policy=None)


def edit(i, sup):
    return Edit(edit_id=i, section_id="s1", op="insert_after", proposed=f"text {i}", rationale="r", evidence=[], supervisor=sup,
                supervisor_note="cited passage doesn't support it" if sup == "flagged" else None)


def fake_agent(found_ids, searches=(("q", ["P1"]),)):
    """A stand-in for the Strands agent: 'searches' put passages on the stack, then it answers found_ids."""
    def make(e, stack, lock, seen):
        def run(prompt, structured_output_model=None):
            for q, ids in searches:
                for pid in ids:
                    stack.passages.append(Passage(id=pid, title="T", section="S", snippet=f"supports {pid}", uri="", source_type="guidance"))
                seen["n"] += 1
                seen["ids"] |= set(ids)
            return SimpleNamespace(structured_output=strengthen.Found(passage_ids=found_ids, reason="r"),
                                   metrics=SimpleNamespace(accumulated_usage={"inputTokens": 10, "outputTokens": 5}))
        return run
    return make


def supervisor(verdict):
    return lambda e, o, p, c, s: (e.model_copy(update={"supervisor": verdict}), None)


def test_verified_sources_replace_the_flag(monkeypatch):
    monkeypatch.setattr(strengthen, "_agent_for", fake_agent(["P1"]))
    monkeypatch.setattr(strengthen.supervise, "_check", supervisor("pass"))
    edits = [edit("E1", "pass"), edit("E2", "flagged")]
    out, stats, report = strengthen.run(edits, OUTLINE, retrieval.PassageStack(), Context())
    assert [e.edit_id for e in out] == ["E1", "E2"] and out[0] is edits[0]          # unflagged untouched, order kept
    assert out[1].supervisor == "pass" and [x.id for x in out[1].evidence] == ["P1"]
    assert out[1].proposed == "text E2"                                               # text never changed
    assert report[0]["outcome"] == "verified" and stats


def test_invented_ids_are_ignored(monkeypatch):
    monkeypatch.setattr(strengthen, "_agent_for", fake_agent(["P99"]))               # an id no search returned
    monkeypatch.setattr(strengthen.supervise, "_check", supervisor("pass"))
    out, _, report = strengthen.run([edit("E2", "flagged")], OUTLINE, retrieval.PassageStack(), Context())
    assert out[0].supervisor == "flagged" and report[0]["outcome"] == "unchanged"


def test_supervisor_still_decides(monkeypatch):
    monkeypatch.setattr(strengthen, "_agent_for", fake_agent(["P1"]))
    monkeypatch.setattr(strengthen.supervise, "_check", supervisor("flagged"))
    original = edit("E2", "flagged")
    out, _, report = strengthen.run([original], OUTLINE, retrieval.PassageStack(), Context())
    assert out[0] == original and report[0]["outcome"] == "still_flagged"


def test_a_failing_agent_changes_nothing(monkeypatch):
    def broken(*a):
        def run(*x, **k):
            raise RuntimeError("Bedrock throttled")
        return run
    monkeypatch.setattr(strengthen, "_agent_for", broken)
    original = edit("E2", "flagged")
    out, _, report = strengthen.run([original], OUTLINE, retrieval.PassageStack(), Context())
    assert out[0] == original and report[0]["outcome"] == "error"


def test_switched_off(monkeypatch):
    monkeypatch.setenv("PHACT_SOURCE_FINDER", "0")
    edits = [edit("E2", "flagged")]
    assert strengthen.run(edits, OUTLINE, retrieval.PassageStack(), Context())[0] == edits
