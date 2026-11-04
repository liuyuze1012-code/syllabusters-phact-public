"""Assessment pipeline (semester agent): Read → Map → Find patterns + sources → Write → Gates → Supervisor.

The same stations as the syllabus pipeline, specialised for one graded assessment:
- map_ceph judges whether completing THIS assessment demonstrates each course competency
- retrieval adds PHACT pattern cards (source_type practice) filtered by material type and the course's
  highest allowed AIAS level, plus the AIAS reference card and ASPPH guidance
- the writer (prompts/propose_assessment.md) must produce the 8-part design; gates.check_suggestion
  enforces it on top of the usual edit gates
"""

from pathlib import Path

from phact_contracts.agent import Context, Outline, Workforce

import aias
import gates
import llm
from pipeline.stages import run_stages
from retrieval import PassageStack, example_blocks, peer_examples
from steps import map_ceph, strengthen, supervise
from steps.propose import ProposeOut, context_blocks, fix_rule, passage_blocks, to_edit

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "propose_assessment.md").read_text()


def _gate(d, outline, passages, rule_ids, ai_stance):
    fix_rule(d, rule_ids)
    data = d.model_dump()
    return gates.check_edit(data, outline, passages, rule_ids, ai_stance) + gates.check_suggestion(data, ai_stance)


