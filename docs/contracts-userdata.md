# User data contracts (frozen Nov 4)

Accounts, user data and the ASPPH admin. Change only with the team's agreement: every layer
(`playground/userdata.py`, the `/api/...` routes, `playground/index.html`) depends on these shapes.
Built to run on EC2 now and on **Lambda** at the end: nothing that matters lives on the server's disk or in memory.

## Who: Cognito user pool `phact-users`
- Sign-in with **email + password**. The password is stored and checked by Cognito, never by PHACT.
- Attributes: `email`, `name`. The stable user id is the Cognito `sub` (a UUID).
- Groups (role): `faculty` (default at sign-up), `aspph-staff`, `school-admin`.
- App client `phact-web`: no secret, flows `USER_PASSWORD_AUTH` + `REFRESH_TOKEN_AUTH`.

## Session
After login the server sets cookie `phact_session` = `base64url(json).hmac_sha256`, HTTP-only, SameSite=Lax, 12 h.
Payload: `{"sub", "email", "name", "role", "exp"}`. The signing key comes from env `PHACT_SECRET`
(on AWS: an SSM/Secrets parameter; locally: `playground/.uploads/session_secret`, generated once).
**The user id is taken only from the session, never from a request body or URL.**
`PHACT_AUTH=1` turns accounts on. Off (local default) = one implicit local user, today's behaviour.

## DynamoDB table `phact-app` (PK, SK strings; on-demand; encrypted)
| PK | SK | Attributes |
|---|---|---|
| `USER#<sub>` | `PROFILE` | `email, name, role, created_at, prefs{level, format, stance, comfort, template, notes, name, inst}` |
| `USER#<sub>` | `COURSE#<code>` | `course{code, name, level, format, size, ai_stance, ai_comfort, notes, description}`, `summary{documents, changes, accepted, updated_at}`, `progress_key` |
| `USER#<sub>` | `EVENT#<iso8601>#<4 hex>` | `type` (login, signup, upload, analyze, decision, export, submit), `course`, `detail` (≤ 300 chars) |
| `SUBMISSION#<id>` | `META` | `owner_sub, course_code, title, status` (pending, approved, returned, withdrawn), `consent_at, summary, s3_key, reviewer, review_note, published_doc_ids` |
| `SOURCE#<doc_id>` | `META` | `title, source_type, year, family, status` (active, secondary, retired), `published_by, published_at` |
| `AUDIT` | `<iso8601>#<4 hex>` | `actor_sub, actor_email, action, target, detail` |

## S3 bucket `phact-userdata-<account>-us-west-2` (private, encrypted)
| Key | Holds |
|---|---|
| `users/<sub>/courses/<code>.json` | the course's full progress: today's `phact.session.<code>` (syllabus document + `materials` + `refs`) |
| `users/<sub>/uploads/<doc_id>.<ext>` | the original uploaded file |
| `users/<sub>/uploads/<doc_id>.pii.json` | the hidden-name map (tag → real value); read only by the export |
| `submissions/<id>.json` | a scrubbed copy of a shared syllabus + PHACT's quality summary |

Course codes in keys are URL-encoded.

## API (JSON; every route except `auth/*` requires a session when `PHACT_AUTH=1`)
| Route | Does |
|---|---|
| `POST /api/auth/signup` `{email, password, name}` | create account (faculty), log in |
| `POST /api/auth/login` `{email, password}` | set the session cookie |
| `POST /api/auth/logout` | clear it |
| `GET /api/me` | `{sub, email, name, role}` or 401 |
| `GET/PUT /api/data/profile` | profile + prefs |
| `GET /api/data/courses` | `[course + summary]` |
| `PUT /api/data/courses/{code}` `{course}` · `DELETE` | save / delete a course (DELETE also removes its progress) |
| `GET/PUT /api/data/progress/{code}` | the full progress JSON |
| `GET /api/data/events?limit=` · `POST {type, course, detail}` | history |
| `/api/admin/...` | `aspph-staff` only (Phases 9–11) |
