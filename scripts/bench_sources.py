"""Does the source finder fix weak sources, how long does it take, and are its sources really right?

    python scripts/bench_sources.py [n]      # n sample syllabi (default 3) + one homework assessment

Per document (one real analysis each, source finder on):
  flags       flagged by the Supervisor before → after the source finder (same run: a paired before/after)
  time        the source-finder stage vs the whole analysis
  accuracy    an independent Opus judge (not the Supervisor) rates whether the cited passages DIRECTLY support
              each change: every finder-verified edit, and the edits that passed on the first try for comparison
Writes agent/eval/out/bench_sources.json.
"""

import json
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground")]
import server  # noqa: E402  (first: it puts the agent's modules on the import path)
import llm  # noqa: E402
import safety  # noqa: E402
import service  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
OUT = ROOT / "agent" / "eval" / "out"
cache = json.loads((OUT / "bench_outlines.json").read_text())


class Support(BaseModel):
    verdict: Literal["direct", "partial", "none"]
    why: str


JUDGE = """You check citations for a public health syllabus tool. Given one recommended change and the ASPPH passages
cited for it, decide whether the passages DIRECTLY support the specific change ("direct"), only the general topic
("partial"), or not at all ("none"). Be strict: topical overlap is "partial". why: one sentence."""


def judge(e: dict) -> str:
    cites = "\n".join(f'<passage title="{x["title"]}">{x["snippet"][:1500]}</passage>' for x in e["evidence"])
    v, _ = llm.call(station="bench-judge", tier="strong", system=JUDGE, schema=Support, effort="low", max_tokens=3000,
                    user=f"<change>{e['proposed']}\nwhy: {e['rationale']}</change>\n{cites}")
    return v.verdict


rows, docs = [], []
for name in sorted(cache)[:n]:
    docs.append((name, "analyze", {"outline": cache[name], "confirmed": cache[name].get("claimed_competencies") or [1, 2, 3, 4]}))
hw = server.extract(ROOT / "data/test-assessments/EPID601_Homework_ProblemSet3.docx")
s = service.handle("assessment_structure", {"text": safety.scrub(hw)[0], "type_hint": "homework"})
docs.append(("EPID601 homework", "assessment_analyze", {"outline": s["outline"], "meta": s["meta"], "confirmed": [1, 2, 3, 4]}))

for name, op, x in docs:
    ctx = server.make_context(server.CourseIn(code="BENCH 2", name=name, size=40, ai_stance="restricted")).model_dump()
    t = time.monotonic()
    r = service.handle(op, {**x, "context": ctx, "ai_stance": "restricted"})
    wall = time.monotonic() - t
    if r.get("error"):
        print(name, "ERROR", r["error"]); continue
    sf = r.get("source_finder") or {}
    rep = {d["edit_id"]: d for d in sf.get("report", [])}
    verified = [e for e in r["edits"] if rep.get(e["edit_id"], {}).get("outcome") == "verified"]
    first_pass = [e for e in r["edits"] if e["supervisor"] == "pass" and e["edit_id"] not in rep]
    row = {"doc": name, "edits": len(r["edits"]), "flagged_before": sf.get("flagged_before", 0), "flagged_after": sf.get("flagged_after", 0),
           "outcomes": [d["outcome"] for d in rep.values()], "searches": sum(d["searches"] for d in rep.values()),
           "total_s": round(wall, 1), "finder_s": round(r["timings_ms"].get("source_finder", 0) / 1000, 1),
           "judge_finder": [judge(e) for e in verified], "judge_first_pass": [judge(e) for e in first_pass]}
    rows.append(row)
    print(json.dumps(row), flush=True)
(OUT / "bench_sources.json").write_text(json.dumps(rows, indent=1))
tot = lambda k: sum(r[k] for r in rows)
jf = [v for r in rows for v in r["judge_finder"]]; jp = [v for r in rows for v in r["judge_first_pass"]]
print(f"\nflagged: {tot('flagged_before')} → {tot('flagged_after')} of {tot('edits')} edits")
print(f"time: source finder {tot('finder_s'):.0f}s of {tot('total_s'):.0f}s total ({100 * tot('finder_s') / max(1, tot('total_s')):.0f}%)")
print(f"judge, finder-verified: {jf.count('direct')} direct / {jf.count('partial')} partial / {jf.count('none')} none")
print(f"judge, passed first try: {jp.count('direct')} direct / {jp.count('partial')} partial / {jp.count('none')} none")
