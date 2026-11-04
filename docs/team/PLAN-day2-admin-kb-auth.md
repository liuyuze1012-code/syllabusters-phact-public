# Day 2 plan: ASPPH source library, university admin, accounts

Draft, Nov 4. The professor side (agent + playground) exists and is being cleaned up separately.
This plan covers the three things that make PHACT a product rather than a demo:

| Part | Who uses it | One-line goal |
|---|---|---|
| **A. ASPPH source library** | ASPPH staff (`aspph-reviewer`) | Add, replace, demote or retire the documents PHACT cites, in minutes, without an engineer |
| **B. University admin** | A school's admin (`school-admin`) | Set the school's AI policy once; every professor's analysis obeys it |
| **C. Accounts and data** | Everyone | Real logins, roles, and each user's work saved in a database instead of the browser |

**Most of the skeleton already exists from the Day 0 scaffold. Fill it in, don't redesign it:**
- `infra/lib/auth-stack.ts`: Cognito user pool, no self sign-up, groups `faculty` / `school-admin` / `aspph-reviewer`, immutable `custom:school_id`
- `infra/lib/data-stack.ts` + `backend/app/db.py`: one DynamoDB table, key layout already written (`SCHOOL#…`, `SOURCE#…`, `JOB#…`)
- `infra/lib/intake-stack.ts` + `backend/app/routes/review.py`: the source-intake pipeline and reviewer routes (stubs)
- `backend/app/routes/school.py` + `services/context_builder.py`: school policy routes and the "school > professor" context order (stubs)
- `knowledge-base/policies/*.json`: the policy shape (`allowed_range`, `rules`, `licensed_tools`) with two demo schools

---

## A. ASPPH source library (document lifecycle)

### The problem
A new *2026 Workforce Report* arrives. PHACT must:
1. cite the 2026 edition by default,
2. stop citing the 2025 edition, or use it only as a labelled fallback,
3. never cite a retired document,
4. tell professors whose accepted edits cite the old edition.

