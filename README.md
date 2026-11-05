# PHACT, by Team 31 (Syllabusters)

**PHACT (Public Health AI Curriculum Transformation)** helps a public health professor bring AI into a course
responsibly. They upload a syllabus or an assessment, and PHACT:

- maps it to the 22 CEPH foundational competencies,
- proposes specific edits, each one citing an ASPPH source the professor can open,
- double-checks every edit with an independent supervisor agent, and
- lets the professor accept or reject each edit before exporting a revised Word document with numbered references.

A university admin sets an AI policy that sits above every professor's own settings. ASPPH staff manage the
knowledge base and watch the agent across all member universities.

Built for **ASPPH** at **AWS Breaking Barriers 2026**, Washington DC.

**Live demo:** https://0rrbnzygi0.execute-api.us-west-2.amazonaws.com. Demo accounts are shared with the
organizers directly, never in this repo.

| Portal | Path | Who |
|---|---|---|
| Professor app | `/` | faculty |
| University admin portal | `/university` | a university's admin (joins by invite code) |
| ASPPH admin console | `/admin` | ASPPH staff: knowledge base, all universities, **Agent monitor**, audit log |

## How it works

```
Browser ──HTTPS──▶ API Gateway (Cognito JWT check) ──▶ Lambda "phact-api" (FastAPI)
                                                         │  long AI work becomes a job
                                                         ▼
                                            Lambda "phact-worker" ──▶ Bedrock AgentCore Runtime
                                                                       Strands Graph, 5 nodes:
                                                                       map_ceph (Claude Opus)
                                                                        → retrieve (Bedrock Knowledge Base, S3 Vectors)
                                                                        → propose (Claude Opus)
                                                                        → supervise (Claude Haiku, one check per edit)
                                                                        → source_finder (Strands agent with a search tool)
```

- **Privacy first:** Amazon Comprehend replaces names, emails and phone numbers with tags before Claude sees
  any text; they're put back only in the professor's own export. Chat also passes a Bedrock Guardrail.
  Passwords live only in Cognito.
- **Isolation:** each professor's courses are keyed to their account, and a university sees only its own members.
  The university ID is a Cognito attribute users can't change themselves.
- **Data:** one DynamoDB table (users, courses, jobs, universities, invites, sources, usage, audit) and
  encrypted S3 buckets.
- **Observability:** AgentCore traces and GenAI spans in CloudWatch (Transaction Search). ASPPH's
  **Agent monitor** shows runs, failures, time per pipeline stage, tokens and estimated cost per model,
  suggestion quality, and per-university usage. It stores counts and times only, never syllabus text.

## Where the code is

| Folder | What it is |
|---|---|
| `playground/` | **The deployed web app:** FastAPI server (`server.py`), the three portals (`index.html`, `university.html`, `admin.html`), jobs, accounts, universities, usage monitoring |
| `agent/` | **The AI harness:** Strands Graph pipeline (`pipeline/stages.py`), each step (`steps/`), code gates, retrieval, PII safety, the AgentCore entrypoint (`agentcore_app.py`). Design notes in `agent/HARNESS.md` |
| `shared/` | The contract between the app and the agent (Pydantic schemas) and sample fixtures |
| `knowledge-base/` | How the knowledge base is built: source list, CEPH checklist, default AI policies, retrieval tests |
| `scripts/` | Setup and deployment (Cognito, DynamoDB, Knowledge Base, Guardrail, AgentCore, Lambda), plus benchmarks and the quality A/B test |
| `backend/`, `frontend/`, `infra/` | The first-day scaffold (FastAPI, React and AWS CDK) the team split work on. The live demo runs from `playground/` and `agent/`, deployed with the Python scripts in `scripts/` |
| `data/` | Synthetic test syllabi and assessments (made up by us) |
| `docs/` | Contracts, team planning notes, brand |

## Run it locally

Needs Python 3.12 and AWS credentials for an account with Bedrock (Claude), the Knowledge Base and Comprehend.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
(cd agent && pip install -r requirements.txt) && pip install fastapi uvicorn python-multipart python-docx
PHACT_AUTH=0 PHACT_PORT=8789 python playground/server.py     # http://localhost:8789 (accounts off, local user)
python -m pytest playground/tests agent/tests                 # unit tests (some use real AWS)
```

Deploying to your own account: `scripts/create_userdb.py`, `create_kb.py`, `create_guardrail.py`,
`deploy_agentcore.py`, then `deploy_lambda.py`. Each prints what it created and is safe to rerun.

## Not in this repo, and why

- **ASPPH and CEPH source documents** (the PDFs and the section text we index). They're ASPPH's published
  material, and the originals are public in the challenge repo:
  [12turnbullb/us-breaking-barriers-2026](https://github.com/12turnbullb/us-breaking-barriers-2026/tree/main/ASPPH).
- **A real university syllabus** we tested on privately, because it includes an instructor's contact details.
- **Challenge materials** we were given (the brief, user stories, earlier ARIE architecture documents).
- **Demo account passwords, AWS keys, user uploads.** These were never committed.

This public copy starts from a single commit. Our working repo stays private with its full history.

## Team

**Team 31, Syllabusters** · AWS Breaking Barriers 2026, Washington DC · ASPPH challenge

🏆 **Finalist**, AWS Breaking Barriers 2026

| | Role | Background |
|---|---|---|
| **Gavin Liu** | Product & build lead | Sophomore in Science, Technology & International Affairs at Georgetown University's School of Foreign Service |
| **Shadman Jarif** | Architecture & testing | Senior in Computer Science at George Mason University |
| **Alice Bui** | UI/UX design & storytelling | Graduate student in Learning Design and Technology at Georgetown University |
| **Michael Asrat** | Solution architecture | Technology professional in government IT and cybersecurity; M.Eng., University of Illinois Chicago |
| **Puneeth Ammapalli** | Cloud & AI engineering | Principal Cloud Engineer at CVS Health, 18+ years in cloud infrastructure and security |

### Gavin Liu

A Georgetown sophomore passionate about AI, space tech and robotics. Gavin has scouted startups and founded
Prototype, a podcast platform about technology and founders.

### Shadman Jarif

Helped design PHACT's overall architecture and AWS infrastructure, focusing on how the services fit together, and
tested and validated the application to find issues before the demo.

### Alice Bui

Brings expertise in learning experience, curriculum design and program management. Alice designed PHACT's user
interface and experience, and led research and storytelling for the presentation.

### Michael Asrat

Solution architect for PHACT. Michael identified technical challenges, evaluated requirements and guided the
solution architecture, turning complex needs into practical, scalable designs on AWS.

### Puneeth Ammapalli

Specializes in AWS, Google Cloud, Azure, Terraform and generative AI, including Amazon Bedrock. Puneeth holds
multiple AWS, GCP and Terraform certifications, and received the President's Award at Discover Financial Services.
