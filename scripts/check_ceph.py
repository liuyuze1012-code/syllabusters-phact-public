"""Check knowledge-base/checklist/ceph_competencies.json against the CEPH PDF.

    python scripts/check_ceph.py

Passes only if: there are exactly 22 competencies with ids 1–22, every domain lists the right ids,
every statement and interpretation item appears word for word in the PDF text, and every
does_not_count item is one of that competency's interpretation items.
It can't check that an interpretation is paired with the RIGHT competency; a human does that.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "knowledge-base/checklist/ceph_competencies.json"


def norm(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    return " ".join(re.findall(r"[\w\"'#()/.,;:=&–-]+", text.lower()))


def main() -> int:
    data = json.loads(CHECKLIST.read_text())
    pdf_text = subprocess.run(["pdftotext", "-enc", "UTF-8", str(ROOT / data["source_file"]), "-"],
                              check=True, capture_output=True, text=True).stdout
    source = norm(pdf_text)
    problems = []

    comps = data["competencies"]
    if sorted(c["id"] for c in comps) != list(range(1, 23)):
        problems.append("competency ids are not exactly 1–22")
    in_domains = sorted(i for d in data["domains"] for i in d["ids"])
    if in_domains != list(range(1, 23)):
        problems.append("domains don't cover ids 1–22 exactly once")

    for c in comps:
        for label, text in [("statement", c["statement"])] + [("interpretation", t) for t in c["interpretation"]]:
            if norm(text) not in source:
                problems.append(f"#{c['id']} {label} not found word for word: {text[:70]}…")
        for t in c["does_not_count"]:
            if t not in c["interpretation"]:
                problems.append(f"#{c['id']} does_not_count item is not one of its interpretation items: {t[:60]}…")

    for p in problems:
        print("FIX ", p)
    print(f"{len(comps)} competencies checked; problems: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
