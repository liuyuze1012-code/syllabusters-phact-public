"""Write Agent-monitor usage records for jobs that ran before monitoring existed (job records expire after 7 days).

    python scripts/backfill_usage.py          # safe to rerun: a record is keyed by its job id and start time

Reads each finished JOB# item, its saved request (who, which route) and result (stats, timings, edits) from S3,
and writes the same counts-only record the worker writes today.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "playground")]
import usage  # noqa: E402
import userdata  # noqa: E402

t, s3 = userdata.table(), userdata.s3()
kw = {"FilterExpression": "begins_with(PK, :j) AND SK = :s", "ExpressionAttributeValues": {":j": "JOB#", ":s": "JOB"}}
jobs = []
while True:
    page = t.scan(**kw)
    jobs += page["Items"]
    if "LastEvaluatedKey" not in page:
        break
    kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
done = 0
for j in jobs:
    if j.get("status") not in ("DONE", "FAILED"):
        continue
    jid = j["PK"][4:]
    try:
        req = json.loads(s3.get_object(Bucket=userdata.BUCKET, Key=f"jobs/{jid}/request.json")["Body"].read())
    except Exception:  # noqa: BLE001
        continue
    body = None
    try:
        body = json.loads(s3.get_object(Bucket=userdata.BUCKET, Key=f"jobs/{jid}/result.json")["Body"].read())
    except Exception:  # noqa: BLE001
        pass
    start = datetime.fromisoformat(j.get("started_at") or j["created_at"])
    end = datetime.fromisoformat(j["finished_at"]) if j.get("finished_at") else start
    status = int(j.get("http_status") or (200 if j["status"] == "DONE" else 500))
    usage.record(usage.build(jid, req["path"], req.get("user") or {}, status, int((end - start).total_seconds() * 1000), body,
                             j.get("error", "") if j["status"] == "FAILED" else "", at=start))
    done += 1
print(f"backfilled {done} of {len(jobs)} job records")
