"""Mock agent: returns shared/fixtures, with the caller's job_id, after checking the
request and the response against the contract. Lets the backend and frontend run end to end
before the real harness exists."""

import json

from phact_contracts import FIXTURES
from phact_contracts.agent import AnalyzeRequest, AnalyzeResponse, ReviseRequest, ReviseResponse


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def mock_analyze(payload: dict) -> dict:
    req = AnalyzeRequest.model_validate(payload)          # rejects a malformed request early
    out = _fixture("analyze_response.json")
    out["job_id"] = req.job_id
    return AnalyzeResponse.model_validate(out).model_dump()


def _revise_fixture(message: str) -> str:
    """Pick a sample reply so every chat state can be tried: a question, an 'add', or a change."""
    text = message.strip().lower()
    if text.endswith("?"):
        return "revise_question_response.json"
    if text.startswith("add"):
        return "revise_add_response.json"
    return "revise_response.json"


def mock_revise(payload: dict) -> dict:
    req = ReviseRequest.model_validate(payload)
    out = _fixture(_revise_fixture(req.message))
    out["job_id"] = req.job_id
    return ReviseResponse.model_validate(out).model_dump()
