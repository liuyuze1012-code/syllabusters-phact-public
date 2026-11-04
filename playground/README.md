# PHACT Playground

A local workbench that runs the **real** MVP pipeline (real Claude on Bedrock + the real knowledge base), so you can experience the whole flow and check every citation. **Not the product UI;** that's `frontend/`.

```bash
cd playground
python server.py        # → http://localhost:8787   (needs fresh sandbox credentials in ~/.aws)
```
Python deps: `anthropic[bedrock] boto3 fastapi uvicorn python-multipart python-docx pydantic`, plus `pip install -e ../shared`. PDFs need `pdftotext` (`brew install poppler`).

**Restarting after code changes:** stop whatever is *listening* on the port first, or the new server fails with "address already in use" and the old code keeps answering:
```bash
kill $(lsof -ti:8787 -sTCP:LISTEN) 2>/dev/null; sleep 1; ../.venv/bin/python server.py
```

## What you can do
1. **Create or pick a course:** code, name, level, format (in person / online live / online self-paced / hybrid), class size, **AI use in this course** (ban / restricted / open), your comfort with AI, and notes. Saved in this browser. All of it becomes the AI's context, and the AI stance is a **hard constraint**: under a ban, a code gate rejects any edit that lets students use AI.
2. **Upload** a PDF/DOCX/text syllabus. Station 1 (Haiku) indexes it into sections and assignments (~10–15 s).
3. **Choose the competencies:** tick the ones assigned to the course (claimed ones are pre-ticked).
4. **Analyze** (~1 min). Map to CEPH (Opus) → find sources (knowledge base) → write edits (Opus), with the code checks. You get:
   - a 22-square heatmap
   - each judgment, with the CEPH rule it applied
   - edit cards: original vs proposed, the AI's reasoning, and **the exact ASPPH passage + a link that opens the PDF**
   - the retrieval log (what it searched, scores) and the token/timing per call
4. **Chat** to change, add or ask ("make E2 simpler", "add a week on data ethics", "why E4?"). Changed edits get a new version. Vague requests: if the readings would change different things ("shorten the syllabus", "make it better") PHACT asks once, with buttons; if only the amount is unclear ("make the edits shorter") it uses a default and says "I assumed: …".
5. **Search the knowledge base** directly to check what retrieval returns for any question.
6. **Accept/Reject** edits (🔗 linked edits are accepted together), then **download the revised syllabus as DOCX** (accepted edits only). A Word upload is edited in place, keeping its formatting; a PDF is rebuilt with clean tables. Your real names and contacts are put back in the export (they were only hidden from Claude; the map stays in `playground/.uploads/`, never committed).

## Files
| File | What it does |
|---|---|
| `server.py` | FastAPI on `127.0.0.1:8787`. Thin routes over `agent/`: extract, structure, analyze, chat, search, source links |
| `index.html` | The whole page: plain HTML + JS, no build step |

## Safety and trust (built in)
- **Safety gate (US-8):** the syllabus and every chat message pass Amazon Comprehend first, so names, emails and phone numbers become `[NAME_1]`-style tags before Claude sees anything. The count shows after Read. Chat messages also pass the **Bedrock Guardrail** (`scripts/create_guardrail.py`), which blocks off-topic requests (stocks, sports, celebrity news), harmful content and prompt attacks with a friendly reply.
- **At least one ASPPH source per edit (US-6):** enforced by the code gate.
- **Supervisor (US-9):** a second, independent check of every edit. Citations that don't support it are removed (and the note says so). Doubtful edits show **⚠ Flagged** with the reason; good ones show **✓ Supervisor verified**.
- **DOCX export (US-11):** the revised syllabus with accepted edits applied and highlighted, plus a "Changes and sources" table (citations with page numbers, CEPH targets, school rule, Supervisor result, approval time).

## Not in the MVP yet
Station 2b (Rate AI) and 2c (Assessments), manual editing of an edit's text, decisions saved beyond the browser tab, and logins.

## Layout (Nov 3)
Setup screen (course → upload → competencies → Analyze), then a Jobright-style workspace:
- **Left:** coverage gauge (competencies met now → if you accept), "See what's changed" with ✓/✕, the chat with suggestion chips, plus Coverage / Sources / Details tabs.
- **Right:** your syllabus as a page. Red strikethrough = removed, green = PHACT's text, amber = flagged by the Supervisor. **[1][2] = ASPPH sources**: click one for the exact passage and the PDF page; the References list at the end numbers them like a paper. Click a highlight for the reasoning and Accept/Reject. Chat changes update the page live and pulse. "Show changes" off = clean preview of what the download will say. 🔒 pills are details hidden from the AI (restored in the download).
- **Dev shortcut:** `/?demo` loads the last saved analysis from `.uploads/demo.json` so you can test the UI without a 1-minute run.

