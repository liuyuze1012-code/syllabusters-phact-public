"""Station 1's code checks, tested offline (no Claude calls)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from steps.structure import SectionSpan, StructureOut, check, claims_in, to_outline  # noqa: E402

LINES = ["PHC 6149", "CEPH D2-2.16. Apply leadership", "Week 1 intro", "readings", "Week 2 styles", "quiz"]


def test_claims_found_by_code():
    assert claims_in("CEPH D2-2.10 and D2-2.17; MPH Foundational Competency 16") == {10, 16, 17}


def test_schedule_must_be_split_per_week():
    out = StructureOut(sections=[SectionSpan(id="info", kind="heading", title="Info", start_line=1, end_line=2),
                                 SectionSpan(id="schedule", kind="week", title="Schedule", start_line=3, end_line=6)],
                       assignments=[])
    assert any("split the schedule" in p for p in check(out, LINES))


def test_good_outline_passes_and_text_is_exact():
    out = StructureOut(sections=[SectionSpan(id="info", kind="heading", title="Info", start_line=1, end_line=2),
                                 SectionSpan(id="week-1", kind="week", title="Week 1", start_line=3, end_line=4),
                                 SectionSpan(id="week-2", kind="week", title="Week 2", start_line=5, end_line=6)],
                       assignments=[])
    assert check(out, LINES) == []
    outline = to_outline(out, LINES)
    assert outline.sections[1].text == "Week 1 intro\nreadings"   # sliced from the original, never retyped
    assert outline.claimed_competencies == [16]


def test_assessment_repair_closes_gaps():
    from steps.assess_structure import AssessOut, Span, check, repair
    lines = [f"line {i}" for i in range(1, 21)]
    out = AssessOut(material_type="exam", title="t", sections=[
        Span(id="intro", kind="instructions", title="i", start_line=2, end_line=4),
        Span(id="q1", kind="task", title="q", start_line=8, end_line=12),
        Span(id="rubric", kind="rubric", title="r", start_line=15, end_line=17)])
    fixed = repair(out, 20)
    assert [(s.start_line, s.end_line) for s in fixed.sections] == [(1, 7), (8, 14), (15, 20)]
    assert check(fixed, lines) == []
