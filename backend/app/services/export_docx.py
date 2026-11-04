"""Build the exported syllabus (US-11): ACCEPTED edits only, applied in place, plus an appendix
"Changes and sources": each edit, its reason, its ASPPH citations, its checks, and who approved it when.

Two paths:
  edit_original(docx_bytes, ...)  the professor uploaded a Word file: edit THAT file in place, so fonts,
                                  styles, tables and headers survive. Replaced text keeps its run's formatting.
  build(...)                      PDF or pasted text: rebuild a clean document from the extracted text
                                  (table-like lines become real Word tables, no " | " pipes).
Two modes (both paths):
  review=True   review copy: changes highlighted and tagged "[PHACT E3]", a cover note, and the
                "Changes and sources" appendix (the audit trail)
  review=False  final syllabus: reads as the professor's own document, no highlights, tags or appendix
Both put the professor's own details back (pii_map: tag -> real value), because PHACT only hid them from
Claude, and both warn when an accepted edit needs another edit that wasn't accepted (Edit.requires).
python-docx can't write real Word tracked changes, so edited text is highlighted and tagged
("[PHACT E3]") and the appendix is the audit trail.
Used by the backend export route and by playground/server.py.
"""

import copy

import io
import re
from datetime import datetime, timezone

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run

STANCE = {"ban": "AI not allowed", "restricted": "AI restricted (brainstorm/edit, disclosed)",
          "open": "AI open (collaborative, disclosed)"}


def _flex(original: str) -> re.Pattern:
    """Match the original text even if line breaks, table pipes or spacing differ."""
    words = [re.escape(w) for w in re.split(r"[\s|]+", original.strip()) if w]
    return re.compile(r"[\s|]*".join(words), re.I)


def _restore(text: str | None, pii_map: dict[str, str]) -> str:
    for tag, value in (pii_map or {}).items():
        text = (text or "").replace(tag, value)
    return text or ""


def _unrestore_edits(edits: list[dict], pii_map: dict) -> list[dict]:
    return [{**e, "original": _restore(e.get("original"), pii_map) or None,
             "proposed": _restore(e.get("proposed"), pii_map) or None} for e in edits]


def label(edit_id: str) -> str:
    return "Instructor edit" if edit_id.startswith(("M-", "A-")) else f"PHACT {edit_id}"


CONTEXT = 40


def instructor_edits(outline: dict, manual: dict | None, added: list | None) -> list[dict]:
    """The professor's own changes from the playground editor, as accepted edits, so the in-place Word
    export can apply them to the ORIGINAL file like any other edit.
    manual: {section_id: full new text}. Only the changed middle (common start/end trimmed at word
    boundaries) becomes the edit, so the rest of the paragraph keeps its formatting.
    added:  [{after, title, text}] new sections, inserted after a section."""
    out = []
    sections = {s["id"]: s for s in outline["sections"]}
    for sid, new in (manual or {}).items():
        old = sections.get(sid, {}).get("text")
        if old is None or old == new:
            continue
        p = 0
        while p < min(len(old), len(new)) and old[p] == new[p]:
            p += 1
        while p and not old[p - 1].isspace():  # back to a word start
            p -= 1
        s = 0
        while s < min(len(old), len(new)) - p and old[-1 - s] == new[-1 - s]:
            s += 1
        while s and not old[len(old) - s].isspace():  # forward to a word end
            s -= 1
        # Widen to whole words on both sides until the original is distinctive (~40 chars): a bare "5"
        # would match the first "5" anywhere in the file.
        while len(old) - s - p < CONTEXT and (p > 0 or s > 0):
            if p > 0:
                p -= 1
                while p and not old[p - 1].isspace():
                    p -= 1
            if s > 0 and len(old) - s - p < CONTEXT:
                s -= 1
                while s and not old[len(old) - s].isspace():
                    s -= 1
        original, proposed = old[p:len(old) - s], new[p:len(new) - s]
        if original.strip():
            out.append({"edit_id": f"M-{sid}", "section_id": sid, "op": "replace", "original": original,
                        "proposed": proposed, "rationale": "Written by the instructor in PHACT's editor.",
                        "evidence": [], "status": "accepted", "supervisor": "not_run", "version": 1})
    for i, a in enumerate(added or [], 1):
        out.append({"edit_id": f"A-{i}", "section_id": a["after"], "op": "insert_after", "original": None,
                    "proposed": f"{a['title']}\n{a['text']}".strip(), "rationale": "Section added by the instructor.",
                    "evidence": [], "status": "accepted", "supervisor": "not_run", "version": 1})
    return out


