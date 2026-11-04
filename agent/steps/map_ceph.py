"""Station 2a: Map to CEPH. Rates each confirmed competency covered / partial / missing.

Model: strong (Opus 5.5), effort medium. Call: one structured-output call. Prompt: prompts/map_ceph.md.
Only the competencies assigned to this course are sent to Claude; code fills the rest as
not_assigned, so the result always has all 22 (the contract requires it).
Gate: every confirmed id answered exactly once, evidence ids exist, and "covered" must point
at a section that holds a GRADED assignment (otherwise code downgrades it to partial).
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from phact_contracts.agent import CompetencyResult, Outline

import llm

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (ROOT / "prompts" / "map_ceph.md").read_text()
_checklist_path = ROOT / "data" / "ceph_competencies.json"
if not _checklist_path.exists():  # during development, read it straight from the knowledge base folder
    _checklist_path = ROOT.parent / "knowledge-base" / "checklist" / "ceph_competencies.json"
CHECKLIST = {c["id"]: c for c in json.loads(_checklist_path.read_text())["competencies"]}


class Judgment(BaseModel):
    id: int
    status: Literal["covered", "partial", "missing"]
    evidence_section_ids: list[str]
    reason: str
    rule_applied: str | None = None


class MapOut(BaseModel):
    results: list[Judgment]


def _competency_block(cid: int) -> str:
    c = CHECKLIST[cid]
    interp = "\n".join(f"- {t}" for t in c["interpretation"])
    dnc = "\n".join(f"- {t}" for t in c["does_not_count"]) or "- (none listed)"
    return (f'<competency id="{cid}" domain="{c["domain"]}">\n{c["statement"]}\n'
            f"<interpretation>\n{interp}\n</interpretation>\n<does_not_count>\n{dnc}\n</does_not_count>\n</competency>")


def _syllabus_blocks(outline: Outline) -> str:
    secs = "\n".join(f'<section id="{s.id}" kind="{s.kind}" title="{s.title}">\n{s.text}\n</section>'
                     for s in outline.sections)
    asg = "\n".join(f'<assignment id="{a.id}" section="{a.section_id}" assessed="{str(a.assessed).lower()}" '
                    f'weight="{a.weight if a.weight is not None else "unknown"}">{a.title}: {a.what_it_tests}</assignment>'
                    for a in outline.assignments)
    return f"{secs}\n{asg}"


def run(outline: Outline, confirmed: list[int], doc_note: str = "") -> tuple[list[CompetencyResult], list[llm.CallStats]]:
    confirmed = sorted({c for c in confirmed if c in CHECKLIST})
    results = {i: CompetencyResult(id=i, status="not_assigned", reason="Not assigned to this course")
               for i in range(1, 23)}
    if not confirmed:
        return list(results.values()), []

    user = ("\n".join(_competency_block(c) for c in confirmed) + "\n\n" + _syllabus_blocks(outline)
            + (f"\n\n<document_note>{doc_note}</document_note>" if doc_note else "")
            + f"\n\nJudge exactly these competencies: {confirmed}.")
    out, stats = llm.call(station="map_ceph", tier="strong", system=PROMPT, user=user,
                          schema=MapOut, effort="medium", max_tokens=12000)

    section_ids = {s.id for s in outline.sections}
    graded_sections = {a.section_id for a in outline.assignments if a.assessed}
    graded_titles = [a.title.lower() for a in outline.assignments if a.assessed]
    text_of = {s.id: s.text.lower() for s in outline.sections}

    for j in out.results:
        if j.id not in confirmed:
            continue
        evidence = [e for e in j.evidence_section_ids if e in section_ids]
        status, reason = j.status, j.reason
        if status == "covered":
            backed = any(e in graded_sections or any(t[:25] in text_of[e] for t in graded_titles) for e in evidence)
            if not backed:  # the CEPH rule in code: "covered" needs a graded assignment
                status = "partial"
                reason += " (PHACT check: no graded assignment found in the cited sections, so marked partial.)"
        results[j.id] = CompetencyResult(id=j.id, status=status, evidence=evidence, reason=reason, rule=j.rule_applied)

    missing_answers = [c for c in confirmed if results[c].status == "not_assigned"]
    for c in missing_answers:  # Claude skipped one: say so honestly rather than guess
        results[c] = CompetencyResult(id=c, status="missing", reason="PHACT could not get a judgment for this competency; review manually.")
    return list(results.values()), [stats]
