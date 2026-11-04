"""The ban gate, tested on the real sentence Opus produced under a ban (Nov 3) and safe counterexamples."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gates  # noqa: E402
from gates import violates_ban  # noqa: E402


def test_catches_real_violation():
    assert violates_ban("Visualization critique with an optional AI brainstorming step. Students may ask an AI tool "
                        "to brainstorm three alternative chart designs for a provided surveillance figure.")


def test_allows_a_ban_policy():
    assert not violates_ban("AI-use level for BIOS 622: Banned. Students may not use generative AI tools for any graded work.")


def test_allows_teaching_about_ai():
    assert not violates_ban("Students critique an instructor-provided AI-generated chart and identify its errors.")


def test_edit_without_sources_is_rejected():
    from phact_contracts.agent import Outline, Passage, Section
    from gates import check_edit
    outline = Outline(sections=[Section(id="week-6", kind="week", title="Week 6", text="Role-play (ungraded)")])
    p = [Passage(id="P1", title="AI Framework", snippet="…", uri="", source_type="guidance")]
    edit = {"section_id": "week-6", "op": "insert_after", "proposed": "Add a graded simulation.",
            "rationale": "Closes the gap.", "evidence_ids": []}
    assert any("at least one" in x for x in check_edit(edit, outline, p, set()))
    assert check_edit({**edit, "evidence_ids": ["P1"]}, outline, p, set()) == []


def test_schedule_edit_must_stay_row_sized():
    from phact_contracts.agent import Outline, Passage, Section
    outline = Outline(sections=[Section(id="week-11", kind="week", title="Week 11", text="Week 11 | Module 6 | Financial Management")])
    passages = [Passage(id="P1", title="t", snippet="s", uri="u", source_type="guidance")]
    base = {"section_id": "week-11", "op": "insert_after", "original": None, "rationale": "r", "evidence_ids": ["P1"]}
    long = gates.check_edit({**base, "proposed": "Assignment brief. " * 30}, outline, passages, set())
    short = gates.check_edit({**base, "proposed": "Leadership Strategy Case Brief (10 pts, due Mar 25); details under Assignments"}, outline, passages, set())
    assert any("too long for the schedule" in p for p in long)
    assert short == []


def test_assessment_suggestion_needs_level_and_parts():
    part = "A specific, concrete description long enough to count."
    full = {"proposed": "Students may use an AI tool to explain code errors.", "aias_level": 3, "ai_role": part,
            "rubric_row": part, "ai_use_statement": part, "reflection_activity": part, "practicalities": part}
    assert gates.check_suggestion(full, "restricted") == []
    assert any("above what this course allows" in p for p in gates.check_suggestion({**full, "aias_level": 4}, "restricted"))
    assert any("no aias_level" in p for p in gates.check_suggestion({**full, "aias_level": None}, "open"))
    assert any("rubric row" in p for p in gates.check_suggestion({**full, "rubric_row": "graded"}, "open"))
    assert any("paid AI plan" in p for p in gates.check_suggestion({**full, "practicalities": part + " Requires ChatGPT Plus."}, "open"))
    assert gates.check_suggestion({"proposed": "Add a short oral defense of the analysis."}, "ban") == []
    assert gates.check_suggestion({**full, "practicalities": part + " No paid subscription is needed."}, "open") == []
