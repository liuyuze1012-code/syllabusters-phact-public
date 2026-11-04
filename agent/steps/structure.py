"""Station 1: Read. Turns syllabus text into an Outline of sections and assignments.

Model: fast, effort low. Call: one structured-output call, no tools. Prompt: prompts/structure.md.
Claude returns LINE NUMBERS, not text; code slices the original text, so every section's text is
exactly the professor's words (the edit gates depend on that).
"""

import re
from pathlib import Path

from pydantic import BaseModel, Field

from phact_contracts.agent import Assignment, Outline, Section

import llm

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "structure.md").read_text()


class SectionSpan(BaseModel):
    id: str
    kind: str = Field(description="heading | objective | week | assignment | policy | other")
    title: str
    start_line: int
    end_line: int


class StructureOut(BaseModel):
    sections: list[SectionSpan]
    assignments: list[Assignment]
    ai_policy_lines: list[int] | None = Field(None, description="[first_line, last_line] or null")
    claimed_competencies: list[int] = []


KINDS = {"heading", "objective", "week", "assignment", "policy", "other"}

# Exact things are found by code, not trusted to the model.
CLAIM_PATTERNS = [
    re.compile(r"\bD2[-–.]\s*2?\.?(\d{1,2})\b"),                                    # CEPH D2-2.16, D2.16
    re.compile(r"\b(?:MPH|foundational)\s*(?:core\s*)?competenc(?:y|ies)?\s*#?\s*(\d{1,2})\b", re.I),
    re.compile(r"\bMPH[-\s]?(\d{1,2})\b"),
]
WEEK_LINE = re.compile(r"^\s*(week|module)\s*(\d{1,2})\b", re.I)


def claims_in(text: str) -> set[int]:
    found = set()
    for pat in CLAIM_PATTERNS:
        found.update(int(m.group(1)) for m in pat.finditer(text) if 1 <= int(m.group(1)) <= 22)
    return found


def number_lines(text: str) -> tuple[list[str], str]:
    lines = text.splitlines()
    return lines, "\n".join(f"L{i:04d}| {ln}" for i, ln in enumerate(lines, 1))


def check(out: StructureOut, lines: list[str]) -> list[str]:
    """The gate after Station 1. Returns problems; [] means pass."""
    problems = []
    n = len(lines)
    ids = [s.id for s in out.sections]
    if len(ids) != len(set(ids)):
        problems.append("section ids are not unique")
    covered = set()
    prev_end = 0
    for s in out.sections:
        if not (1 <= s.start_line <= s.end_line <= n):
            problems.append(f"section {s.id}: line range {s.start_line}-{s.end_line} is outside 1-{n}")
            continue
        if s.start_line <= prev_end:
            problems.append(f"section {s.id}: overlaps the previous section")
        prev_end = s.end_line
        covered.update(range(s.start_line, s.end_line + 1))
        if s.kind not in KINDS:
            problems.append(f"section {s.id}: unknown kind {s.kind!r}")
    content = {i for i, ln in enumerate(lines, 1) if ln.strip()}
    coverage = len(content & covered) / max(1, len(content))
    if coverage < 0.9:
        problems.append(f"sections cover only {coverage:.0%} of the syllabus's non-blank lines (need 90%)")
    for s in out.sections:
        if 1 <= s.start_line <= s.end_line <= n:
            units = {(m.group(1).lower(), m.group(2)) for ln in lines[s.start_line - 1:s.end_line]
                     if (m := WEEK_LINE.match(ln))}
            weeks = {u for u in units if u[0] == "week"} or units
            if len(weeks) >= 2:
                problems.append(f"section {s.id} (lines {s.start_line}-{s.end_line}) contains {len(weeks)} weeks/modules; "
                                "split the schedule into one section per week")
    known = set(ids)
    for a in out.assignments:
        if a.section_id not in known:
            problems.append(f"assignment {a.id}: points to unknown section {a.section_id!r}")
    if any(not 1 <= c <= 22 for c in out.claimed_competencies):
        problems.append("claimed_competencies must be CEPH ids 1-22")
    return problems


def to_outline(out: StructureOut, lines: list[str]) -> Outline:
    def text(a: int, b: int) -> str:
        return "\n".join(lines[a - 1:b]).strip()

    policy = None
    if out.ai_policy_lines and len(out.ai_policy_lines) == 2:
        policy = text(*out.ai_policy_lines)
    return Outline(
        sections=[Section(id=s.id, kind=s.kind if s.kind in KINDS else "other", title=s.title,
                          text=text(s.start_line, s.end_line)) for s in out.sections],
        assignments=out.assignments,
        ai_policy=policy,
        claimed_competencies=sorted(set(out.claimed_competencies) | claims_in("\n".join(lines))),
    )


def run(syllabus_text: str) -> tuple[Outline, list[llm.CallStats]]:
    lines, numbered = number_lines(syllabus_text)
    user = f"<syllabus total_lines=\"{len(lines)}\">\n{numbered}\n</syllabus>"
    stats_all = []
    out, stats = llm.call(station="structure", tier="fast", system=PROMPT, user=user,
                          schema=StructureOut, effort="low", max_tokens=8000, think=False)
    stats_all.append(stats)
    problems = check(out, lines)
    if problems:  # one retry, telling Claude exactly what was wrong
        retry_user = user + "\n\nYour previous index had these problems; fix them:\n- " + "\n- ".join(problems)
        out, stats = llm.call(station="structure-retry", tier="fast", system=PROMPT, user=retry_user,
                              schema=StructureOut, effort="low", max_tokens=8000, think=False)
        stats_all.append(stats)
        problems = check(out, lines)
        if problems:
            raise llm.LLMError("structure_gate_failed", "; ".join(problems))
    return to_outline(out, lines), stats_all
