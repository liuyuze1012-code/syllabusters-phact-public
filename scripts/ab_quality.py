"""A/B: does a change to the propose prompt change recommendation quality? (real Claude + KB calls)

    python scripts/ab_quality.py <old_prompt_file> [n]

For each of the first n fictional sample syllabi, runs the full analysis twice on the same outline and
competencies: once with the old propose prompt (A), once with the current one (B). Saves both edit sets
to agent/eval/out/ab/<syllabus>.json and prints objective metrics. Then a blind judge (Opus) compares
the two sets with the labels shuffled, on a fixed rubric.
"""

import json
import random
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground")]
import server  # noqa: E402
import llm  # noqa: E402
from phact_contracts.agent import Outline  # noqa: E402
from steps import propose  # noqa: E402

OLD, NEW = Path(sys.argv[1]).read_text(), propose.PROMPT
n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
OUT = ROOT / "agent" / "eval" / "out" / "ab"
OUT.mkdir(parents=True, exist_ok=True)
cache = json.loads((ROOT / "agent" / "eval" / "out" / "bench_outlines.json").read_text())


def metrics(r):
    e = r["edits"]
    return {"edits": len(e), "dropped": len(r["dropped"]), "retry": any(s.station == "propose-fix" for s in r["stats"]),
            "supervisor_pass": sum(x.supervisor == "pass" for x in e), "flagged": sum(x.supervisor == "flagged" for x in e),
            "citations": sum(len(x.evidence) for x in e), "with_reflection": sum(bool(x.reflection_activity) for x in e),
            "competencies_targeted": sorted({c for x in e for c in x.ceph}), "proposed_words": sum(len((x.proposed or "").split()) for x in e)}


def brief(edits):
    return "\n\n".join(f"[{x.edit_id}] section={x.section_id} op={x.op} CEPH={x.ceph} supervisor={x.supervisor}\n"
                       f"ORIGINAL: {x.original}\nPROPOSED: {x.proposed}\nREFLECTION: {x.reflection_activity}\nWHY: {x.rationale}\n"
                       f"SOURCES: {'; '.join(ev.title for ev in x.evidence)}" for x in edits)


class Judgment(BaseModel):
    specificity: str  # "X", "Y" or "tie"
    closes_competency_gaps: str
    ai_policy_quality: str
    fit_and_workload: str
    source_honesty: str
    overall: str
    reason: str


JUDGE = """You compare two sets of recommended edits (X and Y) to the same public health syllabus, written by
two versions of an AI assistant for a professor. Judge as an experienced public health faculty member and
CEPH accreditation reviewer. For each criterion answer exactly "X", "Y" or "tie" (use tie when the difference
is small or a matter of taste): specificity (concrete enough to paste in), closes_competency_gaps (turns gaps
into graded, CEPH-meeting work), ai_policy_quality (clear, fair AI-use policy that fits the course's
restricted stance: brainstorming and editing only, disclosed), fit_and_workload (matches the syllabus's
format and length, reasonable workload), source_honesty (claims match the cited ASPPH sources), overall.
reason: 2-3 sentences on the biggest difference."""

rows = []
for name in sorted(cache)[:n]:
    outline = Outline.model_validate(cache[name])
    confirmed = outline.claimed_competencies or [1, 2, 3, 4]
    course = server.CourseIn(code="AB 1", name=name, ai_stance="restricted", size=40,
                             notes="AI incorporation level chosen: Guided · AI supports inquiry, not final authorship.")
    res = {}
    for arm, prompt in (("A_old", OLD), ("B_new", NEW)):
        propose.PROMPT = prompt
        res[arm] = server.analyze_outline(outline, confirmed, server.make_context(course), course.ai_stance)
    propose.PROMPT = NEW
    (OUT / f"{name}.json").write_text(json.dumps({arm: [x.model_dump() for x in r["edits"]] for arm, r in res.items()}, indent=1))
    flip = random.random() < 0.5
    x, y = (res["B_new"], res["A_old"]) if flip else (res["A_old"], res["B_new"])
    j, _ = llm.call(station="ab-judge", tier="strong", system=JUDGE, schema=Judgment, effort="medium", max_tokens=6000,
                    user=f"<syllabus_sections>\n{chr(10).join(s.title for s in outline.sections)}\n</syllabus_sections>\n\n<set_X>\n{brief(x['edits'])}\n</set_X>\n\n<set_Y>\n{brief(y['edits'])}\n</set_Y>",
                    timeout_s=180)
    unblind = lambda v: v if v == "tie" else ({"X": "B_new", "Y": "A_old"} if flip else {"X": "A_old", "Y": "B_new"}).get(v, v)
    verdict = {k: unblind(v) for k, v in j.model_dump().items() if k != "reason"}
    row = {"syllabus": name, "A_old": metrics(res["A_old"]), "B_new": metrics(res["B_new"]), "judge": verdict, "reason": j.reason}
    rows.append(row)
    print(json.dumps(row, indent=1), flush=True)
(OUT / "summary.json").write_text(json.dumps(rows, indent=1))
