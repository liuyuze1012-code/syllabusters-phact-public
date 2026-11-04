"""Read an ASSESSMENT (homework, exam, project, written assignment) into an Outline, like Station 1 does
for a syllabus. Same design: Claude returns line numbers, code slices the exact text, so every section is
the professor's own words and the edit gates can match `original` text.

Model: fast, effort low, thinking off. Prompt: prompts/assess_structure.md.
Refuses documents that look like student work (FERPA): PHACT works on instructor materials only.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from phact_contracts.agent import Assignment, Outline, Section

import llm
from steps.structure import claims_in, number_lines

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "assess_structure.md").read_text()
KINDS = {"instructions", "task", "rubric", "policy", "other"}
TYPES = ("homework", "exam", "project", "written")


class Span(BaseModel):
    id: str
    kind: str = Field(description="instructions | task | rubric | policy | other")
    title: str
    start_line: int
    end_line: int


class AssessOut(BaseModel):
    material_type: Literal["homework", "exam", "project", "written"]
    title: str
    weight: float | None = None
    points: float | None = None
    what_it_tests: str = ""
    sections: list[Span]
    ai_rule_lines: list[int] | None = None
    claimed_competencies: list[int] = []
    looks_like_student_work: bool = False
    student_work_reason: str = ""


class AssessMeta(BaseModel):
    """What the UI and the later steps need to know about the assessment, beyond its sections."""
    material_type: str
    title: str
    weight: float | None = None
    points: float | None = None
    what_it_tests: str = ""
    ai_rule: str | None = None
    has_rubric: bool = False
    task_count: int = 0


class StudentWork(Exception):
    pass


def repair(out: AssessOut, n: int) -> AssessOut:
    """Close gaps in code instead of failing: sort the sections, clip them to the document, and extend each
    one to meet the next, so no line is ever dropped. (The model sometimes skipped a rubric table or a
    footer, and the coverage check then rejected a good index twice, Nov 4.)"""
    spans = sorted([s for s in out.sections if s.start_line <= n and s.end_line >= 1], key=lambda s: s.start_line)
    for i, s in enumerate(spans):
        s.start_line = 1 if i == 0 else max(s.start_line, spans[i - 1].end_line + 1)
        s.end_line = n if i == len(spans) - 1 else max(s.start_line, spans[i + 1].start_line - 1)
    out.sections = [s for s in spans if s.start_line <= s.end_line]
    return out


def check(out: AssessOut, lines: list[str]) -> list[str]:
    problems, n, prev, covered = [], len(lines), 0, set()
    ids = [s.id for s in out.sections]
    if len(ids) != len(set(ids)):
        problems.append("section ids are not unique")
    for s in out.sections:
        if not (1 <= s.start_line <= s.end_line <= n):
            problems.append(f"section {s.id}: line range {s.start_line}-{s.end_line} is outside 1-{n}")
            continue
        if s.start_line <= prev:
            problems.append(f"section {s.id}: overlaps the previous section")
        prev = s.end_line
        covered.update(range(s.start_line, s.end_line + 1))
        if s.kind not in KINDS:
            problems.append(f"section {s.id}: unknown kind {s.kind!r}")
    content = {i for i, ln in enumerate(lines, 1) if ln.strip()}
    if len(content & covered) / max(1, len(content)) < 0.9:
        problems.append("sections must cover at least 90% of the non-blank lines")
    if not any(s.kind == "task" for s in out.sections):
        problems.append("no `task` section: give each question, part or deliverable its own task section")
    return problems


def run(text: str, type_hint: str | None = None) -> tuple[Outline, AssessMeta, list[llm.CallStats]]:
    lines, numbered = number_lines(text)
    hint = f'\nThe professor says this is a "{type_hint}" assessment.' if type_hint in TYPES else ""
    user = f'<assessment total_lines="{len(lines)}">\n{numbered}\n</assessment>{hint}'
    stats = []
    out, s = llm.call(station="assess-structure", tier="fast", system=PROMPT, user=user,
                      schema=AssessOut, effort="low", max_tokens=6000, think=False)
    stats.append(s)
    out = repair(out, len(lines))
    problems = check(out, lines)
    if problems:
        out, s = llm.call(station="assess-structure-retry", tier="fast", system=PROMPT,
                          user=user + "\n\nYour previous index had these problems; fix them:\n- " + "\n- ".join(problems),
                          schema=AssessOut, effort="low", max_tokens=6000, think=False)
        stats.append(s)
        out = repair(out, len(lines))
        if (problems := check(out, lines)):
            raise llm.LLMError("structure_gate_failed", "; ".join(problems))
    if out.looks_like_student_work:
        raise StudentWork(out.student_work_reason or "This looks like a student's submission.")

    def sl(a: int, b: int) -> str:
        return "\n".join(lines[a - 1:b]).strip()

    sections = [Section(id=s.id, kind=s.kind if s.kind in KINDS else "other", title=s.title, text=sl(s.start_line, s.end_line))
                for s in out.sections]
    # Each task is a graded piece, so the graded-work rule in map_ceph can recognise it as evidence.
    assignments = [Assignment(id=s.id, section_id=s.id, title=s.title, weight=None, what_it_tests=out.what_it_tests or s.title,
                              assessed=True) for s in sections if s.kind == "task"]
    ai_rule = sl(*out.ai_rule_lines) if out.ai_rule_lines and len(out.ai_rule_lines) == 2 else None
    outline = Outline(sections=sections, assignments=assignments, ai_policy=ai_rule,
                      claimed_competencies=sorted(set(out.claimed_competencies) | claims_in(text)))
    meta = AssessMeta(material_type=type_hint if type_hint in TYPES else out.material_type, title=out.title,
                      weight=out.weight, points=out.points, what_it_tests=out.what_it_tests, ai_rule=ai_rule,
                      has_rubric=any(s.kind == "rubric" for s in sections), task_count=len(assignments))
    return outline, meta, stats
