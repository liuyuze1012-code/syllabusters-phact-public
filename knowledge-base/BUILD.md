# Building the knowledge database

The step-by-step plan for the three knowledge stores the AI reads. Owner: Gavin. The harness that reads them is in [../agent/HARNESS.md](../agent/HARNESS.md).

| Store | What it is | How the AI gets it | Built from |
|---|---|---|---|
| ① Knowledge base | ASPPH guidance, workforce reports, later exemplars | **Searched** (Bedrock KB over S3 Vectors) | `kb/` in this folder |
| ② CEPH checklist | 22 competencies + evidence rules | **Loaded whole** in every Map prompt | `checklist/ceph_competencies.json` |
| ③ AI policies | PHACT default + demo school policies | **Looked up by school** (DynamoDB, seeded by script) | `policies/*.json` |

## Folder layout

```
knowledge-base/
  kb/                           ← ONLY this prefix is the Bedrock data source
    guidance/
      ai-framework__teaching-and-learning.md
      ai-framework__teaching-and-learning.md.metadata.json
      ...
    workforce/
      competency-mapping__<section>.md (+ .metadata.json)
  sources.json                  ← the inventory: every document, tag, year, how it is split
  manifest.json                 ← written by prepare_kb.py: per-section results + reviewed flag
  checklist/ceph_competencies.json
  policies/phact_default.json, demo_potomac.json, demo_lakeshore.json
  tests/retrieval_tests.json
```

**Why originals live outside `kb/`:** they stay in `data/reference/`, and `scripts/upload_kb.py` sends them to S3 as `originals/<doc_id>.pdf`. If the PDFs sat in the synced folder, Bedrock would index them too. Every passage would then exist twice, once from our clean Markdown and once from the messy PDF, and the messy copy would show up as citations.

## Key decisions

### 1. One file per section, not one file per document
Bedrock applies a file's metadata to **every chunk from that file**. So if the whole AI Framework is one file, every chunk is just "ASPPH AI Framework." If each section is its own file, every chunk knows its section, and citations read **"ASPPH AI Framework › Teaching and Learning."** Professors can check that, and the Supervisor can reason about it.

### 2. Fixed-size chunks (~300 tokens, 20% overlap), not hierarchical
AWS warns that with S3 Vectors, hierarchical chunking stores parent/child context as metadata and can exceed the per-vector metadata limit. Custom metadata is capped at **1 KB and 35 keys per vector** ([AWS: S3 Vectors prerequisites](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html)). Since sections are already split by hand, fixed-size chunking within a section is enough.

### 3. Small metadata, with the right keys filterable
```json
{ "metadataAttributes": {
    "doc_id": "aspph-ai-framework",
    "title": "ASPPH AI Framework",
    "section": "Teaching and Learning",
    "source_type": "guidance",
    "year": 2025,
    "publisher": "ASPPH",
    "original": "originals/aspph-ai-framework.pdf#page=4" } }
```
- **Filterable:** `source_type`, `year`, `doc_id`, used by retrieval filters.
- **Non-filterable** (set when creating the S3 vector index): `AMAZON_BEDROCK_TEXT` and `AMAZON_BEDROCK_METADATA` (**required**, or ingestion can fail), plus `title`, `section` and `original`, which are only displayed.
- Keep values short. The whole block must stay well under 1 KB.

### 4. Exact wording, light cleaning
Remove page numbers, running headers and footers, navigation menus, and broken hyphenation. **Don't paraphrase or summarize.** The chunk text becomes the snippet professors see, and it must match the PDF they open.

## Build steps, in order of value

### Step 1. CEPH checklist (do this first; the Map step can't run without it)
1. Type the 22 MPH foundational competencies from `data/reference/CEPH competency guidelines.pdf` **word for word**, grouped by CEPH's 8 domains.
2. For each one, add CEPH's interpretation: `does_not_count` (e.g. a role-play alone, for #21) and `counts_if`.
3. A teammate checks it line by line against the PDF.

```json
{ "source": "CEPH Accreditation Criteria, D2 MPH Foundational Competencies",
  "competencies": [
    { "id": 21, "domain": "Interprofessional and/or Intersectoral Practice",
      "text": "…exact CEPH wording…",
      "does_not_count": ["…"], "counts_if": "…" } ] }
```

### Step 2. AI Framework, split by section (the most-cited source)
Sections to create (check headings against the PDF): introduction, each of the six focus areas, Teaching and Learning, Practice and Research, Policy/Regulatory/Architectural, Strategic Directions, recommendations. Write one `.md` per section with its metadata file.

### Step 3. Workforce sources
Competency Mapping report (10 leadership skill areas), then the Leadership Report 2025. Tag both `workforce`.

### Step 4. Secondary guidance
Shared Vision 2024, then optionally CPH competencies and the Applied Learning page. Tag them `guidance`.

### Step 5. Retrieval tests (write these before syncing)
2–3 questions per document, each with the file that must come back in the top 3:
```json
[ { "q": "How should faculty define acceptable student use of AI?",
    "expect_doc": "aspph-ai-framework", "expect_section": "Teaching and Learning" },
  { "q": "Leadership skills public health employers need",
    "expect_doc": "competency-mapping" } ]
```
A script runs each query through `Retrieve` and prints pass or fail. "Sync succeeded" doesn't prove the right passages come back; this test does.

### Step 6. AI policies (store ③)
1. `phact_default.json`: rules built from the AI Framework's three modes (complete prohibition, restricted use, transparent collaborative use). Label it **"PHACT default, based on the ASPPH AI Framework,"** never as ASPPH's own policy.
2. Two demo schools with clearly different rules, e.g. one "restricted, disclosure required" and one "open, licensed Copilot." These power the two-school demo.

```json
{ "school_id": "_default", "label": "PHACT default, based on the ASPPH AI Framework",
  "allowed_range": ["prohibited", "restricted", "collaborative"],
  "rules": [ { "id": "DEF-AI-1", "text": "Each course states its AI-use level in the syllabus." },
             { "id": "DEF-AI-2", "text": "Any permitted AI use must be disclosed by the student." } ] }
```

### Step 7. Load and sync (with the backend teammate)
1. Upload `kb/` and `originals/` to the knowledge bucket under those prefixes.
2. Data source inclusion prefix: `kb/`. Fixed-size chunking: 300 tokens, 20% overlap. Titan Text Embeddings v2 (1,024 dimensions), cosine distance.
3. `StartIngestionJob`, then run `tests/retrieval_tests.json`. Fix the files, not the questions, until every test passes.
4. Seed `policies/*.json` into DynamoDB with the seed script.

## Rules to keep
- **Never put test syllabi in `kb/`.** PHC 6149 and the 5 synthetic syllabi are test inputs.
- **SOPHE/CHES is not loaded.** It has a no-reproduction notice, so cite it by number only.
- **AI claims cite `guidance`** (the AI Framework). Workforce files never mention AI.
- **Resets:** never delete the vector index while the data source is connected. Delete the data source, recreate the index, recreate the data source, then sync.

## Time estimate (one person with Claude Code)
| Step | Time |
|---|---|
| 1 Checklist | 1.5 h |
| 2 AI Framework | 1 h |
| 3–4 Other sources | 1.5 h |
| 5 Retrieval tests | 45 min |
| 6 Policies | 45 min |
| 7 Load + sync + fix | 1 h |
| **Total** | **~6.5 h**: about half the build time. Steps 1, 2 and 5 are the must-haves for Day 1. |
