# Knowledge base: the three stores the AI reads

**Owner: Gavin (AI track).** The plan and the reasoning behind it are in [BUILD.md](BUILD.md).

| Store | What it is | How the AI gets it | Files here |
|---|---|---|---|
| ① Knowledge base | **The only new database:** Bedrock Knowledge Base over S3 Vectors | Searched by meaning | `kb/` |
| ② CEPH checklist | A JSON file, not a database | Loaded whole on every analysis | `checklist/ceph_competencies.json` |
| ③ AI policies | Records in the app's DynamoDB table | Looked up by `school_id` | `policies/*.json` (seeded by script) |

## Live in the sandbox (Nov 3)

Knowledge base **`C4GJF8AJ7U`**, data source `SWBUTPKJZY`, in **us-west-2**. Created by `scripts/create_kb.py`; all IDs are in `kb_ids.json`.
- Sync: **38/38 documents indexed, 0 failed.**
- Retrieval tests: **16/16 pass**, with top match scores of 0.63–0.94.

```bash
python scripts/create_kb.py                                  # safe to rerun
KNOWLEDGE_BUCKET=phact-knowledge-<account-id>-us-west-2 KB_ID=C4GJF8AJ7U DATA_SOURCE_ID=SWBUTPKJZY python scripts/upload_kb.py
KB_ID=C4GJF8AJ7U python scripts/test_retrieval.py
```

## Status (Nov 3): MVP-ready

| Document | Store / tag | Priority | Sections | Prepared | Reviewed |
|---|---|---|---|---|---|
| ASPPH AI Framework (2026) | ① `guidance` | **must** | 11 | ✅ fidelity OK | ✅ MVP pass |
| Competency Mapping & Training Agenda (2024) | ① `workforce` | **must** | 9 | ✅ fidelity OK; 4 tables rebuilt from page images | ✅ MVP pass |
| Leadership Programs report (2025) | ① `workforce` | should | 8 | ✅ fidelity OK | ✅ MVP pass |
| Shared Vision & Unified Strategy (2024) | ① `guidance` | should | 9 | ✅ fidelity OK | ✅ MVP pass |
| Applied Learning and Training page | ① `guidance` | optional | 1 | ✅ fidelity OK | ✅ MVP pass |
| CPH exam competencies | ① `guidance` | optional | n/a | deferred: its multi-column layout extracts out of order | n/a |
| CEPH MPH competencies | ② checklist | **must** | 22 | ✅ every word found in the PDF (`check_ceph.py`) | ✅ MVP pass, pairing checked |
| PHACT default + 2 demo schools | ③ policies | **must** | n/a | ✅ draft | ✅ |

Everything else in `data/reference/` is deliberately **not loaded**. Each file's reason is in `sources.json` → `not_loaded`.

## Files

| File / folder | What it is |
|---|---|
| `BUILD.md` | The build plan, decisions and time estimate |
| `sources.json` | **The source inventory:** every document, its tag, year and priority, and exactly how it's split into sections (pages + heading cut points). Also lists every file we don't load, and why. |
| `manifest.json` | Written by `scripts/prepare_kb.py`: every section's file, pages, word count, fidelity result, review note and `reviewed` flag |
| `kb/guidance/`, `kb/workforce/`, `kb/exemplar/` | ① One `.md` per section + its `.md.metadata.json`. **Only `kb/` is synced to Bedrock.** |
| `checklist/ceph_competencies.json` | ② The 22 competencies, CEPH's interpretations, and `does_not_count` rules, all word for word |
| `policies/` | ③ `phact_default.json` + 2 fictional demo schools |
| `kb_ids.json` | The live knowledge base's IDs and ARNs (written by `create_kb.py`) |
| `tests/retrieval_tests.json` | 16 questions, each with the document and section that must come back in the top 3 |

**Original PDFs** stay in `data/reference/`. `scripts/upload_kb.py` sends each one to S3 as `originals/<doc_id>.pdf`, outside the synced `kb/` prefix, so citation links can open it. They aren't copied here, which saves about 55 MB.

## How the files are made

```bash
brew install poppler                       # pdftotext / pdfinfo
python3 scripts/prepare_kb.py              # all documents (or --doc aspph-ai-framework)
python3 scripts/check_ceph.py              # checklist vs the CEPH PDF
```
`prepare_kb.py` extracts the listed pages and cuts at the heading lines. It removes only junk (running headers and footers, page numbers), and re-flows broken lines into paragraphs. It then runs a **fidelity check: the output's words must equal the source's words, in order.** It never overwrites a file you've edited by hand (use `--force` to regenerate).

## Your review checklist (before anything is uploaded)

For each section file, with the PDF open at the pages in `manifest.json`:
1. **Nothing missing:** every paragraph, list and heading on those pages is there.
2. **Nothing extra:** no page furniture, captions of unrelated images, or text from a neighboring section.
3. **Readable structure:** headings on their own line, lists as lists, no paragraph glued to a heading.
4. **Wording untouched.** Fix only extraction damage, such as a lost hyphen ("SDoHinformed" → "SDoH-informed"). Never rephrase.
5. **Metadata right:** title, section, `source_type`, year.
6. Set `"reviewed": true` for that section in `manifest.json`. **`upload_kb.py` refuses to upload until every section is reviewed.**

**What the MVP pass fixed** (each file's `fix` is in `manifest.json`): the 4 Competency Mapping tables were rebuilt into skill-area headings from the page images. Stray page-number text was removed. The Shared Vision diagram fragments were replaced by its labels. Chart and table residue was removed from Leadership › Results, including applicant-demographics numbers that had lost their labels. A lost hyphen and a merged subtitle were fixed in the AI Framework.

**Reviewed by:** Claude, using automated checks plus page images for every fixed file. A human spot-check before the demo is still a good idea.

## Metadata format

```json
{ "metadataAttributes": { "doc_id": "aspph-ai-framework", "title": "ASPPH AI Framework",
  "section": "Teaching and Learning", "source_type": "guidance", "year": 2026,
  "publisher": "ASPPH", "original": "originals/aspph-ai-framework.pdf#page=7" } }
```
At most 900 bytes (S3 Vectors allows 1 KB); `prepare_kb.py` checks.