def apply_style(doc, style: dict | None):
    """The playground's Style tab: font, sizes, heading colour, spacing and margins."""
    if not style:
        return
    from docx.shared import Inches
    font, body = style.get("font", "Georgia"), float(style.get("body", 11))
    color = RGBColor.from_string(style.get("accent", "#1F3A5F").lstrip("#").upper())
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = font, Pt(body)
    normal.paragraph_format.line_spacing = float(style.get("line", 1.15))
    normal.paragraph_format.space_after = Pt(float(style.get("gap", 4)))
    for name, size in (("Title", style.get("title", 22)), ("Heading 1", style.get("h", 14) + 1),
                       ("Heading 2", style.get("h", 14)), ("Heading 3", style.get("h", 14) - 2)):
        try:
            st = doc.styles[name]
        except KeyError:
            continue
        st.font.name, st.font.size, st.font.color.rgb = style.get("hfont", font), Pt(float(size)), color
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Inches(float(style.get("margin", 1)))


def missing_requirements(edits: list[dict]) -> list[str]:
    """Accepted edits whose required edits were not accepted (e.g. a new 10% assignment without the
    edit that lowers another weight, so the grades would total 110%)."""
    accepted = {e["edit_id"] for e in edits if e.get("status") == "accepted"}
    return [f"{e['edit_id']} needs {r}, which was not accepted. Check the result still makes sense."
            for e in edits if e.get("status") == "accepted" for r in e.get("requires", []) if r not in accepted]


def _page(uri: str) -> str:
    m = re.search(r"#page=(\d+)", uri or "")
    return f", p.{m.group(1)}" if m else ""


def ref_numbers(accepted: list[dict]) -> tuple[dict, list[dict]]:
    """Number the cited ASPPH passages [1], [2]… in the order the accepted changes cite them."""
    n, refs = {}, []
    for e in accepted:
        for x in e.get("evidence") or []:
            if x.get("id") and x["id"] not in n:
                n[x["id"]] = len(n) + 1
                refs.append(x)
    return n, refs


def cites_for(accepted: list[dict]) -> dict:
    n, _ = ref_numbers(accepted)
    return {e["edit_id"]: "".join(f"[{n[x['id']]}]" for x in e.get("evidence") or [] if x.get("id") in n) for e in accepted}


def _superscript(p, text: str):
    r = p.add_run(text)
    r.font.superscript = True
    return r


def _references(doc, accepted: list[dict]):
    """The final syllabus's References: the ASPPH sources behind the changes, numbered as cited in the text."""
    _, refs = ref_numbers(accepted)
    if not refs:
        return
    doc.add_heading("References", level=2)
    for i, x in enumerate(refs, 1):
        uri = x.get("uri") or ""
        p = doc.add_paragraph()
        p.add_run(f"[{i}] ")
        p.add_run(f"{x.get('title', '')}{_page(uri)}.")
        if uri.startswith("http"):
            p.add_run(f" {uri}")


def _add_tagged(paragraph, text: str, edit_id: str):
    run = paragraph.add_run(text)
    run.font.highlight_color = WD_COLOR_INDEX.BRIGHT_GREEN
    tag = paragraph.add_run(f"  [PHACT {edit_id}]")
    tag.bold = True
    tag.font.size = Pt(8)
    tag.font.color.rgb = RGBColor(0x0D, 0x7D, 0x6F)


def apply_edits(sections: list[dict], edits: list[dict]) -> tuple[list[dict], list[str]]:
    """Return sections as lists of pieces [(text, edit_id|None)], plus warnings for edits that couldn't be placed."""
    placed = {s["id"]: [(s["text"], None)] for s in sections}
    after: dict[str, list[dict]] = {}
    warnings = []
    for e in edits:
        sid = e["section_id"]
        if sid not in placed:
            warnings.append(f"{e['edit_id']}: section {sid} not found")
            continue
        if e["op"] == "insert_after":
            after.setdefault(sid, []).append(e)
            continue
        pieces, done = [], False
        for text, tag in placed[sid]:
            m = _flex(e.get("original") or "").search(text) if tag is None and not done else None
            if m:
                pieces += [(text[:m.start()], None)]
                if e["op"] == "replace":
                    pieces += [(e.get("proposed") or "", e["edit_id"])]
                pieces += [(text[m.end():], None)]
                done = True
            else:
                pieces.append((text, tag))
        if not done:
            warnings.append(f"{e['edit_id']}: original text not found; added after the section instead")
            after.setdefault(sid, []).append({**e, "op": "insert_after"})
        placed[sid] = pieces
    out = []
    for s in sections:
        out.append({"id": s["id"], "title": s["title"], "pieces": placed[s["id"]], "after": after.get(s["id"], [])})
    return out, warnings


