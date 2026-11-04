# Assessment: the "master implementation prompt" vs. ASPPH's official spec vs. what exists

Nov 4. Done as the prompt asks: inspect first, compare, plan, then build in phases with tests.
Sources: the official repo `12turnbullb/us-breaking-barriers-2026/ASPPH` (Vision + **Technical Document**, user
stories, architecture appendix). The Technical Document there is identical to our copy, and it is
**the binding spec**. Where the pasted prompt disagrees with it, the official document wins.

## 1. Where the prompt conflicts with ASPPH's official Technical Document
| Topic | Pasted prompt | Official Technical Document | Decision |
|---|---|---|---|
| Infrastructure as code | SAM or Terraform | **AWS CDK (TypeScript)**, stacks Foundation/Auth/Data/Api/Observability | **CDK.** Our `infra/` scaffold already is CDK. |
| Long-running AI work | Step Functions | **API writes a QUEUED job, async-invokes a worker Lambda, UI polls `GET /api/jobs/{id}`** | **Async worker + polling** (spec'd, simpler). Step Functions only if a real multi-step need appears. |
| AI agents | Not mentioned | **Strands agents hosted on Bedrock AgentCore** (curriculum, competency) | **Wrap our harness as Strands agents on AgentCore**, keeping the code gates (see §4). |
| Roles | faculty, university admin, platform admin | Cognito groups **`faculty`, `aspph-admin`** | Use **`faculty` + `aspph-admin`** (rename our `aspph-staff`); keep `school-admin` as an optional extra. |
| Auth flow | Auth Code + PKCE, Managed Login | **Amplify Auth on the SPA**, Cognito authorizer on API Gateway | Amplify Auth with the Cognito managed login (that is Auth Code + PKCE). JWT checked at API Gateway, not our cookie. |
| SSO | SAML/OIDC-ready | **No MyASPPH SSO; pre-provisioned demo users** | Pre-provisioned users now; the pool is federation-ready. |
| API | HTTP API | API Gateway + Cognito authorizer, `/health` public, `/api/*` authorized | Either works; REST matches the spec's authorizer wording. |
| Region / account | n/a | `us-east-1`, ASPPH's account | **Our Workshop Studio sandbox is `us-west-2`, our sandbox account.** Keep us-west-2 (all services verified here); the CDK app takes region as a parameter so ASPPH can redeploy in us-east-1. |
| Guardrail | "where supported" | **At API input only + Comprehend pre-scrub; never on agent output** | Already built exactly this way. |
| Vector store | Avoid always-on vector DBs | Bedrock KB over **S3 Vectors** | Already built (pay-per-use, no cluster). |

## 2. What exists today
| Area | Status | Where |
|---|---|---|
| AI harness: read → map CEPH → retrieve → write → code gates → Supervisor; chat; assessments with AIAS 8-part designs; peer examples | ✅ working, tested live | `agent/` |
| Knowledge base: Bedrock KB + S3 Vectors, 23 docs / 56 sections, lifecycle status, citations to PDF pages | ✅ live, 26/26 retrieval tests | `knowledge-base/`, us-west-2 |
| Safety: Comprehend PII scrub/restore, Guardrail on chat input, student-work refusal | ✅ | `agent/safety.py` |
| Accounts + user data: Cognito pool, DynamoDB `phact-app`, S3 user bucket, history | ✅ tested (cookie session) | `playground/accounts.py`, `userdata.py` |
| ASPPH admin: sources (publish/replace/retire), example-syllabus review, audit log | ✅ tested | `playground/admin*.py/html` |
| Export: final + review DOCX, in-place Word edits | ✅ | `backend/app/services/export_docx.py` |
| UI | ✅ works, but **vanilla HTML/JS**, not React | `playground/index.html`, `admin.html` |
| React SPA | ⚠️ scaffold on mock data | `frontend/` |
| FastAPI-on-Lambda backend | ⚠️ scaffold (routes stubbed) | `backend/` |
| CDK stacks | ⚠️ scaffold (TODOs) | `infra/` |
| Hosting | ✅ Lambda + API Gateway (HTTPS); agent on AgentCore. The EC2 demo server was retired on Nov 4 | — |
| Upload hardening (presigned, quarantine, signature checks, malware scan) | ❌ | |
| Tenant registry, per-university quotas, usage/cost tracking | ❌ (per-call token stats only) | |
| CloudWatch alarms, WAF, GitHub Actions OIDC, dev/prod configs | ❌ | |
| Security/E2E test suites the prompt lists | partial (gates, isolation, auth basics) | |

## 3. AWS prerequisites (checked read-only in our sandbox, Nov 4)
✅ API Gateway (HTTP + REST) · Lambda · Amplify Hosting · **Bedrock AgentCore** · Step Functions · WAF · CloudWatch · CloudFormation/CDK (via `npx`, Node 20) · Cognito · DynamoDB · S3 · Textract · Comprehend · Bedrock KB.
❌ **GuardDuty (Malware Protection for S3) is denied** → malware scanning can't be demonstrated here; use file-signature/structure validation now and document GuardDuty Malware Protection for production.
⚠️ App Runner denied (irrelevant now). CDK bootstrap must be run once (`npx cdk bootstrap`).

## 4. Recommended plan (prioritized for a demo on Nov 5; each phase ends with tests)
**Time reality:** the prompt describes weeks of work. Ranked by what ASPPH's spec requires and what judges see.

| # | Phase | What | Est. |
|---|---|---|---|
| P1 | **Serverless backend (spec-aligned)** | Move the working playground API into `backend/` as FastAPI + Mangum on **Lambda behind API Gateway with the Cognito authorizer** (JWT, not our cookie). **Async jobs**: `POST /api/analyses` writes QUEUED to DynamoDB and async-invokes a **worker Lambda**; the UI polls. Rename the role to `aspph-admin`. | 4–5 h |
| P2 | **CDK for everything** | Fill `infra/`: Auth (existing pool imported or created), Data (table + buckets), Api (API GW, Lambdas, least-privilege roles), Observability (log groups, alarms on 5xx, worker errors, Bedrock throttles), Hosting (Amplify). Dev/prod via context. | 3–4 h |
| P3 | **Secure upload** | `POST /api/uploads` → presigned PUT to a **quarantine** prefix; validation Lambda: extension + MIME + **magic bytes**, size/page limits, encrypted/corrupt rejection, checksum, then move to `validated/`; idempotency key per file hash. | 2–3 h |
| P4 | **Strands + AgentCore** | Package the curriculum and competency pipelines as **Strands agents on AgentCore** whose tools are our existing stations (retrieve, gates, supervise). The worker Lambda calls AgentCore. Keeps every code gate. | 3–4 h |
| P5 | **Frontend** | Either (a) host the current UI on Amplify behind Amplify Auth (fast, demo-ready), or (b) port it into the React app as the listed components. **(b) is 1–2 days**; recommend (a) now, with (b) started by teammates in parallel. | (a) 1–2 h |
| P6 | **Usage + cost controls** | Per university/faculty usage items (pages, analyses, Bedrock tokens, invocations) written by the worker; monthly quotas checked before a job starts; a cost document (no hardcoded prices: cite the AWS pricing pages and our measured tokens). | 2 h |
| P7 | **Tests + demo** | Security tests (expired/invalid JWT via API GW, cross-tenant access, renamed/oversized/corrupt files, fabricated citation, prompt injection, duplicate job, concurrent approval with conditional writes, quota), E2E demo script with the Epidemiology + a new **Biostatistics** synthetic syllabus, architecture diagram, API docs, security checklist, deployment guide. | 3 h |
| later | WAF on the API, GitHub Actions OIDC deploys, MFA enforcement for admins, SAML/OIDC federation, Step Functions, GuardDuty malware scanning (needs permission) | | |

**Proposed file changes, by phase:** P1 `backend/app/{main,auth,db,worker}.py`, `backend/app/routes/*` (filled from `playground/server.py`), `agent/` unchanged · P2 `infra/lib/*.ts`, `infra/bin/phact.ts`, `cdk.json` contexts · P3 `backend/app/services/uploads.py` + validation Lambda · P4 `agent/agentcore/{curriculum,competency}_agent.py` · P5 `frontend/` or Amplify config for the playground · P6 `backend/app/services/usage.py` · P7 `backend/tests/*`, `docs/{api,security-checklist,cost-estimate,demo-script,deployment}.md`.
