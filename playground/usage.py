"""Agent monitoring: one small usage record per AI job, and the numbers ASPPH's Agent monitor shows.

The worker writes a record after every job (jobs.run). It holds COUNTS AND TIMES ONLY: which operation, which
university, how long each pipeline stage took, tokens per model, how many suggestions and flags. Never syllabus
text, never names or emails. The admin console reads them through /api/admin/monitor.

DynamoDB (table phact-app):  USAGE#<YYYY-MM-DD>  <iso time>#<job id>   (one partition per day; kept ~13 months)
"""

import math
import time
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

import userdata

TTL_DAYS = 400
# Estimate only: USD per million tokens. Haiku 5.5 is Bedrock's published standard rate (prompts under 100K tokens);
# Opus 5.5 is Anthropic's list price (no separate Bedrock table found). Checked Nov 4, 2026: update when prices change.
PRICES = {"opus": (4.00, 20.00), "haiku": (0.10, 0.50)}
PRICE_NOTE = "Estimate: Haiku 5.5 $0.10/$0.50 and Opus 5.5 $4/$20 per million input/output tokens (list prices, Nov 4, 2026)."
OPS = {"/api/analyze": "Syllabus analysis", "/api/assessment/analyze": "Assessment analysis", "/api/analyze_more": "Add competencies",
       "/api/chat": "Chat revision", "/api/structure": "Read syllabus", "/api/assessment/structure": "Read assessment",
       "/api/classify": "Detect document type", "/api/extract": "Extract text",
       "/api/uni/policy/extract": "Read AI policy document"}
ANALYSES = ("/api/analyze", "/api/assessment/analyze")


def family(model: str) -> str:
    m = (model or "").lower()
    return "opus" if "opus" in m else "haiku" if "haiku" in m else "other"


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(family(model), (0.0, 0.0))
    return (tokens_in * pin + tokens_out * pout) / 1e6


def build(job_id: str, path: str, user: dict, http_status: int, wall_ms: int, body: dict | None, error: str = "",
          at: datetime | None = None) -> dict:
    """The record for one job. `body` is the route's JSON result (stats, timings, edits…), or None if it failed."""
    at = at or datetime.now(timezone.utc)
    body = body if isinstance(body, dict) else {}
    models: dict[str, dict] = {}
    for s in body.get("stats") or []:
        m = models.setdefault(s.get("model") or "unknown", {"calls": 0, "in": 0, "out": 0, "ms": 0})
        m["calls"] += 1
        m["in"] += int(s.get("input_tokens") or 0)
        m["out"] += int(s.get("output_tokens") or 0)
        m["ms"] += int(s.get("latency_ms") or 0)
    edits = body.get("edits") or []
    sf = body.get("source_finder") or {}
    ok = http_status < 400 and not error
    return {
        "PK": f"USAGE#{at:%Y-%m-%d}", "SK": f"{at.isoformat(timespec='milliseconds')}#{job_id}",
        "job_id": job_id, "op": path, "at": at.isoformat(timespec="seconds"), "status": "DONE" if ok else "FAILED",
        "http_status": int(http_status), "wall_ms": int(wall_ms),
        "university_id": user.get("university_id") or "independent", "role": user.get("role", ""), "user_sub": user.get("sub", ""),
        "stages": {k: int(v) for k, v in (body.get("timings_ms") or {}).items() if isinstance(v, (int, float))},
        "models": models, "suggestions": len(edits),
        "flagged": sum(1 for e in edits if isinstance(e, dict) and e.get("supervisor") == "flagged"),
        "flagged_before_finder": int(sf.get("flagged_before") or 0) if sf else None,
        "finder_verified": sum(1 for r in sf.get("report") or [] if r.get("outcome") == "verified") if sf else None,
        "doc_type": body.get("doc_type"), "orchestrator": (body.get("orchestrator") or {}).get("name"),
        "error": (error or "")[:300], "ttl": int(time.time()) + TTL_DAYS * 86400,
    }


def record(item: dict) -> None:
    userdata.table().put_item(Item=userdata._ddb({k: v for k, v in item.items() if v is not None}))


