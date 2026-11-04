"""Station 4: Write edits. Opus proposes edits that may cite only the passages it was given.

Model: strong (Opus 5.5), effort medium. Prompt: prompts/propose.md.
Gate: gates.check_edit on every edit. Failing edits get ONE retry with the exact problems;
edits that still fail are dropped (and reported), never shown as if they were fine.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from phact_contracts.agent import CompetencyResult, Context, Edit, Evidence, Outline, Passage

import gates
import llm

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "propose.md").read_text()


class DraftEdit(BaseModel):
    edit_id: str
    section_id: str
    op: Literal["replace", "insert_after", "delete"]
    original: str | None = None
    proposed: str | None = None
    rationale: str
    evidence_ids: list[str] = []
    school_rule: str | None = None
    ceph: list[int] = []
    reflection_activity: str | None = None
    requires: list[str] = []
    aias_level: int | None = None
    ai_role: str | None = None
    rubric_row: str | None = None
    ai_use_statement: str | None = None
    practicalities: str | None = None
    purpose: Literal["ai_incorporation", "workforce", "competency"] | None = None


class ProposeOut(BaseModel):
    edits: list[DraftEdit]


def passage_blocks(passages: list[Passage]) -> str:
    return "\n".join(f'<passage id="{p.id}" title="{p.title}" section="{p.section or ""}">\n{p.snippet}\n</passage>'
                     for p in passages)


def context_blocks(context: Context) -> str:
    rules = "\n".join(f'<school_rule id="{r.id}">{r.text}</school_rule>' for r in context.school_rules)
    return f"{rules}\n<professor>{context.professor or 'No stated preferences.'}\nMemory: {context.memory or 'none'}</professor>"


def to_edit(d: DraftEdit, passages: list[Passage], version: int = 1) -> Edit:
    by_id = {p.id: p for p in passages}
    return Edit(edit_id=d.edit_id, version=version, section_id=d.section_id, op=d.op, original=d.original,
                proposed=d.proposed, rationale=d.rationale,
                evidence=[Evidence(id=i, title=f"{by_id[i].title} › {by_id[i].section}" if by_id[i].section else by_id[i].title,
                                   snippet=by_id[i].snippet, uri=by_id[i].uri) for i in d.evidence_ids if i in by_id],
                school_rule=d.school_rule, ceph=d.ceph, reflection_activity=d.reflection_activity,
                requires=[r for r in d.requires if r != d.edit_id], supervisor="not_run", status="draft",
                aias_level=d.aias_level if d.aias_level and 1 <= d.aias_level <= 5 else None, ai_role=d.ai_role,
                rubric_row=d.rubric_row, ai_use_statement=d.ai_use_statement, practicalities=d.practicalities,
                purpose=d.purpose)


def fix_rule(d: DraftEdit, rule_ids: set[str]) -> DraftEdit:
    """Opus sometimes writes two rules in one field ("DEF-AI-1, DEF-AI-2"), which rejected a good edit
    (Nov 3). Keep the first known id; an unknown one is still left for the gate to reject."""
    if d.school_rule and d.school_rule not in rule_ids:
        known = [r.strip() for r in d.school_rule.replace(";", ",").split(",") if r.strip() in rule_ids]
        if known:
            d.school_rule = known[0]
    return d


def gate_all(drafts: list[DraftEdit], outline: Outline, passages: list[Passage], rule_ids: set[str],
             ai_stance: str | None = None):
    good, bad = [], []
    for d in drafts:
        fix_rule(d, rule_ids)
        problems = gates.check_edit(d.model_dump(), outline, passages, rule_ids, ai_stance)
        (bad if problems else good).append((d, problems))
    return good, bad


def run(outline: Outline, competencies: list[CompetencyResult], passages: list[Passage],
        context: Context, ai_stance: str | None = None,
        existing: list[Edit] | None = None, examples: str = "") -> tuple[list[Edit], list[dict], list[llm.CallStats]]:
    """existing: edits the professor already has (adding a competency later). Then PHACT writes edits
    ONLY for the given gaps, sees the existing ones so it doesn't repeat them, and may link to them."""
    gaps = [c for c in competencies if c.status in ("partial", "missing")]
    sections = "\n".join(f'<section id="{s.id}" kind="{s.kind}" title="{s.title}">\n{s.text}\n</section>'
                         for s in outline.sections)
    gap_blocks = "\n".join(f'<gap id="{g.id}" status="{g.status}">{g.reason}</gap>' for g in gaps) or "<gap>none</gap>"
    ai = f"<ai_status>{'The syllabus has this AI policy: ' + outline.ai_policy if outline.ai_policy else 'The syllabus has NO AI-use policy.'}</ai_status>"
    stance = f"<course_ai_stance>{ai_stance or 'not stated: follow <professor>'}</course_ai_stance>"
    user = f"{sections}\n\n{gap_blocks}\n{ai}\n{stance}\n\n{passage_blocks(passages)}\n\n{context_blocks(context)}{examples}"
    if existing:
        nxt = 1 + max((int(e.edit_id[1:]) for e in existing if e.edit_id[1:].isdigit()), default=0)
        user += ("\n\n<existing_edits>\n" + "\n".join(
            f'<edit id="{e.edit_id}" section="{e.section_id}">{(e.proposed or e.op)[:300]}</edit>' for e in existing)
            + f"\n</existing_edits>\nThe professor just added the competencies in the <gap> blocks to a course that "
            f"already has the edits above. Those edits stay. Write edits ONLY for these new gaps (1 to 3 edits). Don't "
            f"repeat or redo anything an existing edit covers, including the AI-use policy. If a new edit depends on an "
            f"existing one, list it in `requires`. Number new edits from E{nxt}.")
    rule_ids = {r.id for r in context.school_rules}
    stats_all = []

    out, stats = llm.call(station="propose", tier="strong", system=PROMPT, user=user,
                          schema=ProposeOut, effort="medium", max_tokens=14000)
    stats_all.append(stats)
    good, bad = gate_all(out.edits, outline, passages, rule_ids, ai_stance)

    dropped = []
    # what failed the first pass, kept in the stats so the cost of the retry is visible (and fixable)
    stats.notes += [f"gate {d.edit_id}: {p}" for d, ps in bad for p in ps]
    if bad:  # one retry, only for the failing edits, telling Opus exactly what was wrong
        fix = "\n".join(f"- {d.edit_id} ({d.section_id}): " + "; ".join(p) for d, p in bad)
        retry_user = (user + "\n\nThese edits failed PHACT's checks. Return corrected versions of ONLY these edits "
                      f"(same edit_id), or omit an edit if it can't be fixed honestly:\n{fix}")
        out2, stats = llm.call(station="propose-fix", tier="strong", system=PROMPT, user=retry_user,
                               schema=ProposeOut, effort="medium", max_tokens=10000)
        stats_all.append(stats)
        good2, bad2 = gate_all(out2.edits, outline, passages, rule_ids, ai_stance)
        fixed_ids = {d.edit_id for d, _ in good2}
        good += good2
        dropped = [{"edit_id": d.edit_id, "problems": p} for d, p in bad if d.edit_id not in fixed_ids]
        dropped += [{"edit_id": d.edit_id, "problems": p} for d, p in bad2]

    # An edit that needs a failed edit is half of a pair (a new 10% task without the rebalance → 110%):
    # drop it too rather than show something that breaks the syllabus if accepted alone.
    good = [d for d, _ in good]
    keep_ids = {e.edit_id for e in existing or []}
    while True:
        ids = {d.edit_id for d in good} | keep_ids
        orphans = [d for d in good if any(r not in ids for r in d.requires)]
        if not orphans:
            break
        for d in orphans:
            dropped.append({"edit_id": d.edit_id, "problems": [f"needs {', '.join(r for r in d.requires if r not in ids)}, which failed checks"]})
        good = [d for d in good if d not in orphans]
    return [to_edit(d, passages) for d in good], dropped, stats_all
