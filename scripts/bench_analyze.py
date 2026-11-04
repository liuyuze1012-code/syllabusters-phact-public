"""Time the syllabus analysis, stage by stage, on the fictional sample syllabi (real Claude + KB calls).

    python scripts/bench_analyze.py [label] [n]     # label names the run (e.g. before / after); n syllabi (default 3)

Each syllabus is read once (cached), then analyze_outline runs exactly as the server calls it.
Prints, per syllabus: wall time, each stage, how many edits, and what failed PHACT's checks on the first
draft (the reason the repair pass runs). Appends one JSON line per run to agent/eval/out/bench.jsonl.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground")]
import server  # noqa: E402  (sets up the agent's import paths, make_context, extract)
from phact_contracts.agent import Outline  # noqa: E402
from steps import map_ceph, structure  # noqa: E402
import safety  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else "run"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
OUT = ROOT / "agent" / "eval" / "out"
OUT.mkdir(parents=True, exist_ok=True)
CACHE = OUT / "bench_outlines.json"
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

for path in sorted((ROOT / "data" / "test-syllabi" / "Synthetic").glob("*.docx"))[:n]:
    if path.name not in cache:
        clean, _, _ = safety.scrub(server.extract(path))
        outline, _ = structure.run(clean)
        cache[path.name] = outline.model_dump()
        CACHE.write_text(json.dumps(cache))
    outline = Outline.model_validate(cache[path.name])
    confirmed = outline.claimed_competencies or [1, 2, 3, 4]
    course = server.CourseIn(code="BENCH 1", name=path.stem, ai_stance="restricted", size=40,
                             notes="AI incorporation level chosen: Guided · AI supports inquiry, not final authorship.")
    t0 = time.monotonic()
    r = server.analyze_outline(outline, confirmed, server.make_context(course), course.ai_stance)
    wall = time.monotonic() - t0
    gate = [note for s in r["stats"] for note in s.notes if note.startswith("gate ")]
    row = {"label": label, "syllabus": path.name, "wall_s": round(wall, 1),
           "stages_s": {k: round(v / 1000, 1) for k, v in r["timings_ms"].items()},
           "edits": len(r["edits"]), "dropped": len(r["dropped"]), "retry": any(s.station == "propose-fix" for s in r["stats"]),
           "first_pass_failures": gate, "out_tokens": sum(s.output_tokens for s in r["stats"]),
           "orchestrator": (r.get("orchestrator") or {}).get("name", "plain")}
    with (OUT / "bench.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(f"{path.name} [{row['orchestrator']}]: {row['wall_s']} s · {row['stages_s']} · {row['edits']} edits, {row['dropped']} dropped, retry={row['retry']}")
    for g in gate:
        print("   ", g[:220])