### The rule from the research
Metadata only helps if **retrieval filters on it**. Storing "superseded" without filtering still lets old chunks reach the prompt and the citation ([Zimaspace on superseded citations](https://shop.zimaspace.com/blogs/tech-ai-hub/rag-citations-point-superseded-document-versions)). Use a **stable document identity plus an explicit revision status**, filter at query time, and **switch versions atomically**: verify the new edition first, then flip statuses ([Zimaspace on versioning](https://shop.zimaspace.com/blogs/tech-ai-hub/document-versioning-keeps-rag-answers-current-files)). A hard filter beats "penalise older documents" for policy-like content ([dev.to walkthrough](https://dev.to/alaikrm/when-rag-gives-wrong-answers-a-debugging-walkthrough-2bn8)).

### Data model
**Family vs. edition.** `doc_family` is stable ("aspph-workforce-report"); each upload is an **edition** (2025, 2026).

DynamoDB `SOURCE#<edition_id>` item:
| Field | Example | Notes |
|---|---|---|
| `edition_id` | `aspph-workforce-report-2026` | primary key |
| `doc_family` | `aspph-workforce-report` | groups editions |
| `edition` | `2026` | year or version label |
| `status` | `draft` → `in_review` → **`active`** / **`secondary`** / **`retired`** | the lifecycle |
| `supersedes` / `superseded_by` | `…-2025` | links editions |
| `source_type` | `guidance` / `workforce` / `exemplar` | already used by retrieval |
| `priority` | `must` / `should` | already in `manifest.json` |
| `effective_date`, `published_at`, `reviewed_by`, `notes` | | audit trail |
| `sections` | list of `kb/…md` files + pages | from `prepare_kb.py` |
| `content_sha` | | detects re-uploads and duplicates |

**Each chunk's `.metadata.json` gains** `doc_family`, `edition` and `status` (alongside the existing `doc_id`, `title`, `section`, `source_type`, `year`, `original`).

**What the statuses mean at retrieval** (`agent/retrieval.py`):
| Status | Default search | Fallback | Shown to professors as |
|---|---|---|---|
| `active` | ✅ | | normal citation |
| `secondary` | ❌ | ✅ only if active results are weak (below the score cut-off or too few) | "older edition (2025)" tag on the citation |
| `retired` | ❌ | ❌ | never |

Implementation: add `{"equals": {"key": "status", "value": "active"}}` to the existing `source_type` filter with `andAll`. If fewer than *k* passages pass `MIN_SCORE`, run a second search with `status = secondary` and mark those passages `older_edition: true`.

### The pipeline (admin uploads a document)
1. **Upload** (PDF/DOCX) in the Sources page. Store the original in `originals/`.
2. **Extract**: reuse `agent/pdf_textract.py` (tables as rows).
3. **Split into sections + clean**: reuse `scripts/prepare_kb.py` logic (running headers removed, section titles, page ranges).
4. **Automated checks**, shown to the reviewer:
   - duplicate? (`content_sha`)
   - **"looks like a new edition of …"**: same family title or high text overlap with an active document → suggest *Replace*
   - metadata complete (title, type, year), sections non-empty, page links valid
5. **Reviewer decides** (one screen): **Replace** the older edition (old → `secondary` or `retired`, admin's choice), **add alongside** (both active), or **send back**.
6. **Publish**: write the files to `kb/`, then ingest **only those documents** with `IngestKnowledgeBaseDocuments` (per-document, no full re-sync, up to 25 documents per call; content must come from S3 for an S3 data source) ([AWS: direct ingestion](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-direct-ingestion.html), [adding documents](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-direct-ingestion-add.html)). Never run it at the same time as `StartIngestionJob`.
7. **Smoke test**: run 3–5 search tests (as in `knowledge-base/tests/retrieval_tests.json`) against the new edition. Only if they pass…
8. **…atomic switch**: new edition → `active`, old edition → `secondary`/`retired`. That means re-ingesting the old edition's chunks with the updated `status` metadata, or a full `StartIngestionJob` (38 sections took ~1–2 min). **Test first thing:** whether direct ingestion can update metadata alone is not documented, so plan for re-ingesting content from S3.
9. **Retire**: delete from the index (`DeleteKnowledgeBaseDocuments`) and from `kb/`. Keep `originals/` and the `SOURCE#` record for the audit trail.

**For the hackathon:** run steps 2–9 inside the backend (a FastAPI background task), **not** Step Functions. The `intake-stack.ts` Step Functions design (one `.waitForTaskToken` human gate) is the production story for the pitch, and it's 3–4 hours of CDK on its own. Cut it unless someone is free.

### Ripple to professors (the differentiator)
When an edition is replaced or retired, every saved edit citing one of its passages gets a badge in the workspace: **"Source updated: P3 is from the 2025 report, which ASPPH replaced with 2026. ↻ Refresh sources"**. Refresh re-runs retrieval and the Supervisor for that edit only (reuses `/api/analyze_more`-style incremental logic). This needs each saved edit to store the `edition_id` of each cited passage. Add `edition_id` to the `Evidence` contract.

### Sources page (ASPPH admin UI)
- **Library table**: title · type · edition · status chip (active/secondary/retired) · sections · "cited in N edits" · last reviewed
- **Upload** button → review screen: original PDF on the left, cleaned sections on the right, check results, and the Replace / Alongside / Send back choice
- Row actions: **Demote to secondary**, **Retire**, **Restore**, **Run search test**
- **Search test panel**: type a question and see which passages come back, with their status (the playground's KB search, upgraded)

---

## B. University admin (school policy)

### Order of authority (already decided; see `context_builder.py`)
**School policy (binding) > professor (may be stricter, never looser) > course > memory.** ASPPH guidance informs *what* to suggest. It doesn't override a school's rules.

### Policy object (`SCHOOL#<sid>` / `POLICY`, versioned)
Extend `knowledge-base/policies/*.json`:
```json
{
  "school_id": "potomac", "version": 3, "effective_date": "2027-01-01",
  "allowed_range": ["prohibited", "restricted"],
  "rules": [{"id": "POT-AI-1", "text": "AI may be used for brainstorming and editing only, never for graded writing."}],
  "licensed_tools": ["Microsoft Copilot (university licence)"],
  "disclosure_required": true,
  "data_rules": ["Never upload student data or PHI to AI tools."],
  "source_document": "originals/policies/potomac-ai-policy-2026.pdf",
  "confirmed_by": "<admin user id>", "confirmed_at": "…"
}
```

### Admin flow
1. **Upload the school's AI policy** (PDF or paste) → Claude extracts a **draft**: `allowed_range`, numbered rules, licensed tools, data rules. This is an LLM call with structured output, like Station 1.
2. **Admin reviews and edits** each rule (the draft is never saved without a human confirming it) → **Save** as a new version (old versions kept).
3. **Preview**: "This is what your professors will see" (the stance options they can choose, the rules shown in the workspace).

### Enforcement: three layers, the same pattern as the course AI ban
| Layer | What it does | Where |
|---|---|---|
| **UI** | A professor can only pick a course stance inside `allowed_range`; banned options are greyed out with "Your school doesn't allow this" | course form |
| **Prompt** | School rules go **first** as binding `<school_rule>` blocks; course stance can't exceed them | `context_blocks`, `make_context` |
| **Code gate** | If the school's range is `prohibited` only → `violates_ban` runs on **every** edit, whatever the course says. An edit naming an AI tool **not** in `licensed_tools` fails. An edit that touches AI use must cite a school rule id (already required). | `gates.check_edit` |

The Supervisor already checks rule compliance; it gets the school rules too.

### Admin dashboard (keep small)
Faculty using PHACT · courses analyzed · % of edits accepted · policy version in force. Aggregates only, no syllabus content (professors' work is theirs).

---

## C. Accounts, auth and database

### Auth: Cognito (already in CDK)
- No self sign-up. School admins **invite** faculty (`AdminCreateUser`), ASPPH invites school admins and reviewers.
- Groups: `faculty`, `school-admin`, `aspph-reviewer`. **`school_id` comes only from the token, never the request body** (already the rule in `auth.py`).
- Frontend: Amplify Auth or the Hosted UI (SRP flow is configured).
- **Hackathon fallback** if a Cognito deploy fights the sandbox: `DEV_AUTH=1` with three seeded users (one per role) and a role-switcher login screen. Clearly labelled; same API, so swapping in Cognito later changes one function.

### Database: DynamoDB single table (layout already in `db.py`)
Move what the playground keeps in `localStorage` into the table:
| Item (SK under `SCHOOL#<sid>#USER#<uid>`) | Holds |
|---|---|
| `PROFILE` | name, preferences, defaults (from Settings) |
| `COURSE#<code>` | course details |
| `COURSE#<code>#SYL#v<n>` | each uploaded syllabus version (file in S3 `uploads/`) |
| `ANALYSIS#<code>#<aid>` | outline, competencies, passages (with `edition_id`), timings |
| `EDIT#<aid>#<eid>#V<n>` | every edit version |
| `DECISION#<ts>` | accept/reject/hand-edit, who and when (the audit trail) |
| `SESSION#<aid>` | chat history |

- **The personal-data map** (tag → real name) stays out of DynamoDB items the agent can read: store it encrypted (KMS) next to the upload in S3 and only read it in the export route.
- Every query is scoped by `school_id` + `user_id` from the token (tenant isolation by key design).
- Implement the `db.py` helpers listed in its TODO, then point the routes in `routes/` at them.

---

## Build order for tomorrow (one day, four people)

| # | Block | Est. | Depends on |
|---|---|---|---|
| 1 | **Contracts first** (30 min, together): `SourceEdition`, `SchoolPolicy` v2, `Evidence.edition_id`, retrieval status filter | 0.5 h | none |
| 2 | **C. DB helpers + DEV_AUTH users**, then real Cognito if it deploys | 3–4 h | 1 |
| 3 | **A. Status filter + fallback in `retrieval.py`**; add `status` to all 38 sections' metadata, re-sync, run the 16 retrieval tests | 2 h | 1 |
| 4 | **A. Publish / replace / retire backend** (direct ingestion + smoke test + atomic switch) | 3 h | 3 |
| 5 | **B. Policy extract → confirm → save**, then the three enforcement layers + tests | 3 h | 1 |
| 6 | **UIs**: Sources page, School admin page, login/role switch (playground first, ported later) | 3 h | 2, 4, 5 |
| 7 | **Ripple**: "source updated" badge + refresh for one edit | 1.5 h | 4 |
| 8 | **Demo script**: upload 2026 report → replaces 2025 → professor sees the badge; school bans AI → professor can't choose "open", gate blocks AI edits | 1 h | all |

**Cut list if time runs short (in order):** Step Functions intake (keep the in-API version) → admin dashboard stats → ripple refresh (keep the badge only) → real Cognito (keep DEV_AUTH).

## Open questions to settle in the morning
1. **Can `IngestKnowledgeBaseDocuments` update metadata only?** Test in 10 minutes; if not, re-ingest from S3 (fine at our size).
2. **Does the S3 Vectors index accept `status` as a filterable key?** `source_type` already filters, so new keys should too. Confirm `status` isn't in the non-filterable list.
3. **Sandbox permissions for Cognito/CDK deploys.** Workshop Studio roles sometimes block IAM creation. Decides DEV_AUTH vs. Cognito.
4. **Who are the demo personas?** Suggest: "Dr. Rivera" (faculty, Potomac), "Potomac admin", "ASPPH reviewer". Fictional, consistent with the demo policies.
5. **`secondary` or `retired` by default on Replace?** Suggest `secondary` for 1 year (still citable as "older edition"), then retire. ASPPH should decide.