def _appendix(doc, accepted: list[dict], approvals: dict, warnings: list[str]):
    doc.add_page_break()
    doc.add_heading("Changes and sources", level=1)
    doc.add_paragraph("Every change below was proposed by PHACT and accepted by the instructor. "
                      "\"Why\" is the AI's reasoning; \"Sources\" are the exact ASPPH passages behind it.")
    table = doc.add_table(rows=1, cols=6)
    table.style = "Light Grid Accent 1"
    for cell, head in zip(table.rows[0].cells, ["Edit", "Where", "Change", "Why (AI suggestion)", "ASPPH sources", "Checks / approval"]):
        cell.text = head
    for e in accepted:
        row = table.add_row().cells
        row[0].text = e["edit_id"] + (f" v{e.get('version')}" if e.get("version", 1) > 1 else "")
        row[1].text = f"{e['section_id']} ({e['op']})"
        design = ""
        if e.get("aias_level"):  # assessment designs: the parts a professor hands to students
            design = "\n".join(x for x in [f"AIAS level {e['aias_level']}", e.get("ai_role") and f"AI / student: {e['ai_role']}",
                                             e.get("rubric_row") and f"Graded by: {e['rubric_row']}",
                                             e.get("ai_use_statement") and f"Tell students: {e['ai_use_statement']}",
                                             e.get("practicalities") and f"Practicalities: {e['practicalities']}"] if x)
        row[2].text = (f"Replaces: “{e['original']}”\n" if e.get("original") else "") + (e.get("proposed") or "(deleted)") + (f"\n\n{design}" if design else "")
        row[3].text = e.get("rationale", "")
        row[4].text = "\n".join(f"{x['id']}: {x['title']}{_page(x.get('uri', ''))}" for x in e.get("evidence", [])) or "none"
        checks = [f"CEPH {', '.join('#' + str(c) for c in e['ceph'])}" if e.get("ceph") else "",
                  f"school rule {e['school_rule']}" if e.get("school_rule") else "",
                  f"Supervisor: {e.get('supervisor', 'not_run')}" + (f" ({e['supervisor_note']})" if e.get("supervisor_note") else ""),
                  f"Accepted {approvals.get(e['edit_id'], {}).get('at', '')} by {approvals.get(e['edit_id'], {}).get('by', 'instructor')}"]
        row[5].text = "\n".join(c for c in checks if c)
    if warnings:
        doc.add_heading("Placement notes", level=2)
        for w in warnings:
            doc.add_paragraph(w, style="List Bullet")



def _cover(doc, course: dict, n: int, how: str, before=None):
    """A short italic note on what PHACT changed. Goes first (rebuild) or before `before` (original file)."""
    p = doc.add_paragraph() if before is None else before.insert_paragraph_before()
    p.add_run(f"PHACT draft, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. ").italic = True
    if course:
        p.add_run(f"{STANCE.get(course.get('ai_stance', ''), '')}. ").italic = True
    p.add_run(f"{n} accepted edit(s) are highlighted and tagged [PHACT E#]; sources are in the appendix. {how}").italic = True


def _lines(pieces) -> list[list[tuple[str, str | None]]]:
    """[(text, edit_id|None), ...] → lines, each a list of segments. A replacement inside a table row
    stays inside that row instead of becoming its own paragraph (which split tables, Nov 3)."""
    lines, cur = [], []
    for text, tag in pieces:
        for i, part in enumerate(text.split("\n")):
            if i:
                lines.append(cur)
                cur = []
            if part:
                cur.append((part, tag))
    lines.append(cur)
    return [ln for ln in lines if "".join(t for t, _ in ln).strip()]


