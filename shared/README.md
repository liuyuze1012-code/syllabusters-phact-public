# Shared: the contract between the backend and the AI

**Owner: everyone. Change only with the whole team's agreement.** One copy of the agent's input/output schema, installed into both `backend/` and `agent/` with `pip install -e ../shared`. If both sides validate against the same classes, they can be built separately and still fit together.

## Files

| File | What it does |
|---|---|
| `pyproject.toml` | Makes `phact_contracts` installable |
| `phact_contracts/__init__.py` | Exposes `FIXTURES`, the path to the sample JSON files |
| `phact_contracts/agent.py` | **The contract:** `AnalyzeRequest`, `AnalyzeResponse`, `ReviseRequest` (with `scope`), `ReviseResponse` (with `kind`, `new_passages`, `removed_edit_ids`), `ErrorResponse`, and their parts (`Outline`, `CompetencyResult`, `Edit`, `Passage`…). `AnalyzeResponse` rejects anything that doesn't have all 22 competencies. |
| `fixtures/analyze_request.json` | A sample request (PHC 6149, PHACT default policy) |
| `fixtures/analyze_response.json` | A sample result: 22 competencies, AI rating, 3 edits, 3 passages. **Illustrative mock data, not a real analysis**; snippets marked `[MOCK SNIPPET]` are placeholders. |
| `fixtures/revise_response.json` | Chat reply, kind `change`: edit E2 rewritten as version 2 |
| `fixtures/revise_add_response.json` | Chat reply, kind `add`: new edit E4 from a new passage P4 |
| `fixtures/revise_question_response.json` | Chat reply, kind `question`: an answer, nothing changed |
| `fixtures/error_response.json` | A sample failure (`unreadable_syllabus`) |

The mock agent (`agent/mock.py`), the backend's `AGENT_MODE=mock`, and the frontend's `VITE_USE_MOCKS=1` all serve these fixtures.
