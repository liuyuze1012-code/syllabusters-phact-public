# Build plan: accounts + user database, then the ASPPH admin

Nov 4. Two features, built in this order because the second depends on the first:
- **A. Accounts and user database**: sign up / log in, roles, every professor's courses, progress and history saved to AWS instead of the browser.
- **B. ASPPH admin**: staff log in to (1) manage knowledge-base sources (add, replace, retire) and (2) review syllabi professors submit as examples, and publish the good ones.

Status: Cognito pool `phact-users` exists (`us-west-2_30rtK08T1`, from an interrupted run of `scripts/create_userdb.py`). No DynamoDB table or S3 bucket yet. The script is safe to rerun.

## Rules that keep bugs down
1. **Contracts first, frozen.** Keys, item shapes, API routes and roles are written down in Phase 0 and not changed casually afterwards. Most integration bugs are two pieces disagreeing about a shape.
2. **The app keeps working after every phase.** Accounts sit behind a switch (`PHACT_AUTH=1`). Off = today's behaviour, so local development never breaks mid-build.
3. **Each phase ends with a test gate.** Don't start the next phase until its checks pass.
4. **Bottom-up:** storage → data functions → API → UI. Each layer is tested before anything is built on it.
5. **No destructive migrations.** Browser data is *copied* to the account, never deleted until the import is confirmed.
6. **Scripts are safe to rerun.** Test users are prefixed `test-` and cleaned up.
7. **Permissions grow per phase** (least privilege), and the EC2 role is updated only when deploying.
8. **Deploy only at two checkpoints** (end of A and end of B), never mid-feature.

---

## Feature A: accounts and the user database

### Phase 0. Contracts (30 min)
Write `docs/contracts-userdata.md` and freeze it:
| Where | Key / path | Holds |
|---|---|---|
| Cognito `phact-users` | email login | password (hashed by AWS), name; groups `faculty`, `aspph-staff`, `school-admin` |
| DynamoDB `phact-app` | `USER#<sub>` / `PROFILE` | email, name, role, institution, preferences (today's Settings) |
| | `USER#<sub>` / `COURSE#<code>` | course details + progress summary (changes, accepted, documents) + S3 key + `updatedAt` |
| | `USER#<sub>` / `EVENT#<iso time>#<rand>` | history: `login`, `upload`, `analyze`, `decision`, `export` + small details |
| S3 `phact-userdata-…` | `users/<sub>/courses/<code>.json` | the course's full progress (today's `phact.session.<code>`: syllabus doc + materials + references) |
API (all under `/api`, all derive the user from the session, never from the request body):
`auth/signup`, `auth/login`, `auth/logout`, `me` · `data/profile` GET/PUT · `data/courses` GET · `data/courses/{code}` PUT/DELETE · `data/progress/{code}` GET/PUT · `data/events` GET/POST.
**Done when:** the doc exists and the team agrees.

### Phase 1. Infrastructure (20 min)
Finish `scripts/create_userdb.py` (reuses the pool, creates the app client, groups, table and private encrypted bucket; writes `playground/userdb_ids.json` with ids only).
**Gate:** run it twice; the second run changes nothing; all four resources are visible in the console.

### Phase 2. Data functions (1 h)
`playground/userdata.py`: plain functions with no web code: `get_profile/put_profile`, `list_courses/put_course/delete_course`, `get_progress/put_progress` (S3), `log_event/list_events`. Every function takes the user id as its first argument.
**Gate:** tests against the real table with a `test-` user: write → read → list → delete; a second test user can't see the first one's data; then clean up.

### Phase 3. Login on the server (1 h)
Sign up (Cognito `SignUp` + admin confirm for the demo, so no email code is needed), log in (`USER_PASSWORD_AUTH`), log out, `me`. After login the server sets a **signed, HTTP-only session cookie** (12 h). A `current_user` check guards routes; `require_role("aspph-staff")` guards admin routes. Behind `PHACT_AUTH=1`.
**Gate (curl):** sign up → log in → `me` works · wrong password → 401 · no cookie → 401 on AI routes · faculty → 403 on an admin route · auth off → everything works as today.

