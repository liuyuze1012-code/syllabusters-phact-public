# Agent: the AI harness (Strands on Bedrock AgentCore)

**Owner: Gavin (AI track).** Right now this is a **preliminary placeholder**. `main.py` answers in mock mode with the shared sample result, so the backend and frontend can be built and tested without waiting for the real harness. The full design is in [HARNESS.md](HARNESS.md).

## Run the placeholder

```bash
cd agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PHACT_MOCK=1 python main.py                         # serves POST http://localhost:8080/invocations
curl -X POST localhost:8080/invocations -H 'Content-Type: application/json' \
     -d @../shared/fixtures/analyze_request.json
pytest tests/
```

The backend can also skip this server entirely with `AGENT_MODE=mock`, which reads the same fixtures in-process.

## Files

| File | What it does | Status |
|---|---|---|
| `HARNESS.md` | The full harness design: stations, models, prompts, gates, evals | ready |
| `requirements.txt` | AgentCore SDK, Strands, boto3, pydantic, `../shared` | ready |
| `main.py` | AgentCore entrypoint; routes `analyze` / `revise`; `PHACT_MOCK=1` uses the mock | ready (mock) |
| `mock.py` | Validates the request, returns the fixture with the caller's `job_id` | ready |
| `pipeline/analyze.py` | The real assembly line, stations 1–6 | placeholder |
| `pipeline/revise.py` | Chat edit | placeholder |
| `steps/check_text.py` | Station 0: enough readable text? (code) | placeholder |
| `steps/structure.py` | Station 1: read into sections and assignments (fast model) | placeholder |
| `steps/map_ceph.py` | Station 2a: rate the 22 competencies (strong model) | placeholder |
| `steps/rate_ai.py` | Station 2b: AI-use score 0–4 (strong model) | placeholder |
| `steps/assess.py` | Station 2c: count assessment types (fast model) | placeholder |
| `steps/retrieve.py` | Station 3: knowledge base search (code) | placeholder |
| `steps/propose.py` | Station 4: write the edits (strong model) | placeholder |
| `steps/supervise.py` | Station 5: check each edit (fast model) | placeholder |
| `gates.py` | Code checks between stations | placeholder |
| `retrieval.py` | Bedrock KB `Retrieve` with filters, P-numbering | placeholder |
| `prompts/*.md` | One prompt per station + revise | placeholder |
| `data/` | `ceph_competencies.json` copied here at build time | empty |
| `eval/run_eval.py` | Scores the pipeline against the golden answers | placeholder |
| `eval/golden/` | Expected results per test syllabus | empty |
| `eval/adversarial/` | Injection, off-topic and PII test cases | empty |
| `tests/test_mock.py` | The placeholder returns contract-valid output | ready |

## Switching from mock to real
1. Build `pipeline/analyze.py` station by station, following HARNESS.md section 10.
2. Run with `PHACT_MOCK=0`, and check `eval/run_eval.py` passes its bars.
3. The backend switches `AGENT_MODE` from `mock` → `local` → `agentcore`. **No backend code changes**, because both sides use the same contract.
