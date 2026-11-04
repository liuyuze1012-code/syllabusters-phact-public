"""Analyze pipeline, MVP version: Read → Map to CEPH → Find sources → Write edits → Supervisor.

Not yet in the MVP: 2b Rate AI, 2c Assessments.
`run_mvp` is what the playground calls. `run(payload)` is the AgentCore contract entrypoint.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from phact_contracts.agent import (AIRating, AnalyzeRequest, AnalyzeResponse, Assessments, Context, Meta,
                                   Outline, Workforce)

from retrieval import PassageStack, example_blocks, peer_examples
from pipeline.stages import run_stages
from steps import map_ceph, propose, strengthen, structure, supervise

AI_QUERIES = [
    ("Faculty should clearly define acceptable use of AI in courses: prohibition, restricted use, or transparent collaborative use", "AI-use policy"),
    ("Students should use AI tools followed by critical reflection on their use and limitations", "AI with reflection"),
    ("AI-powered simulations and applied AI skills in public health teaching", "AI in assignments"),
]


def analyze_outline(outline: Outline, confirmed: list[int], context: Context, ai_stance: str | None = None) -> dict:
    """The syllabus analysis as four stages on a Strands Graph (pipeline/stages.py), always in this order."""

    def map_stage(st):
        # Speed (Nov 4): the AI-policy searches don't depend on the CEPH mapping, so they run while Opus maps.
        with ThreadPoolExecutor(max_workers=1) as pool:
            mapping = pool.submit(map_ceph.run, outline, confirmed)
            specs = [{"query": q, "source_types": ["guidance"], "k": 3, "why": why} for q, why in AI_QUERIES]
            with ThreadPoolExecutor(max_workers=len(specs)) as searches:
                st["ai_fetched"] = list(zip(specs, searches.map(lambda sp: PassageStack._fetch(sp["query"], sp["source_types"], sp["k"]), specs)))
            st["competencies"], s = mapping.result()
        st["stats"] += s

    def retrieve_stage(st):
        stack = st["stack"] = PassageStack()
        for sp, hits in st.pop("ai_fetched"):
            stack._take(sp["query"], sp["source_types"], sp["why"], None, hits)
        gaps = [c for c in st["competencies"] if c.status in ("partial", "missing")][:5]
        specs = []
        for g in gaps:
            statement = map_ceph.CHECKLIST[g.id]["statement"]
            specs += [{"query": f"{statement} in public health teaching and assessment", "source_types": ["guidance", "workforce"], "k": 2, "why": f"CEPH #{g.id}"},
                      {"query": f"public health leaders and workforce need to {statement.lower()}", "source_types": ["workforce"], "k": 2, "why": f"workforce expectation #{g.id}"}]
        topics = "; ".join(map_ceph.CHECKLIST[g.id]["statement"] for g in gaps[:3]) or "AI-use policy and graded assignments"
        with ThreadPoolExecutor(max_workers=1) as pool:  # the per-gap searches and the peer-example search, in parallel
            peer = pool.submit(peer_examples, f"syllabus example: {topics}")
            ids = stack.add_many(specs)
            st["examples"] = peer.result()
        for i, g in enumerate(gaps):
            wf = ids[2 * i + 1]
            if wf:
                p = next(x for x in stack.passages if x.id == wf[0])
                g.workforce = Workforce(text=f"{p.title} › {p.section}", evidence=[wf[0]])

    def propose_stage(st):
        st["edits"], st["dropped"], s = propose.run(outline, st["competencies"], st["stack"].passages, context, ai_stance,
                                                    examples=example_blocks(st["examples"]))
        st["stats"] += s

    def supervise_stage(st):
        st["edits"], s = supervise.run(st["edits"], outline, st["stack"].passages, context, ai_stance)
        st["stats"] += s

    def strengthen_stage(st):  # Strands source-finder agents for flagged edits, re-checked by the Supervisor
        before = sum(e.supervisor == "flagged" for e in st["edits"])
        st["edits"], s, report = strengthen.run(st["edits"], outline, st["stack"], context, ai_stance)
        st["stats"] += s
        st["source_finder"] = {"flagged_before": before, "flagged_after": sum(e.supervisor == "flagged" for e in st["edits"]), "report": report}

    st = run_stages("syllabus-analysis", [("map_ceph", map_stage), ("retrieve", retrieve_stage),
                                          ("propose", propose_stage), ("supervise", supervise_stage),
                                          ("source_finder", strengthen_stage)], {"stats": []})
    return {"competencies": st["competencies"], "passages": st["stack"].passages, "edits": st["edits"], "dropped": st["dropped"],
            "searches": st["stack"].queries, "timings_ms": st["timings"], "stats": st["stats"], "examples": st["examples"],
            "orchestrator": st["orchestrator"], "source_finder": st.get("source_finder")}


def analyze_more(outline: Outline, new_ids: list[int], existing_edits: list, existing_passages: list,
                 context: Context, ai_stance: str | None = None) -> dict:
    """The professor adds competencies AFTER the first analysis. Only the new ones are mapped, searched
    and written for; existing edits, decisions and sources are untouched (no full re-analysis)."""
    timings, stats = {}, []
    t = time.monotonic()
    mapped, s = map_ceph.run(outline, new_ids)
    stats += s
    new_comps = [c for c in mapped if c.id in set(new_ids)]
    timings["map_ceph"] = int((time.monotonic() - t) * 1000)

    t = time.monotonic()
    stack = PassageStack(start=len(existing_passages) + 1, existing=existing_passages)
    gaps = [c for c in new_comps if c.status in ("partial", "missing")]
    new_pids = []
    for g in gaps:
        statement = map_ceph.CHECKLIST[g.id]["statement"]
        new_pids += stack.add(f"{statement} in public health teaching and assessment", ["guidance", "workforce"], k=2,
                              why=f"CEPH #{g.id} (added)")
        wf = stack.add(f"public health leaders and workforce need to {statement.lower()}", ["workforce"], k=2,
                       why=f"workforce expectation #{g.id}")
        new_pids += wf
        if wf:
            p = next(x for x in stack.passages if x.id == wf[0])
            g.workforce = Workforce(text=f"{p.title} › {p.section}", evidence=[wf[0]])
    timings["retrieve"] = int((time.monotonic() - t) * 1000)

    edits, dropped = [], []
    if gaps:  # a competency the syllabus already covers needs no edit
        t = time.monotonic()
        edits, dropped, s = propose.run(outline, gaps, stack.passages, context, ai_stance, existing=existing_edits)
        stats += s
        # never collide with an existing id, even if the model ignored the numbering
        taken = {e.edit_id for e in existing_edits}
        nxt = 1 + max((int(i[1:]) for i in taken if i[1:].isdigit()), default=0)
        rename = {}
        for e in edits:
            if e.edit_id in taken or e.edit_id in rename.values():
                rename[e.edit_id] = f"E{nxt}"
                nxt += 1
        for e in edits:
            e.edit_id = rename.get(e.edit_id, e.edit_id)
            e.requires = [rename.get(r, r) for r in e.requires]
        timings["propose"] = int((time.monotonic() - t) * 1000)
        t = time.monotonic()
        edits, s = supervise.run(edits, outline, stack.passages, context, ai_stance)
        stats += s
        timings["supervise"] = int((time.monotonic() - t) * 1000)
    old = {p.id for p in existing_passages}
    return {"competencies": new_comps, "new_passages": [p for p in stack.passages if p.id not in old],
            "edits": edits, "dropped": dropped, "searches": stack.queries, "timings_ms": timings, "stats": stats}


def run(payload: dict) -> dict:
    req = AnalyzeRequest.model_validate(payload)
    t0 = time.monotonic()
    outline, s1 = structure.run(req.syllabus_text)
    confirmed = req.confirmed_competencies or outline.claimed_competencies
    r = analyze_outline(outline, confirmed, req.context)
    stats = s1 + r["stats"]
    return AnalyzeResponse(
        job_id=req.job_id, outline=outline, competencies=r["competencies"],
        ai_rating=AIRating(score=0 if not outline.ai_policy else 2,
                           mode="unstated" if not outline.ai_policy else "restricted",
                           reasons=["MVP placeholder: Station 2b (Rate AI) is not built yet."]),
        assessments=Assessments(), edits=r["edits"], passages=r["passages"],
        meta=Meta(timings_ms={**r["timings_ms"], "total": int((time.monotonic() - t0) * 1000)},
                  models={s.station: s.model for s in stats},
                  tokens={"in": sum(s.input_tokens for s in stats), "out": sum(s.output_tokens for s in stats)}),
    ).model_dump()