## Editor, Style, downloads (Nov 3, later)
- **✎ Editor:** every section as an accordion (like Jobright's editor). Edit the text yourself; PHACT's edits for that section sit underneath and you can rewrite their text too. Double-click any part of the page to jump to it. **+ Add a section** from presets (AI use policy, accessibility, integrity, wellness, communication) or ask PHACT to draft one. Hand-typed text passes the Safety gate (`/api/scrub`) before it can reach Claude.
- **Aa Style:** templates (Classic, Modern, Compact, Academic), fonts, sizes, accent color, spacing, margins, schedule as a table. Applies to the page and to the download. A Word upload keeps its own formatting unless you tick "Also restyle my uploaded Word file".
- **Downloads:** *final syllabus* (clean, reads as yours) or *review copy* (highlights, `[PHACT E#]` / `[Instructor edit]` tags, Changes and sources appendix). In a Word upload, hand edits become instructor edits applied in place, before PHACT's.
- **Evidence** tab: CEPH coverage, every ASPPH source, KB search, retrieval log and timings.

## App structure (Nov 3, latest): placeholder until the real UI design
A small single-page app with a sidebar. Pages are URL routes, so the browser Back button works:
| Route | Page |
|---|---|
| `#/` | **Home**: your courses as cards (progress, changes accepted, last updated). Delete with 🗑. |
| `#/settings` | **Settings**: name (greeting only, never sent to the AI), institution, defaults for new courses, syllabus style, and **standing preferences** that PHACT reads in every analysis and chat |
| `#/new`, `#/c/CODE` | **Course**: a 4-step flow (details → upload → competencies → analyze, with a progress screen) |
| `#/c/CODE/revise` | **Workspace**: AI Revise, Editor, Style, Evidence + the live syllabus |
Each course's work (outline, edits, your decisions, hand edits, chat) is **saved in this browser** (localStorage), so you can leave and come back. "Open the saved PHC 6149 demo" on an empty Home (or `/?demo`) loads `.uploads/demo.json` as a course.
- **🎯 Competencies (workspace top bar → Evidence tab):** add competencies after the first analysis and PHACT analyzes **only those** (`/api/analyze_more`, ~30 s): it maps them, searches sources for their gaps, and writes 1–3 edits while seeing the existing ones (no duplicates, links allowed). Your edits, decisions and hand edits stay. Removing a competency offers to reject the edits written only for it.
- Course cards open straight into the workspace when a revision exists. Re-running Analyze from the course page starts over, and the page warns you.

## Semester agent: assessments (Nov 4)
The course page is now a **course hub**. After the syllabus is analyzed, its **Semester** section lists every week from the syllabus; **+ Add an assessment** (homework, exam/quiz, project, written assignment) to any week.
- Read: `/api/assessment/structure` (Haiku; one `task` section per question; **refuses student work**, FERPA). Analyze: `/api/assessment/analyze` (`agent/pipeline/assess.py`).
- Every change is an **8-part design**: where · **AIAS level** (AI Assessment Scale, capped by the course stance: ban 1, restricted 3, open 5) · what AI / students do · why + CEPH · **rubric row** · AI-use statement for students · what the AI gets wrong + how students check · practicalities. `gates.check_suggestion` enforces it; the Supervisor checks the parts are concrete and consistent with the level.
- Evidence: the **pattern library** (`knowledge-base/kb/practice/`, 18 cards, `source_type: practice`, sources in `knowledge-base/practice_sources.md`) filtered by material type and allowed level, plus ASPPH guidance. Retrieval tests: `scripts/test_retrieval.py knowledge-base/tests/practice_retrieval_tests.json`.
- **Course memory** (syllabus AI policy, competencies, other assessments, accepted/rejected ideas) goes into every assessment analysis and chat.
- The hub also shows the **Course AI plan** (each assessment's AIAS levels vs. the stance) and **Competencies across the semester** (where each competency is actually graded).
- Each assessment opens in the same workspace (highlights, citations, Editor, Style, chat, export), stored under `session.materials[id]`.

## Course hub (Nov 4, latest)
Every course opens to one page, top to bottom:
1. **About this course**: description (from the syllabus, or ✎ write your own), level/format/size, AI stance with its AIAS cap, competencies.
2. **What PHACT knows about this course**: a checklist of everything in the AI's context, plus the exact course memory text.
3. **Upload a course document**: drop any file. `/api/classify` (Haiku, after the Safety gate) detects **syllabus / homework / exam / project / written / other**, writes a summary and guesses the week; you confirm or change the type, then:
   syllabus → read + competencies + analyze (replacing an existing one asks first) · assessment → the assessment pipeline · other → saved as a **reference** whose summary joins the course memory.
   **Try a sample** buttons load the fictional EPID 601 set in `data/test-assessments/` (homework, midterm, project, memo, reading guide) plus the EPID 601 syllabus.
4. **Course documents**: everything uploaded, with type, week, summary, status.
5. **Semester**: weekly timeline, course AI plan, competencies across the semester.

## Accounts, user data and the ASPPH admin (Nov 4)
Contracts: `docs/contracts-userdata.md`. Plan and test gates: `docs/team/PLAN-accounts-admin.md`.
- **Accounts** (`PHACT_AUTH=1`): log in / create an account; Cognito stores passwords. The server keeps a signed, HTTP-only session cookie (`accounts.py`). Off (local default): no login, browser storage, as before.
- **User data** (`userdata.py`): profile, preferences, course list and history in DynamoDB `phact-app`; each course's full progress, uploaded files and name maps in the private S3 bucket `phact-userdata-…`. Courses made in a browser before accounts can be imported once. Settings shows "Your activity".
- **ASPPH admin** at `/admin` (role `aspph-staff`): the knowledge-base library (publish a document, replace an older edition, make secondary, retire; every change re-syncs and runs a live search test), **example syllabi** shared by professors (with consent) to approve or return, and the audit log (`admin_sources.py`).
- **Peer examples**: approved example syllabi inspire analyses but are never cited (they're kept out of the numbered passages); the Evidence tab lists them.
- Setup: `python scripts/create_userdb.py` (safe to rerun). Tests: `pytest playground/tests`.
