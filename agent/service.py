"""The PHACT agent as one service: every AI operation, JSON in → JSON out.

This is what runs on Amazon Bedrock AgentCore (agentcore_app.py wraps it). The API server calls it
through agent_client.py, either in-process (local dev) or on AgentCore (AWS), with the same inputs and
the same outputs, so both paths are interchangeable and testable.

The Safety gate (Comprehend PII scrub) stays in the API server, BEFORE anything reaches this service:
names and emails never leave the API, not even to our own agent runtime.

ops: warm, structure, classify, analyze, analyze_more, assessment_structure, assessment_analyze, chat
"""

from pydantic_core import to_jsonable_python

from phact_contracts.agent import ChatTurn, Context, Edit, Outline, Passage

from pipeline.analyze import analyze_more, analyze_outline
from pipeline.assess import analyze_assessment
from steps import assess_structure, chat, classify, structure


def _stats(stats) -> list[dict]:
    return [s.__dict__ if hasattr(s, "__dict__") else s for s in stats]


def _analysis(r: dict, passages_key: str = "passages") -> dict:
    return {"competencies": [c.model_dump() for c in r["competencies"]],
            passages_key: [p.model_dump() for p in r[passages_key]],
            "edits": [e.model_dump() for e in r["edits"]], "dropped": r["dropped"], "searches": r["searches"],
            "timings_ms": r["timings_ms"], "stats": _stats(r["stats"]), "examples": r.get("examples", []),
            "orchestrator": r.get("orchestrator"), "source_finder": r.get("source_finder")}


def handle(op: str, x: dict) -> dict:
    """Run one operation. Errors come back as {"error": {"type", "message"}} so the caller can map them."""
    try:
        if op == "warm":  # wakes this session's microVM ahead of an analysis (no model call)
            return {"ok": True}
        if op == "structure":
            if not x.get("with_info"):
                outline, stats = structure.run(x["text"])
                return {"outline": outline.model_dump(), "stats": _stats(stats)}
            from concurrent.futures import ThreadPoolExecutor
            from steps import course_info
            with ThreadPoolExecutor(max_workers=2) as pool:  # the course details read in parallel with the outline
                info_f = pool.submit(course_info.run, x["text"])
                outline, stats = structure.run(x["text"])
                try:
                    info, s2 = info_f.result()
                    info_d, stats = info.model_dump(), stats + [s2]
                except Exception:  # noqa: BLE001 — details are a convenience: blank fields, the professor fills them in
                    info_d = {}
            return {"outline": outline.model_dump(), "stats": _stats(stats), "info": info_d}
        if op == "classify":
            doc, stats = classify.run(x["text"])
            return {**doc.model_dump(), "stats": _stats([stats])}
        if op == "assessment_structure":
            outline, meta, stats = assess_structure.run(x["text"], x.get("type_hint"))
            return {"outline": outline.model_dump(), "meta": meta.model_dump(), "stats": _stats(stats)}
        ctx = Context.model_validate(x["context"]) if "context" in x else None
        if op == "analyze":
            return _analysis(analyze_outline(Outline.model_validate(x["outline"]), x["confirmed"], ctx, x.get("ai_stance")))
        if op == "assessment_analyze":
            return _analysis(analyze_assessment(Outline.model_validate(x["outline"]), x["meta"], x["confirmed"], ctx, x.get("ai_stance")))
        if op == "analyze_more":
            return _analysis(analyze_more(Outline.model_validate(x["outline"]), x["new_ids"], [Edit(**e) for e in x["edits"]],
                                          [Passage(**p) for p in x["passages"]], ctx, x.get("ai_stance")), "new_passages")
        if op == "chat":
            r = chat.run(x["message"], [ChatTurn(**t) for t in x.get("history", [])], Outline.model_validate(x["outline"]),
                         [Edit(**e) for e in x["edits"]], [Passage(**p) for p in x["passages"]], ctx, x.get("ai_stance"),
                         mode=x.get("mode", "syllabus"))
            return to_jsonable_python(r)
        return {"error": {"type": "unknown_op", "message": f"unknown operation {op!r}"}}
    except assess_structure.StudentWork as e:
        return {"error": {"type": "student_work", "message": str(e)}}
    except Exception as e:  # noqa: BLE001 — reported to the caller, never swallowed
        return {"error": {"type": type(e).__name__, "message": str(e)[:1000]}}