def _runs_into(p, segs, review: bool, cites: dict | None = None):
    tags = []
    for text, tag in segs:
        run = p.add_run(text)
        if tag:
            tags.append(tag)
            if review:
                run.font.highlight_color = WD_COLOR_INDEX.BRIGHT_GREEN
    for tag in dict.fromkeys(tags):  # one label per edit, at the end
        if review:
            t = p.add_run(f"  [{label(tag)}]")
            t.bold, t.font.size, t.font.color.rgb = True, Pt(8), RGBColor(0x0D, 0x7D, 0x6F)
        elif (cites or {}).get(tag):  # final syllabus: small citation numbers pointing to References
            _superscript(p, cites[tag])


def _cells(segs) -> list[list[tuple[str, str | None]]]:
    cells = [[]]
    for text, tag in segs:
        for j, chunk in enumerate(text.split("|")):
            if j:
                cells.append([])
            cells[-1].append((chunk, tag))
    out = []
    for c in cells:
        if c:
            c[0] = (c[0][0].lstrip(), c[0][1])
            c[-1] = (c[-1][0].rstrip(), c[-1][1])
        out.append([x for x in c if x[0]])
    while out and not out[0]:
        out.pop(0)
    return out


def _write_stream(doc, stream, review: bool, cites: dict | None = None):
    """stream: ("h", title, level) or ("l", segments). Runs of table rows (" | ") become ONE Word table."""
    rows = []

    def flush():
        if len(rows) == 1:
            _runs_into(doc.add_paragraph(), [(t.replace(" | ", "   "), g) for t, g in rows[0]], review, cites)
        elif rows:
            cells_per_row = [_cells(r) for r in rows]
            t = doc.add_table(rows=0, cols=max(len(c) for c in cells_per_row))
            t.style = "Table Grid"
            for cells in cells_per_row:
                out = t.add_row().cells
                for cell, segs in zip(out, cells):
                    _runs_into(cell.paragraphs[0], segs, review, cites)
        rows.clear()

    for item in stream:
        if item[0] == "h":
            flush()
            doc.add_heading(item[1], level=item[2])
            continue
        segs = item[1]
        if " | " in "".join(t for t, _ in segs):
            rows.append(segs)
            continue
        flush()
        _runs_into(doc.add_paragraph(), [(t.strip() if i == 0 else t, g) for i, (t, g) in enumerate(segs)], review, cites)
    flush()


def build(outline: dict, edits: list[dict], course: dict | None = None, approvals: dict | None = None,
          pii_map: dict | None = None, review: bool = True, manual: dict | None = None,
          added: list | None = None, style: dict | None = None) -> bytes:
    """Rebuild path (PDF / pasted text). outline/edits as plain dicts; only "accepted" edits are applied.
    The professor's hand edits replace section text directly (the document is rebuilt anyway)."""
    outline = {**outline, "sections": [{**s, "text": (manual or {}).get(s["id"], s["text"])} for s in outline["sections"]]}
    edits = instructor_edits(outline, None, added) + list(edits)
    edits = _unrestore_edits(edits, pii_map)
    accepted = [e for e in edits if e.get("status") == "accepted"]
    course = course or {}
    doc = Document()
    apply_style(doc, style)
    title = f"{course.get('code', '')} {course.get('name', '')}".strip() or "Course syllabus"
    doc.add_heading(title, level=0)
    if review:
        _cover(doc, course, len(accepted), "Rebuilt from the uploaded PDF's text, so its exact layout is not kept.")

    sections = [{**sec, "text": _restore(sec["text"], pii_map)} for sec in outline["sections"]]
    kinds = {sec["id"]: sec.get("kind") for sec in outline["sections"]}
    placed, warnings = apply_edits(sections, accepted)
    stream, in_schedule = [], False
    for sec in placed:
        week = kinds.get(sec["id"]) == "week"
        lines = _lines(sec["pieces"])
        first = "".join(t for t, _ in lines[0]).strip().lower() if lines else ""
        if week:  # the schedule is ONE table, so weeks get no heading of their own
            if not in_schedule:
                stream.append(("h", "Course schedule", 2))
        else:
            stream.append(("h", sec["title"], 2))
            if first and first.rstrip(":") == sec["title"].strip().lower():
                lines = lines[1:]  # the text's own heading line, already shown
        in_schedule = week
        stream += [("l", ln) for ln in lines]
        for e in sec["after"]:
            body = [ln for ln in (e.get("proposed") or "").split("\n") if ln.strip()]
            if e["edit_id"].startswith("A-") and body:  # an added section: its first line is its heading
                stream.append(("h", body[0], 2))
                body = body[1:]
            stream += [("l", [(ln, e["edit_id"])]) for ln in body]
    _write_stream(doc, stream, review, cites_for(accepted))

    if review:
        _appendix(doc, accepted, approvals or {}, warnings + missing_requirements(edits))
    else:
        _references(doc, accepted)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------- editing the professor's original Word file ----------

