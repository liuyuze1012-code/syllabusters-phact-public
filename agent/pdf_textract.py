"""Read a PDF syllabus with Amazon Textract, so tables come back as real rows.

pdftotext only sees text positions: a schedule cell that wraps over 3 lines becomes 3 broken
fragments ("| • | Helm-Murtagh | Negotiation Case Study (from"). Textract detects the table and
returns each CELL whole, so a week becomes one row: "Week 14 | Module 9 video lectures; … | Due Apr 15".

    text = read_pdf(pdf_bytes)            # ~20–40 s for 12 pages; raises on failure (caller falls back)

How: upload to a temp S3 key → StartDocumentAnalysis(TABLES, LAYOUT) → poll → delete the temp object.
LAYOUT gives reading order (title, headings, paragraphs, lists, tables) and lets us drop page headers,
footers and page numbers. Multi-page PDFs must go through S3 (the sync API takes one page).
"""

import os
import re
import time
import uuid

import boto3

REGION = os.getenv("AWS_REGION", "us-west-2")
BUCKET = os.getenv("TEXTRACT_BUCKET", "")  # e.g. phact-knowledge-<account-id>-us-west-2
PREFIX = "textract-tmp/"  # deleted right after each job
TIMEOUT_S = 180
SKIP = {"LAYOUT_HEADER", "LAYOUT_FOOTER", "LAYOUT_PAGE_NUMBER"}


def _blocks(textract, job_id: str) -> list[dict]:
    started = time.monotonic()
    while True:
        r = textract.get_document_analysis(JobId=job_id)
        if r["JobStatus"] == "SUCCEEDED":
            break
        if r["JobStatus"] == "FAILED" or time.monotonic() - started > TIMEOUT_S:
            raise RuntimeError(f"Textract job {r['JobStatus'].lower()}: {r.get('StatusMessage', 'timed out')}")
        time.sleep(2)
    blocks = r["Blocks"]
    while r.get("NextToken"):  # results come in pages of ~1000 blocks
        r = textract.get_document_analysis(JobId=job_id, NextToken=r["NextToken"])
        blocks += r["Blocks"]
    return blocks


def _children(block: dict) -> list[str]:
    return [i for rel in block.get("Relationships", []) if rel["Type"] == "CHILD" for i in rel["Ids"]]


CONTINUES = re.compile(r"(,|&|:|-|\b(?:and|or|of|the|in|for|to|a|an|by|with|on))$", re.I)


def _text(block_id: str, by_id: dict, line_of: dict | None = None) -> str:
    """Text of a LINE/CELL/LAYOUT block from its WORD children. In a table cell, Textract drops bullet
    glyphs, so item breaks are inferred: a printed line that starts with a capital or "-" after a line
    that ended cleanly is a new item ("; "); a sentence that wraps ("Preparedness, &" / "Response")
    is joined with a space. Keeps a reading list readable in one row."""
    out, last_line = [], None
    for cid in _children(by_id[block_id]):
        c = by_id[cid]
        if c["BlockType"] in ("WORD", "LINE"):
            word, line = c.get("Text", ""), (line_of or {}).get(cid)
            if line_of is not None and word in ("•", "o", "▪", "◦"):
                continue
            new_line = line_of is not None and out and line != last_line
            breaks = new_line and (word[:1].isupper() or word[:1] in "-–") and not CONTINUES.search(out[-1].rstrip())
            out.append((("; " if breaks else " ") + word) if out else word)
            last_line = line
        elif c["BlockType"] == "SELECTION_ELEMENT" and c.get("SelectionStatus") == "SELECTED":
            out.append(" [x]")
    return "".join(out).strip(" ;")


def _table(table: dict, by_id: dict, line_of: dict) -> str:
    rows: dict[int, dict[int, str]] = {}
    for cid in _children(table):
        c = by_id[cid]
        if c["BlockType"] == "CELL":
            rows.setdefault(c["RowIndex"], {})[c["ColumnIndex"]] = _text(cid, by_id, line_of)
    lines = []
    for r in sorted(rows):
        cells = [rows[r][k] for k in sorted(rows[r])]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _overlap(a: dict, b: dict) -> float:
    a, b = a["Geometry"]["BoundingBox"], b["Geometry"]["BoundingBox"]
    w = min(a["Left"] + a["Width"], b["Left"] + b["Width"]) - max(a["Left"], b["Left"])
    h = min(a["Top"] + a["Height"], b["Top"] + b["Height"]) - max(a["Top"], b["Top"])
    return max(w, 0) * max(h, 0)


def to_text(blocks: list[dict]) -> str:
    by_id = {b["Id"]: b for b in blocks}
    line_of = {w: b["Id"] for b in blocks if b["BlockType"] == "LINE" for w in _children(b)}
    tables = [b for b in blocks if b["BlockType"] == "TABLE"]
    used_tables, parts = set(), []
    # A list's items are ALSO top-level LAYOUT_TEXT blocks; emit them once, with the list (they were
    # read twice before, so Claude saw every bulleted assignment twice, Nov 3).
    in_list = {c for b in blocks if b["BlockType"] == "LAYOUT_LIST" for c in _children(b)}
    for b in blocks:  # LAYOUT blocks arrive in reading order
        kind = b["BlockType"]
        if not kind.startswith("LAYOUT_") or kind in SKIP or b["Id"] in in_list:
            continue
        if kind == "LAYOUT_TABLE":
            same_page = [t for t in tables if t.get("Page") == b.get("Page") and t["Id"] not in used_tables]
            best = max(same_page, key=lambda t: _overlap(t, b), default=None)
            if best is not None and _overlap(best, b) > 0:
                used_tables.add(best["Id"])
                parts.append(_table(best, by_id, line_of))
                continue
        if kind == "LAYOUT_LIST":  # a list's children are LAYOUT_TEXT items, one per bullet
            items = [_text(c, by_id) for c in _children(b) if by_id[c]["BlockType"].startswith("LAYOUT_")]
            parts.append("\n".join(f"• {t}" for t in items if t))
            continue
        if _children(b) and all(by_id[c]["BlockType"].startswith("LAYOUT_") for c in _children(b)):
            continue  # a container (e.g. a list inside a key-value) whose children are emitted on their own
        text = _text(b["Id"], by_id)
        if text:
            parts.append(text)
    return "\n".join(p for p in parts if p.strip())


def read_pdf(data: bytes) -> str:
    s3 = boto3.client("s3", region_name=REGION)
    textract = boto3.client("textract", region_name=REGION)
    key = f"{PREFIX}{uuid.uuid4().hex}.pdf"
    s3.put_object(Bucket=BUCKET, Key=key, Body=data, ServerSideEncryption="AES256")
    try:
        job = textract.start_document_analysis(DocumentLocation={"S3Object": {"Bucket": BUCKET, "Name": key}},
                                               FeatureTypes=["TABLES", "LAYOUT"])
        return to_text(_blocks(textract, job["JobId"]))
    finally:  # the syllabus never stays in S3
        s3.delete_object(Bucket=BUCKET, Key=key)
