"""Turn the source PDFs into knowledge base files: one Markdown file per section, plus its
Bedrock metadata sidecar. Driven entirely by knowledge-base/sources.json.

    python scripts/prepare_kb.py                      # every document
    python scripts/prepare_kb.py --doc aspph-ai-framework

What it does, per section:
  1. extracts the listed pages with pdftotext (poppler: `brew install poppler`)
  2. cuts at the 'start' / 'end' heading lines when two sections share a page
  3. removes junk only: running headers/footers, page numbers, the document's drop_lines
  4. re-flows broken lines into paragraphs; ALL-CAPS lines become ### headings
  5. FIDELITY CHECK: the words in the output must equal the words of the source text
     (minus the removed junk), in the same order. Nothing may be added, dropped or reworded.
  6. writes kb/<type>/<doc_id>__<section>.md + .md.metadata.json (checked under 1 KB)

It also writes knowledge-base/manifest.json: every section, its pages, word count and check result.
A human still reads every file against the PDF before it is loaded (see knowledge-base/BUILD.md).
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge-base"
METADATA_LIMIT = 900  # bytes; S3 Vectors allows 1 KB of custom metadata per vector

WORD = re.compile(r"\w+", re.UNICODE)
PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,3}\s*$", re.IGNORECASE)
BULLET = re.compile(r"^\s*[•▪●◦■\-–]\s+")
LABEL = re.compile(r"^[A-Z][\w ,&/()'’-]{2,60}:\s")  # "Competency Integration: This strategy…"


def pdf_pages(pdf: Path, first: int, last: int) -> list[str]:
    out = []
    for p in range(first, last + 1):
        text = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-f", str(p), "-l", str(p), str(pdf), "-"],
            check=True, capture_output=True, text=True,
        ).stdout
        out.append(text.replace("\f", "").replace(" ", " "))
    return out


def page_count(pdf: Path) -> int:
    info = subprocess.run(["pdfinfo", str(pdf)], check=True, capture_output=True, text=True).stdout
    return int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1))


def running_lines(pdf: Path) -> set[str]:
    """Lines that repeat on at least 30% of pages (and 3+ pages): headers, footers, page furniture."""
    pages = pdf_pages(pdf, 1, page_count(pdf))
    counts = Counter()
    for page in pages:
        counts.update({ln.strip() for ln in page.splitlines() if 0 < len(ln.strip()) <= 80})
    threshold = max(3, int(0.3 * len(pages)))
    return {ln for ln, n in counts.items() if n >= threshold}


def cut(text: str, start: str | None, end: str | None, where: str) -> str:
    lines = text.splitlines()
    if start:
        idx = next((i for i, ln in enumerate(lines) if ln.strip() == start), None)
        if idx is None:
            sys.exit(f"[{where}] start heading not found: {start!r}")
        lines = lines[idx:]
    if end:
        idx = next((i for i, ln in enumerate(lines[1:], 1) if ln.strip() == end), None)
        if idx is None:
            sys.exit(f"[{where}] end heading not found: {end!r}")
        lines = lines[:idx]
    return "\n".join(lines)


def is_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters) and len(line) <= 90


def reflow(lines: list[str]) -> str:
    """Join wrapped lines into paragraphs without changing any word."""
    blocks: list[str] = []
    para: list[str] = []
    width = max((len(ln) for ln in lines), default=80)

    def flush():
        if para:
            blocks.append(" ".join(para))
            para.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue
        if is_heading(line):
            flush()
            if blocks and blocks[-1].startswith("### "):     # a heading split over two lines
                blocks[-1] += " " + line
            else:
                blocks.append("### " + line)
            continue
        if BULLET.match(line):
            flush()
            para.append("- " + BULLET.sub("", line))
            continue
        if para and LABEL.match(line):
            flush()
        if para:
            prev = para[-1]
            ends_sentence = prev.rstrip().endswith((".", "?", "!", ":", "”", '"'))
            if ends_sentence and len(prev) < 0.7 * width:
                flush()
        para.append(line)
    flush()
    return "\n\n".join(blocks)


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_section(doc: dict, sec: dict, junk: set[str], previous: dict, force: bool) -> dict:
    pdf = ROOT / doc["pdf"]
    first, last = sec["pages"]
    where = f"{doc['doc_id']}/{sec['id']}"
    text = cut("\n".join(pdf_pages(pdf, first, last)), sec.get("start"), sec.get("end"), where)

    drop = junk | set(doc.get("drop_lines", []))
    kept = [ln for ln in text.splitlines() if ln.strip() not in drop and not PAGE_NUMBER.match(ln)]
    body = reflow(kept)

    source_words = words("\n".join(kept))
    output_words = words(body)
    fidelity = source_words == output_words

    header = f"# {doc['title']}: {sec['title']}\n\n"
    md = header + body + "\n"
    stem = f"{doc['doc_id']}__{sec['id']}"
    out_dir = KB / doc["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{stem}.md"
    rel = f"{doc['out_dir']}/{stem}.md"

    # Never overwrite a file someone has edited by hand: its hash no longer matches what we generated.
    prev = previous.get(rel, {})
    hand_edited = md_path.exists() and prev.get("generated_sha") and sha(md_path.read_text(encoding="utf-8")) != prev["generated_sha"]
    if hand_edited and not force:
        return {**prev, "skipped": "hand-edited (use --force to regenerate)"}
    md_path.write_text(md, encoding="utf-8")

    meta = {"metadataAttributes": {
        "doc_id": doc["doc_id"],
        "title": doc["title"][:120],
        "section": sec["title"],
        "source_type": doc["source_type"],
        "year": doc["year"],
        "publisher": doc["publisher"],
        "original": f"originals/{doc['doc_id']}.pdf#page={first}",
    }}
    meta_json = json.dumps(meta, ensure_ascii=False, indent=2)
    size = len(meta_json.encode("utf-8"))
    (out_dir / f"{stem}.md.metadata.json").write_text(meta_json + "\n", encoding="utf-8")

    return {"file": rel, "pages": [first, last], "words": len(output_words),
            "fidelity": fidelity, "metadata_bytes": size, "metadata_ok": size <= METADATA_LIMIT,
            "review_note": sec.get("review_note"), "generated_sha": sha(md),
            "reviewed": prev.get("reviewed", False)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", help="only this doc_id")
    ap.add_argument("--force", action="store_true", help="regenerate even hand-edited files (loses the edits)")
    args = ap.parse_args()

    config = json.loads((KB / "sources.json").read_text())
    docs = [d for d in config["documents"] if not args.doc or d["doc_id"] == args.doc]
    if not docs:
        sys.exit(f"no document with doc_id {args.doc!r}")

    manifest_path = KB / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    problems = 0
    for doc in docs:
        junk = running_lines(ROOT / doc["pdf"])
        previous = {s["file"]: s for s in manifest.get(doc["doc_id"], {}).get("sections", [])}
        results = [build_section(doc, s, junk, previous, args.force) for s in doc["sections"]]
        manifest[doc["doc_id"]] = {"title": doc["title"], "source_type": doc["source_type"], "year": doc["year"],
                                   "priority": doc["priority"], "pdf": doc["pdf"], "removed_running_lines": sorted(junk),
                                   "sections": [{k: v for k, v in r.items() if k != "skipped"} for r in results]}
        print(f"\n{doc['doc_id']}  ({doc['source_type']}, {doc['year']}) — removed running lines: {sorted(junk) or 'none'}")
        for r in results:
            if r.get("skipped"):
                print(f"  --- {r['file']:<75} skipped: {r['skipped']}")
                continue
            ok = r["fidelity"] and r["metadata_ok"]
            problems += not ok
            print(f"  {'OK ' if ok else 'FIX'} {r['file']:<75} p{r['pages'][0]}-{r['pages'][1]:<3} {r['words']:>5} words"
                  + ("" if r["fidelity"] else "  ← words changed") + ("" if r["metadata_ok"] else "  ← metadata too big")
                  + ("  ← REVIEW: " + r["review_note"][:60] + "…" if r["review_note"] else ""))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"\nmanifest: {manifest_path.relative_to(ROOT)}   problems: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