def load(days: int, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for d in range(days):
        day = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        kw = {"KeyConditionExpression": Key("PK").eq(f"USAGE#{day}")}
        while True:
            page = userdata.table().query(**kw)
            out += [userdata._plain(i) for i in page["Items"]]
            if "LastEvaluatedKey" not in page:
                break
            kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return out


def pct(values: list[float], p: float) -> int | None:
    if not values:
        return None
    v = sorted(values)
    return int(v[min(len(v) - 1, max(0, math.ceil(p / 100 * len(v)) - 1))])


def aggregate(rows: list[dict], days: int, names: dict | None = None, now: datetime | None = None) -> dict:
    """Everything the Agent monitor shows, from usage records alone (pure: no AWS calls, so it's unit-tested)."""
    now = now or datetime.now(timezone.utc)
    names = names or {}
    rows = sorted(rows, key=lambda r: r.get("at", ""), reverse=True)
    analyses = [r for r in rows if r.get("op") in ANALYSES]
    ok_analyses = [r for r in analyses if r.get("status") == "DONE"]

    def run_cost(r):
        return sum(cost(m, v.get("in", 0), v.get("out", 0)) for m, v in (r.get("models") or {}).items())

    models: dict[str, dict] = {}
    for r in rows:
        for m, v in (r.get("models") or {}).items():
            agg = models.setdefault(m, {"model": m, "family": family(m), "calls": 0, "in": 0, "out": 0, "ms": 0})
            for k in ("calls", "in", "out", "ms"):
                agg[k] += int(v.get(k, 0))
    for m in models.values():
        m["cost"] = round(cost(m["model"], m["in"], m["out"]), 4)

    stage_names = ["map_ceph", "retrieve", "propose", "supervise", "source_finder"]
    stages = []
    for s in stage_names:
        vals = [r["stages"][s] for r in ok_analyses if s in (r.get("stages") or {})]
        if vals:
            stages.append({"stage": s, "avg_ms": int(sum(vals) / len(vals)), "p90_ms": pct(vals, 90), "runs": len(vals)})

    by_op = []
    for op in sorted({r.get("op") for r in rows}, key=lambda o: -sum(1 for r in rows if r.get("op") == o)):
        rs = [r for r in rows if r.get("op") == op]
        walls = [r["wall_ms"] for r in rs if r.get("status") == "DONE"]
        by_op.append({"op": op, "label": OPS.get(op, op), "runs": len(rs), "errors": sum(r.get("status") != "DONE" for r in rs),
                      "p50_ms": pct(walls, 50), "p90_ms": pct(walls, 90)})

    unis: dict[str, dict] = {}
    for r in rows:
        u = unis.setdefault(r.get("university_id") or "independent", {"university_id": r.get("university_id") or "independent", "runs": 0,
                                                                      "analyses": 0, "errors": 0, "tokens": 0, "cost": 0.0, "last": ""})
        u["runs"] += 1
        u["analyses"] += r.get("op") in ANALYSES
        u["errors"] += r.get("status") != "DONE"
        u["tokens"] += sum(v.get("in", 0) + v.get("out", 0) for v in (r.get("models") or {}).values())
        u["cost"] += run_cost(r)
        u["last"] = max(u["last"], r.get("at", ""))
    for u in unis.values():
        u["cost"] = round(u["cost"], 4)
        u["name"] = names.get(u["university_id"], "Independent faculty" if u["university_id"] == "independent" else u["university_id"])

    daily = []
    for d in range(days - 1, -1, -1):
        day = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        rs = [r for r in rows if r.get("at", "").startswith(day)]
        daily.append({"date": day, "runs": len(rs), "analyses": sum(r.get("op") in ANALYSES for r in rs),
                      "errors": sum(r.get("status") != "DONE" for r in rs), "cost": round(sum(run_cost(r) for r in rs), 4)})

    with_finder = [r for r in ok_analyses if r.get("flagged_before_finder") is not None]
    sugg = sum(r.get("suggestions", 0) for r in ok_analyses)
    walls = [r["wall_ms"] for r in ok_analyses]
    return {
        "days": days, "generated_at": now.isoformat(timespec="seconds"), "price_note": PRICE_NOTE,
        "totals": {"runs": len(rows), "analyses": len(analyses), "errors": sum(r.get("status") != "DONE" for r in rows),
                   "error_rate": round(sum(r.get("status") != "DONE" for r in rows) / len(rows), 4) if rows else 0,
                   "analysis_p50_ms": pct(walls, 50), "analysis_p90_ms": pct(walls, 90),
                   "tokens": sum(m["in"] + m["out"] for m in models.values()), "cost": round(sum(m["cost"] for m in models.values()), 4),
                   "universities": len([u for u in unis if u != "independent"]), "professors": len({r.get("user_sub") for r in rows if r.get("user_sub")})},
        "quality": {"suggestions": sugg, "finished": len(ok_analyses), "per_analysis": round(sugg / len(ok_analyses), 1) if ok_analyses else 0,
                    "flagged_after": sum(r.get("flagged", 0) for r in ok_analyses),
                    "flagged_before_finder": sum(r["flagged_before_finder"] for r in with_finder),
                    "finder_verified": sum(r.get("finder_verified") or 0 for r in with_finder),
                    "flag_rate": round(sum(r.get("flagged", 0) for r in ok_analyses) / sugg, 3) if sugg else 0},
        "stages": stages, "models": sorted(models.values(), key=lambda m: -m["cost"]), "by_op": by_op,
        "universities": sorted(unis.values(), key=lambda u: -u["runs"]), "daily": daily,
        "recent": [{k: r.get(k) for k in ("at", "job_id", "op", "status", "wall_ms", "university_id", "stages", "suggestions", "flagged",
                                           "finder_verified", "doc_type", "error")} | {"label": OPS.get(r.get("op"), r.get("op")),
                                                                                       "cost": round(run_cost(r), 4),
                                                                                       "tokens": sum(v.get("in", 0) + v.get("out", 0) for v in (r.get("models") or {}).values()),
                                                                                       "university": names.get(r.get("university_id"), "Independent faculty" if r.get("university_id") == "independent" else r.get("university_id"))}
                   for r in rows[:60]],
    }