### Phase 4. Data API (45 min)
Routes from Phase 0 on top of Phase 2. Course saves also update the DynamoDB summary.
**Gate:** two test accounts, each saves a course; each sees only its own; a 600 KB progress file round-trips (proves the S3 design).

### Phase 4b. Uploaded files to S3 (30 min)
Today the original uploads and the hidden-name maps (needed to edit the original Word file and restore names on download) sit on the server's disk in `playground/.uploads/`. Move them to the user bucket: `users/<sub>/uploads/<doc_id>.<ext>` and `users/<sub>/uploads/<doc_id>.pii.json`. `_doc()` in `server.py` becomes read/write through S3, scoped to the signed-in user.
**Gate:** upload → export works; it still works after deleting the server's local copy; another user can't fetch the file by guessing its id.

### Phase 5. The page uses the account (1.5 h)
- A login / sign-up screen before Home, and the user's name + **Log out** in the sidebar.
- Replace the page's browser storage with an **account-backed store**: load the user's profile, course list and progress at login (so the rest of the page code stays unchanged), then save changes to the server automatically (debounced, last save wins).
- **One-time import:** "We found 3 courses saved in this browser. Add them to your account?"
**Gate (browser):** create a course → reload → still there · log in from a second browser → same courses · log out → nothing visible · auth off → the old behaviour.

### Phase 6. History (30 min)
The page logs events on upload, analyze, accept/reject and export; the server logs logins. Settings gets a **Your activity** list.
**Gate:** do each action once and see it listed with the right time.

### Phase 7. Deploy checkpoint A (30 min)
Add Cognito, DynamoDB and user-bucket permissions to `PhactDemoServerRole` (only these resources), redeploy, turn on `PHACT_AUTH=1`, and create demo accounts (one professor, one ASPPH staff). Their passwords go in a **git-ignored local file**, not in chat or git.
**Gate:** the public link asks for a login; the demo professor's work survives a server restart.

---

## Feature B: the ASPPH admin (needs Feature A's roles)

### Phase 8. Lifecycle groundwork (45 min)
Add `status: active` to all 56 knowledge-base documents; retrieval searches only `active` (plus `secondary` as a labelled fallback); re-sync.
**Gate:** all 26 retrieval tests still pass. This proves the filter didn't hide anything.

### Phase 9. Sources backend (2 h)
`/api/admin/sources` (aspph-staff only): list · upload → Textract → sections preview + metadata (title, type, year, family, "replaces…") · **publish** (write to `kb/`, PDF to `originals/`, ingest, run a search test, only then mark active) · set status (active / secondary / retired) · every action → an `AUDIT#` event.
**Gate:** publish a test document → a search finds it · retire it → the search no longer returns it · the audit log shows both.

### Phase 10. Admin page: Sources tab (1.5 h)
A separate `/admin` page (staff login only): the library table, upload + review screen, status buttons, audit log.
**Gate:** do Phase 9's test through the UI; a professor account gets "no access".

### Phase 11. Example-syllabus submissions (2 h)
- **Professor:** "Share as an example syllabus" on a finished course → **consent screen** (what's shared, names removed, can withdraw) → a `SUBMISSION#` item + a scrubbed copy in S3 + PHACT's quality summary.
- **Admin, Submissions tab:** the queue → preview → choose the exemplary parts → tag (area, competencies, AIAS) → **Approve** (publishes through Phase 9 as `exemplar`) or **Return with a note**.
- **Professor:** sees the status; **Withdraw** retires it.
**Gate:** submit → approve → it appears in the knowledge base · withdraw → retired · a second professor can't see the first one's submission.

### Phase 12. Exemplars in analyses (1 h)
Retrieval adds approved exemplars as **"Example from a peer syllabus"** cards, never as [n] evidence citations (a peer syllabus isn't an ASPPH finding).
**Gate:** an analysis in the same area shows the example card; citations are unchanged.

### Phase 13. Final checkpoint (45 min)
All unit tests + 26 retrieval tests + an end-to-end demo script run → deploy → walk the demo on the public link.

---

## Time and the cut line
**A ≈ 5.5 h, B ≈ 8 h.** If time is short, keep A complete (it's what makes PHACT a real product) and from B build Phases 8–10 (sources) first; Phase 11 is the strongest *story* but can be shown with one seeded submission; Phase 12 can be described rather than built.
