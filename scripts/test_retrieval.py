"""Run knowledge-base/tests/retrieval_tests.json against the live Bedrock Knowledge Base.

    KB_ID=XXXXXXXXXX AWS_REGION=us-west-2 python scripts/test_retrieval.py

Prints PASS/FAIL per question with the top results' score, doc and section.
First run Nov 3: 16/16 passed.
"""

import json
import sys
import os
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge-base/tests/retrieval_tests.json"
    cfg = json.loads((ROOT / path).read_text())
    rt = boto3.client("bedrock-agent-runtime")
    kb_id, top_k = os.environ["KB_ID"], cfg.get("top_k", 3)
    failed = 0
    for t in cfg["tests"]:
        vector = {"numberOfResults": top_k}
        # Same lifecycle rule as PHACT's search: only ACTIVE documents (retired ones must never come back).
        active = {"equals": {"key": "status", "value": "active"}}
        vector["filter"] = ({"andAll": [{"equals": {"key": "source_type", "value": t["filter_source_type"]}}, active]}
                            if t.get("filter_source_type") else active)
        res = rt.retrieve(knowledgeBaseId=kb_id, retrievalQuery={"text": t["q"]},
                          retrievalConfiguration={"vectorSearchConfiguration": vector})
        hits = [(r.get("score", 0), r["metadata"].get("doc_id"), r["metadata"].get("section"))
                for r in res["retrievalResults"]]
        ok = any(doc == t["expect_doc"] and (not t.get("expect_sections") or sec in t["expect_sections"])
                 for _, doc, sec in hits)
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {t['q'][:70]}")
        for score, doc, sec in hits:
            print(f"        {score:.2f}  {doc} › {sec}")
    print(f"\n{len(cfg['tests']) - failed}/{len(cfg['tests'])} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
