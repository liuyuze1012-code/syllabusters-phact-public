"""Try Station 1 (Read) on one test syllabus and print what came back.

    cd agent && python eval/try_structure.py ../data/test-syllabi/PHC6149-Public-Health-Leadership-Spring-2026.pdf

Text extraction here is a stand-in for the backend's extract step (pdftotext for PDFs,
python-docx for DOCX). Makes ~1 real Claude call (fast model): costs well under a cent.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from steps import structure  # noqa: E402


def extract(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        # Amazon Textract first: it detects tables, so each schedule week comes back as ONE row instead of
        # wrapped fragments. Falls back to pdftotext if Textract is off (PHACT_TEXTRACT=0) or fails.
        if os.getenv("PHACT_TEXTRACT", "1") != "0":
            try:
                import pdf_textract
                return pdf_textract.read_pdf(path.read_bytes())
            except Exception as e:  # noqa: BLE001
                print(f"Textract failed ({e}); using pdftotext")
        # Layout mode keeps each table row together (schedules are usually tables);
        # big column gaps become " | " so the model still sees the columns, in fewer tokens.
        raw = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                             check=True, capture_output=True, text=True).stdout
        return "\n".join(re.sub(r" {3,}", " | ", ln).rstrip() for ln in raw.splitlines())
    if path.suffix.lower() == ".docx":
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        d = docx.Document(str(path))
        parts = []
        for block in d.iter_inner_content():  # document order, so the schedule table stays under its heading
            if isinstance(block, Paragraph):
                parts.append(block.text)
            elif isinstance(block, Table):
                parts += [" | ".join(c.text.strip() for c in row.cells) for row in block.rows]
        return "\n".join(parts)
    return path.read_text()


def main():
    path = Path(sys.argv[1])
    text = extract(path)
    started = time.monotonic()
    outline, stats = structure.run(text)
    secs = time.monotonic() - started

    print(f"\n{path.name}: {len(text.splitlines())} lines → {len(outline.sections)} sections, "
          f"{len(outline.assignments)} assignments in {secs:.1f}s")
    for s in stats:
        print(f"  call {s.station}: {s.model} effort={s.effort} in={s.input_tokens} out={s.output_tokens} "
              f"cache_read={s.cache_read_tokens} {s.latency_ms}ms stop={s.stop_reason} {s.notes or ''}")
    print("\nSECTIONS")
    for sec in outline.sections:
        print(f"  {sec.id:<32} {sec.kind:<10} {sec.title[:50]:<50} ({len(sec.text.split())} words)")
    print("\nASSIGNMENTS")
    for a in outline.assignments:
        w = f"{a.weight:.0%}" if a.weight is not None else "  - "
        print(f"  {'GRADED ' if a.assessed else 'ungraded'} {w:>5}  {a.title[:45]:<45} → {a.section_id}  [{a.what_it_tests[:40]}]")
    print("\nAI POLICY:", (outline.ai_policy[:150] + "…") if outline.ai_policy else "none found")
    print("CLAIMED CEPH COMPETENCIES:", outline.claimed_competencies or "none")
    out = Path(__file__).resolve().parent / "out"
    out.mkdir(exist_ok=True)
    (out / f"{path.stem}.outline.json").write_text(outline.model_dump_json(indent=2))
    print(f"\nfull outline saved to eval/out/{path.stem}.outline.json")


if __name__ == "__main__":
    main()
