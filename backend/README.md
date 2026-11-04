# Backend: FastAPI on Lambda

**Owner: software engineering track.** The API the web app calls, the job worker that runs the AI in the background, plus extraction, safety and export. Python 3.12.

## Run it locally with no AWS and no AI

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
DEV_AUTH=1 AGENT_MODE=mock uvicorn app.main:app --reload     # http://localhost:8000/health
pytest                                                      # includes the mock-agent tests
```

`AGENT_MODE` switches the AI without touching any other code:

| Value | What it does | When |
|---|---|---|
| `mock` (default) | Returns `shared/fixtures/*.json` instantly | Building and testing everything before the AI is ready |
| `local` | Calls the agent running on a laptop at `:8080` | Gavin testing the real pipeline end to end |
| `agentcore` | Calls the deployed AgentCore runtime (`AGENT_RUNTIME_ARN`) | Demo and production |

Extra mock switches: `PHACT_MOCK_DELAY=20` simulates a slow run (test the progress bar). `PHACT_MOCK_ERROR=1` returns a failure (test the error screen).

## Files

| File | What it does | Status |
|---|---|---|
| `requirements.txt` | Runtime dependencies, including `../shared` (the agent contract) | ready |
| `requirements-dev.txt` | Test and local-run dependencies | ready |
| `app/main.py` | Creates the FastAPI app, includes every router; `handler` is the Lambda entrypoint (Mangum) | ready |
| `app/config.py` | Every setting, read from environment variables | ready |
| `app/auth.py` | Reads the Cognito claims (user, school, groups); `require_group` for role checks; `DEV_AUTH=1` fake user | claims parsing TODO |
| `app/db.py` | DynamoDB key layout and data helpers | key helpers ready, rest TODO |
| `app/storage.py` | Presigned S3 links (signature v4 for KMS buckets) | TODO |
| `app/schemas.py` | Web API request/response shapes | ready |
| `app/routes/health.py` | `GET /health` | ready |
| `app/routes/me.py` | Profile and preferences | TODO |
| `app/routes/courses.py` | Courses, upload link, register syllabus, save the checks | TODO |
| `app/routes/jobs.py` | Start a job (202) and poll it | TODO |
| `app/routes/edits.py` | Read an analysis; accept or reject an edit | TODO |
| `app/routes/exports.py` | Build the DOCX and return a download link | TODO |
| `app/routes/school.py` | School admin: profile and AI policy | TODO |
| `app/routes/review.py` | ASPPH reviewer: queue, detail, approve & publish / send back / reject, retire, submit | TODO |
| `app/services/extract.py` | PDF/DOCX → text | TODO |
| `app/services/safety.py` | Comprehend PII scrub + Bedrock Guardrail | TODO |
| `app/services/context_builder.py` | Builds the `context` block for the agent from DynamoDB | TODO |
| `app/services/agent_client.py` | **Calls the agent: mock, local or AgentCore.** Validates every response | ready |
| `app/services/export_docx.py` | DOCX from accepted edits + "Changes and sources" appendix | TODO |
| `app/worker.py` | Job worker Lambda: safety → agent → save → COMPLETE/FAILED | works with mock; DB TODO |
| `tests/conftest.py` | Sets `DEV_AUTH=1`, `AGENT_MODE=mock` | ready |
| `tests/test_health.py` | The API starts | ready |
| `tests/test_agent_mock.py` | Mock results are contract-valid; the worker runs; double-wrapped parsing works | ready |

## Rules
- `user_id` and `school_id` come **only** from the token, never from the request body.
- Every role-restricted route calls `require_group` first.
- Log job IDs and timings, never syllabus text or chat messages.
- The agent contract is `shared/phact_contracts/agent.py`. Don't copy it here; import it.
