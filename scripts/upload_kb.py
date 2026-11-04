"""Upload the prepared knowledge base to S3 and start a Bedrock sync.

    KNOWLEDGE_BUCKET=... KB_ID=... DATA_SOURCE_ID=... AWS_REGION=us-west-2 python scripts/upload_kb.py

  1. knowledge-base/kb/**      → s3://<bucket>/kb/...         (the ONLY prefix the data source syncs)
  2. each source PDF           → s3://<bucket>/originals/<doc_id>.pdf   (citation links; not synced)
  3. start_ingestion_job, then wait until it finishes and print its statistics

Refuses to upload unless every section in manifest.json passed its fidelity check and is marked reviewed.
First run Nov 3: 38/38 documents indexed.
"""

import json
import os
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge-base"


def main() -> int:
    manifest = json.loads((KB / "manifest.json").read_text())
    blockers = [s["file"] for d in manifest.values() for s in d["sections"]
                if not s.get("fidelity") or not s.get("reviewed")]
    if blockers:
        print("Not uploading. These sections are unreviewed or failed the fidelity check:")
        for f in blockers:
            print("  ", f)
        print('Mark a section reviewed by setting "reviewed": true in knowledge-base/manifest.json after reading it.')
        return 1

    bucket = os.environ["KNOWLEDGE_BUCKET"]
    s3 = boto3.client("s3")
    for path in sorted((KB / "kb").rglob("*")):
        if path.is_file() and path.name != ".gitkeep":
            key = "kb/" + path.relative_to(KB / "kb").as_posix()
            s3.upload_file(str(path), bucket, key)
            print("uploaded", key)
    for doc_id, doc in manifest.items():
        s3.upload_file(str(ROOT / doc["pdf"]), bucket, f"originals/{doc_id}.pdf",
                       ExtraArgs={"ContentType": "application/pdf"})
        print("uploaded", f"originals/{doc_id}.pdf")

    agent = boto3.client("bedrock-agent")
    kb_id, ds_id = os.environ["KB_ID"], os.environ["DATA_SOURCE_ID"]
    job = agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)["ingestionJob"]
    while job["status"] in ("STARTING", "IN_PROGRESS"):
        time.sleep(10)
        job = agent.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id,
                                      ingestionJobId=job["ingestionJobId"])["ingestionJob"]
        print("sync:", job["status"])
    print(json.dumps(job.get("statistics", {}), indent=2))
    if job.get("failureReasons"):
        print("failures:", job["failureReasons"])
    return 0 if job["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
