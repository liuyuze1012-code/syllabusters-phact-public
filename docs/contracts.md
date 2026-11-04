# Contracts

The three agreements that let the three tracks work in parallel. **Change them only with everyone's agreement**, then update the code in the same pull request.

## 1. Web API (frontend ↔ backend)

All routes except `/health` need a Cognito ID token. `user_id` and `school_id` always come from the token.

| Method | Path | Who | Body → Response |
|---|---|---|---|
| GET | `/health` | public | → `{ok, agent_mode}` |
| GET | `/api/me` | any | → profile, school, groups |
| PUT | `/api/me/preferences` | faculty | AI stance, comfort, notes |
| GET | `/api/courses` | faculty | → courses |
| POST | `/api/courses` | faculty | `CourseIn` → course |
| POST | `/api/courses/{code}/upload-url?filename=` | faculty | → `UploadUrlOut` (presigned PUT, 5 min) |
| POST | `/api/courses/{code}/syllabus?key=` | faculty | → extracted, scrubbed text for confirmation |
| PUT | `/api/courses/{code}/settings` | faculty | confirmed competencies, AI target, assessment types |
| POST | `/api/jobs` | faculty | `JobIn` → **202** `JobOut` |
| GET | `/api/jobs/{id}` | faculty | → `JobOut` (poll every 3 s) |
| GET | `/api/analyses/{id}` | faculty | → the `AnalyzeResponse` fields + edit statuses |
| POST | `/api/edits/{id}/decision` | faculty | `DecisionIn` |
| POST | `/api/exports?analysis_id=` | faculty | → download link |
| GET / PUT | `/api/school`, `/api/school/policy` | school-admin | school profile, AI rules |
| GET | `/api/review/queue`, `/api/review/{id}` | aspph-reviewer | source requests, previews |
| POST | `/api/review/{id}/decision` | aspph-reviewer | `approve_publish` · `send_back` · `reject`, notes, corrected metadata. Approve starts publish + sync + tests |
| POST | `/api/review/{id}/retire` · `/api/review/submit` | aspph-reviewer | remove an outdated source · upload a new document |

Shapes: [`backend/app/schemas.py`](../backend/app/schemas.py).

## 2. Agent (backend worker ↔ AI harness)

Defined once in [`shared/phact_contracts/agent.py`](../shared/phact_contracts/agent.py), with samples in [`shared/fixtures/`](../shared/fixtures/).

```
IN   AnalyzeRequest  { mode:"analyze", job_id, syllabus_text (scrubbed), course, confirmed_competencies, targets, context }
OUT  AnalyzeResponse { ok:true, job_id, outline, competencies[22], ai_rating, assessments, edits[], passages[], meta }
  or ErrorResponse   { ok:false, job_id, error, message }

IN   ReviseRequest   { mode:"revise", job_id, analysis_id, message (checked),
                       scope: "edits" | "section" | "all", target_edit_ids, section_id,
                       history (last 6 turns), outline, edits, passages, context }
OUT  ReviseResponse  { ok:true, job_id, kind: "change" | "add" | "question",
                       edits[] (new versions or new edits), new_passages[], removed_edit_ids[], reply, meta }
     kind "question" never changes edits or passages (the contract rejects it).
     Undo ("go back to v1") is handled by the backend alone: no agent call.
```

## 3. Edit (everyone)

The unit the Edit studio shows, the professor decides on, and the export applies.

```json
{ "edit_id": "E2", "version": 1, "section_id": "week-6", "op": "replace",
  "original": "exact text being replaced", "proposed": "new text",
  "rationale": "AI suggestion, no citations here",
  "evidence": [{ "id": "P2", "title": "ASPPH AI Framework", "snippet": "exact chunk text", "uri": "s3://…" }],
  "school_rule": "DEF-AI-2", "ceph": [21], "reflection_activity": "…",
  "supervisor": "pass", "status": "draft" }
```
- `op`: `replace` · `insert_after` · `delete`. For `replace`/`delete`, `original` must appear word for word in the section.
- `evidence` = from sources; `rationale` = AI suggestion. The UI must show them differently (US-9).
- `status` changes only through `POST /api/edits/{id}/decision`. Export uses `accepted` only (US-11).