def analyze_assessment(outline: Outline, meta: dict, confirmed: list[int], context: Context,
                       ai_stance: str | None = None) -> dict:
    """The assessment analysis as four stages on a Strands Graph (pipeline/stages.py), always in this order."""
    mtype, cap = meta.get("material_type", "homework"), aias.max_level(ai_stance)
    topic = f"{meta.get('title', '')}: {meta.get('what_it_tests', '')}"

    def map_stage(st):
        note = (f'This is ONE graded {mtype} ("{meta.get("title", "")}"), not a syllabus. Judge whether completing THIS '
                "assessment requires students to demonstrate each competency. Each `task` section is a graded part.")
        st["competencies"], s = map_ceph.run(outline, confirmed, doc_note=note)
        st["stats"] += s

    def retrieve_stage(st):
        stack = st["stack"] = PassageStack()
        stack.add("AI Assessment Scale levels: no AI, AI planning, AI collaboration, full AI, AI exploration",
                  ["practice"], k=1, why="AIAS reference", extra=[{"equals": {"key": "doc_id", "value": "aias-levels"}}])
        allowed = [{"lessThanOrEquals": {"key": "aias_level", "value": cap}}]
        kept = stack.add(f"{mtype} assessment design with AI: {topic}", ["practice"], k=3, why=f"patterns for this {mtype}",
                         extra=allowed + [{"equals": {"key": "material_type", "value": mtype}}])
        if len(kept) < 2:  # few cards for this type yet: widen to any type, still within the allowed level
            stack.add(f"assessment design with AI: {topic}", ["practice"], k=3, why="patterns, any type", extra=allowed)
        st["gaps"] = gaps = [c for c in st["competencies"] if c.status in ("partial", "missing")][:4]
        for g in gaps:
            statement = map_ceph.CHECKLIST[g.id]["statement"]
            stack.add(f"assessment where students {statement.lower()}", ["practice"], k=2, why=f"pattern for CEPH #{g.id}",
                      extra=allowed)
            stack.add(f"{statement} in public health teaching and assessment", ["guidance", "workforce"], k=2,
                      why=f"CEPH #{g.id}")
            wf = [p for p in stack.passages if p.source_type == "workforce"]
            if wf:
                g.workforce = Workforce(text=f"{wf[-1].title} › {wf[-1].section}", evidence=[wf[-1].id])
        stack.add("students use AI tools followed by critical reflection on their limitations", ["guidance"], k=2,
                  why="AI with reflection")
        st["examples"] = peer_examples(f"{mtype} assessment example: {topic}")

    def propose_stage(st):
        stack, gaps = st["stack"], st["gaps"]
        sections = "\n".join(f'<section id="{x.id}" kind="{x.kind}" title="{x.title}">\n{x.text}\n</section>' for x in outline.sections)
        gap_blocks = "\n".join(f'<gap id="{g.id}" status="{g.status}">{g.reason}</gap>' for g in gaps) or "<gap>none</gap>"
        head = (f'<assessment type="{mtype}" title="{meta.get("title", "")}" weight="{meta.get("weight")}" '
                f'points="{meta.get("points")}">Current AI rule: {meta.get("ai_rule") or "none stated"}</assessment>')
        user = (f"{sections}\n\n{head}\n{gap_blocks}\n<course_ai_stance>{ai_stance or 'restricted'}</course_ai_stance>\n"
                f"<aias_allowed>up to level {cap} ({aias.label(cap)})</aias_allowed>\n\n{passage_blocks(stack.passages)}\n\n"
                f"{context_blocks(context)}") + example_blocks(st["examples"])
        rule_ids = {r.id for r in context.school_rules}
        out, s = llm.call(station="propose-assessment", tier="strong", system=PROMPT, user=user,
                          schema=ProposeOut, effort="medium", max_tokens=16000,
                          timeout_s=180)  # full 8-part designs are long: ~3x the old edits
        st["stats"].append(s)
        graded = [(d, _gate(d, outline, stack.passages, rule_ids, ai_stance)) for d in out.edits]
        good = [d for d, p in graded if not p]
        bad = [(d, p) for d, p in graded if p]
        s.notes += [f"gate {d.edit_id}: {x}" for d, ps in bad for x in ps]
        st["dropped"] = []
        if bad:  # one retry for the failing changes, with the exact problems
            fix = "\n".join(f"- {d.edit_id} ({d.section_id}): " + "; ".join(p) for d, p in bad)
            out2, s = llm.call(station="propose-assessment-fix", tier="strong", system=PROMPT, schema=ProposeOut,
                               user=user + "\n\nThese changes failed PHACT's checks. Return corrected versions of ONLY these "
                               f"(same edit_id), complete in every part, or omit one that can't be fixed honestly:\n{fix}",
                               effort="medium", max_tokens=12000, timeout_s=150)
            st["stats"].append(s)
            fixed = {d.edit_id: d for d in out2.edits if not _gate(d, outline, stack.passages, rule_ids, ai_stance)}
            good += list(fixed.values())
            st["dropped"] = [{"edit_id": d.edit_id, "problems": p} for d, p in bad if d.edit_id not in fixed]
        ids = {d.edit_id for d in good}
        for d in good:
            d.requires = [r for r in d.requires if r in ids]
        st["edits"] = [to_edit(d, stack.passages) for d in good]

    def supervise_stage(st):
        st["edits"], s = supervise.run(st["edits"], outline, st["stack"].passages, context, ai_stance)
        st["stats"] += s

    def strengthen_stage(st):  # Strands source-finder agents for flagged edits, re-checked by the Supervisor
        before = sum(e.supervisor == "flagged" for e in st["edits"])
        st["edits"], s, report = strengthen.run(st["edits"], outline, st["stack"], context, ai_stance)
        st["stats"] += s
        st["source_finder"] = {"flagged_before": before, "flagged_after": sum(e.supervisor == "flagged" for e in st["edits"]), "report": report}

    st = run_stages("assessment-analysis", [("map_ceph", map_stage), ("retrieve", retrieve_stage),
                                            ("propose", propose_stage), ("supervise", supervise_stage),
                                          ("source_finder", strengthen_stage)], {"stats": []})
    return {"competencies": st["competencies"], "passages": st["stack"].passages, "edits": st["edits"], "dropped": st["dropped"],
            "searches": st["stack"].queries, "timings_ms": st["timings"], "stats": st["stats"], "examples": st["examples"],
            "orchestrator": st["orchestrator"], "source_finder": st.get("source_finder")}
