"""Station 5: Supervisor. One fast call per edit, all in parallel (the ARIE "double-check" idea).

Model: fast (Haiku 5.5), thinking on, effort low. Prompt: prompts/supervise.md.
Code then acts on the verdict:
  - citations the Supervisor says don't support the edit are REMOVED from its evidence
  - if none are left, or the verdict is "flag", the edit is marked supervisor="flagged" with the reason
  - otherwise supervisor="pass" (the UI's verification badge only shows for a check that actually ran)
Flagged edits stay visible: the professor decides, with the reason in front of them.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from phact_contracts.agent import Context, Edit, Outline, Passage

import llm

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "supervise.md").read_text()


class Verdict(BaseModel):
    verdict: Literal["pass", "flag"]
    supported_ids: list[str]
    reason: str


def _check(edit: Edit, outline: Outline, passages: dict[str, Passage], context: Context,
           ai_stance: str | None) -> tuple[Edit, llm.CallStats | None]:
    section = next((s for s in outline.sections if s.id == edit.section_id), None)
    cited = [passages[e.id] for e in edit.evidence if e.id in passages]
    user = (f'<edit id="{edit.edit_id}" section="{edit.section_id}" op="{edit.op}">\n'
            f"original: {edit.original}\nproposed: {edit.proposed}\nrationale: {edit.rationale}\n"
            f"reflection: {edit.reflection_activity}\n"
            + (f"AIAS level: {edit.aias_level}\nai_role: {edit.ai_role}\nrubric_row: {edit.rubric_row}\n"
               f"ai_use_statement: {edit.ai_use_statement}\npracticalities: {edit.practicalities}\n" if edit.aias_level else "")
            + "</edit>\n"
            + "\n".join(f'<passage id="{p.id}" title="{p.title}" section="{p.section or ""}">\n{p.snippet}\n</passage>' for p in cited)
            + (f'\n<section id="{section.id}">\n{section.text[:3000]}\n</section>' if section else "")
            + "\n" + "\n".join(f'<school_rule id="{r.id}">{r.text}</school_rule>' for r in context.school_rules)
            + f"\n<course_ai_stance>{ai_stance or 'not stated'}</course_ai_stance>")
    try:
        v, stats = llm.call(station=f"supervise-{edit.edit_id}", tier="fast", system=PROMPT, user=user,
                            schema=Verdict, effort="low", max_tokens=4000)
    except llm.LLMError as e:  # the check itself failed: say so, never pretend it passed
        return edit.model_copy(update={"supervisor": "not_run", "supervisor_note": f"Supervisor check failed ({e.code})."}), None

    kept = [ev for ev in edit.evidence if ev.id in set(v.supported_ids)]
    removed = [ev.id for ev in edit.evidence if ev not in kept]
    notes = []
    if removed:
        notes.append(f"Removed citation(s) {', '.join(removed)}: they don't support this edit.")
    if not kept:
        verdict, notes = "flagged", notes + ["No cited ASPPH passage supports this edit; treat it as an AI suggestion."]
    elif v.verdict == "flag":
        verdict, notes = "flagged", notes + [v.reason]
    else:
        verdict = "pass"
    return edit.model_copy(update={"evidence": kept, "supervisor": verdict,
                                   "supervisor_note": " ".join(notes) or None}), stats


def run(edits: list[Edit], outline: Outline, passages: list[Passage], context: Context,
        ai_stance: str | None = None) -> tuple[list[Edit], list[llm.CallStats]]:
    if not edits:
        return [], []
    by_id = {p.id: p for p in passages}
    with ThreadPoolExecutor(max_workers=min(8, len(edits))) as pool:
        results = list(pool.map(lambda e: _check(e, outline, by_id, context, ai_stance), edits))
    return [e for e, _ in results], [s for _, s in results if s]