def _paragraphs(doc) -> list[Paragraph]:
    """Every paragraph in document order, including the ones inside table cells."""
    return [Paragraph(p, doc._body) for p in doc.element.body.iter(qn("w:p"))]


def _runs(p: Paragraph) -> list[Run]:
    # Every run, including inside hyperlinks (p.runs skips those, which would shift every offset).
    return [Run(r, p) for r in p._p.iter(qn("w:r"))]


def _split(p: Paragraph, at: int):
    """Make sure a run boundary falls exactly at character `at`, so we can cut there without
    touching the formatting of the text around it."""
    pos = 0
    for run in _runs(p):
        t = run.text
        if pos < at < pos + len(t):
            twin = copy.deepcopy(run._r)
            run._r.addnext(twin)
            run.text, Run(twin, p).text = t[:at - pos], t[at - pos:]
            return
        pos += len(t)


def _cut(p: Paragraph, a: int, b: int):
    """Remove characters [a, b) of the paragraph. Returns the run element to insert after (or None = start)."""
    _split(p, a), _split(p, b)
    anchor, pos = None, 0
    for run in _runs(p):
        n = len(run.text)
        if pos + n <= a and n:
            anchor = run._r
        elif a <= pos and pos + n <= b:
            run._r.getparent().remove(run._r)
        pos += n
    return anchor


def _insert_tagged(p: Paragraph, anchor, text: str, edit_id: str, review: bool = True, cite: str = ""):
    """Insert highlighted new text after `anchor`, copying that run's font so it matches the paragraph."""
    model = anchor if anchor is not None else next(iter(p._p.iter(qn("w:r"))), None)
    new = copy.deepcopy(model) if model is not None else p.add_run()._r
    for child in list(new):
        if child.tag != qn("w:rPr"):
            new.remove(child)
    r = Run(new, p)
    r.text = text
    if not review:  # final syllabus: the new text matches the paragraph's own formatting, plus its citation numbers
        if anchor is not None:
            anchor.addnext(new)
        elif model is not None and model.getparent() is p._p:
            p._p.insert(p._p.index(model), new)
        else:
            p._p.append(new)
        if cite and text:
            sup = copy.deepcopy(new)
            Run(sup, p).text = cite
            Run(sup, p).font.superscript = True
            new.addnext(sup)
        return
    r.font.highlight_color = WD_COLOR_INDEX.BRIGHT_GREEN
    tag = copy.deepcopy(new)
    t = Run(tag, p)
    t.text, t.bold, t.font.highlight_color = f"  [{label(edit_id)}]", True, None
    t.font.size, t.font.color.rgb = Pt(8), RGBColor(0x0D, 0x7D, 0x6F)
    if anchor is not None:
        anchor.addnext(new)
    elif model is not None:
        p._p.insert(p._p.index(model) if model.getparent() is p._p else len(p._p), new)
    else:
        p._p.append(new)
    new.addnext(tag)


def _find(paras: list[Paragraph], needle: str, start_para: int = 0):
    """Find `needle` across paragraphs. Returns [(paragraph index, a, b), ...] or None."""
    texts = ["".join(r.text for r in _runs(p)) for p in paras]
    starts, pos = [], 0
    for t in texts:
        starts.append(pos)
        pos += len(t) + 1
    m = _flex(needle).search("\n".join(texts), starts[start_para] if paras else 0) if needle.strip() else None
    if not m:
        return None
    hits = []
    for i, (s0, t) in enumerate(zip(starts, texts)):
        a, b = max(m.start(), s0), min(m.end(), s0 + len(t))
        if a < b:
            hits.append((i, a - s0, b - s0))
    return hits or None


