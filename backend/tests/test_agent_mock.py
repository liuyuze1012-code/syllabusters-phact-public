"""The mock agent returns contract-valid results, so the backend can be built without the AI."""

import json

from phact_contracts import FIXTURES
from phact_contracts.agent import AnalyzeRequest, AnalyzeResponse, ErrorResponse

from app.services.agent_client import MockAgentClient, parse_agentcore_body
from app.worker import handler


def _req() -> AnalyzeRequest:
    return AnalyzeRequest.model_validate(json.loads((FIXTURES / "analyze_request.json").read_text()))


def test_mock_analyze_is_valid():
    res = MockAgentClient().analyze(_req())
    assert isinstance(res, AnalyzeResponse)
    assert len(res.competencies) == 22
    assert res.meta.mock is True


def test_mock_error(monkeypatch):
    monkeypatch.setenv("PHACT_MOCK_ERROR", "1")
    assert isinstance(MockAgentClient().analyze(_req()), ErrorResponse)


def test_worker_runs_with_mock():
    out = handler({"job_id": "t1", "request": _req().model_dump()}, None)
    assert out["ok"] is True and out["edits"] >= 1


def test_double_wrapped_body():
    inner = {"ok": True, "x": 1}
    wrapped = json.dumps({"result": "```json\n" + json.dumps(inner) + "\n```"}).encode()
    assert parse_agentcore_body(wrapped) == inner