def _para_after(anchor: Paragraph) -> Paragraph:
    """A new empty paragraph after `anchor`; if anchor sits in a table, after the whole table."""
    el = anchor._p
    tbl = next((a for a in el.iterancestors(qn("w:tbl"))), None)
    if tbl is not None:
        while tbl.getparent().tag != qn("w:body"):  # nested tables: climb to the outermost
            tbl = next(tbl.iterancestors(qn("w:tbl")))
        el = tbl
    new = copy.deepcopy(anchor._p) if tbl is None else None
    if new is None:
        from docx.oxml import OxmlElement
        new = OxmlElement("w:p")
    else:
        for child in list(new):
            if child.tag != qn("w:pPr"):
                new.remove(child)
        ppr = new.find(qn("w:pPr"))
        style = ppr.find(qn("w:pStyle")) if ppr is not None else None
        if style is not None and (style.get(qn("w:val")) or "").startswith(("Heading", "Title")):
            ppr.remove(style)  # inserted text after a heading is body text, not another heading
    el.addnext(new)
    return Paragraph(new, anchor._parent)


def _section_end(paras: list[Paragraph], section: dict) -> int | None:
    """Index of the section's last paragraph in the document, found by matching its first and last lines."""
    lines = [ln for ln in section["text"].split("\n") if ln.strip()]
    if not lines:
        return None
    first = _find(paras, lines[0])
    if not first:
        return None
    last = _find(paras, lines[-1], first[0][0])
    return (last or first)[-1][0]


def edit_original(docx_bytes: bytes, outline: dict, edits: list[dict], course: dict | None = None,
                  approvals: dict | None = None, pii_map: dict | None = None, review: bool = True,
                  manual: dict | None = None, added: list | None = None, style: dict | None = None) -> bytes:
    """Apply accepted edits to the professor's own .docx. Anything that can't be placed exactly
    goes after its section and is listed in Placement notes; nothing is silently dropped."""
    # the professor's hand edits go first, so PHACT's edits (written against the edited text) find their place
    edits = _unrestore_edits(instructor_edits(outline, manual, added) + list(edits), pii_map)
    accepted = [e for e in edits if e.get("status") == "accepted"]
    sections = {sec["id"]: {**sec, "text": _restore((manual or {}).get(sec["id"], sec["text"]), pii_map)}
                for sec in outline["sections"]}
    doc = Document(io.BytesIO(docx_bytes))
    if style and style.get("apply_to_original"):  # opt-in: otherwise the professor's own formatting is kept
        apply_style(doc, style)
    warnings = []
    later = []
    cites = cites_for(accepted)
    for e in accepted:
        sec = sections.get(e["section_id"])
        if sec is None:
            warnings.append(f"{e['edit_id']}: section {e['section_id']} not found; see the appendix for its text")
            continue
        if e["op"] == "insert_after":
            later.append((e, sec))
            continue
        paras = _paragraphs(doc)
        hits = _find(paras, e.get("original") or "")
        if not hits:
            warnings.append(f"{e['edit_id']}: original text not found in the file; added after the section instead")
            later.append((e, sec))
            continue
        for n, (i, a, b) in enumerate(reversed(hits)):  # back to front, so earlier offsets stay valid
            anchor = _cut(paras[i], a, b)
            first = n == len(hits) - 1
            if first and e["op"] == "replace":
                _insert_tagged(paras[i], anchor, e.get("proposed") or "", e["edit_id"], review, cites.get(e["edit_id"], ""))
            elif first and review:
                _insert_tagged(paras[i], anchor, "", e["edit_id"])  # leaves a visible "[PHACT E#]" where text was deleted
            elif not "".join(r.text for r in _runs(paras[i])).strip() and paras[i]._p.getparent().tag == qn("w:body"):
                paras[i]._p.getparent().remove(paras[i]._p)
    for e, sec in later:  # inserts last, after all replacements, so their anchors are final
        paras = _paragraphs(doc)
        end = _section_end(paras, sec)
        if end is None:
            warnings.append(f"{e['edit_id']}: couldn't locate section \"{sec['title']}\"; added at the end of the document")
            target = doc.add_paragraph()
            _insert_tagged(target, None, e.get("proposed") or "", e["edit_id"], review, cites.get(e["edit_id"], ""))
            continue
        anchor = paras[end]
        lines = [ln for ln in (e.get("proposed") or "").split("\n") if ln.strip()]
        for k, line in enumerate(reversed(lines)):  # the citation goes after the change's last line
            _insert_tagged(_para_after(anchor), None, line.strip(), e["edit_id"], review, cites.get(e["edit_id"], "") if k == 0 else "")

    if review:
        _cover(doc, course or {}, len(accepted), "Everything else is your original file, unchanged.",
               before=doc.paragraphs[0] if doc.paragraphs else None)
        _appendix(doc, accepted, approvals or {}, warnings + missing_requirements(edits))
    else:
        _references(doc, accepted)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
