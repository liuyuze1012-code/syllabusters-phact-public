"""Calls the AI agent. AGENT_MODE picks how, so the backend works before the AI does.

    AGENT_MODE=mock       return shared/fixtures/*.json instantly (default; no AI, no AWS)
    AGENT_MODE=local      POST to the agent running on a laptop (python agent/main.py → :8080)
    AGENT_MODE=agentcore  call the deployed AgentCore runtime (AGENT_RUNTIME_ARN)

Every response is validated against phact_contracts before it reaches the rest of the backend.
"""

import json
import os
import time
import urllib.request
import uuid

from phact_contracts import FIXTURES
from phact_contracts.agent import (
    AnalyzeRequest,
    AnalyzeResponse,
    ErrorResponse,
    ReviseRequest,
    ReviseResponse,
)

AnalyzeResult = AnalyzeResponse | ErrorResponse
ReviseResult = ReviseResponse | ErrorResponse


def _parse(raw: dict, ok_model):
    """Turn a raw agent dict into a validated contract object."""
    if raw.get("ok") is False:
        return ErrorResponse.model_validate(raw)
    return ok_model.model_validate(raw)


def parse_agentcore_body(body: bytes) -> dict:
    """AgentCore responses can arrive double-wrapped: JSON whose value is a string,
    sometimes inside a ```json code fence, that holds the real JSON."""
    data = json.loads(body)
    if isinstance(data, dict) and isinstance(data.get("result"), (str, dict)):
        data = data["result"]
    if isinstance(data, str):
        text = data.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(text)
    return data


class MockAgentClient:
    """Returns the fixtures. PHACT_MOCK_DELAY=<seconds> simulates a slow run;
    PHACT_MOCK_ERROR=1 returns the error fixture so the error UI can be tested."""

    def _load(self, name: str) -> dict:
        return json.loads((FIXTURES / name).read_text())

    def _maybe_fail(self, job_id: str) -> ErrorResponse | None:
        time.sleep(float(os.getenv("PHACT_MOCK_DELAY", "0")))
        if os.getenv("PHACT_MOCK_ERROR") == "1":
            raw = self._load("error_response.json")
            raw["job_id"] = job_id
            return ErrorResponse.model_validate(raw)
        return None

    def analyze(self, req: AnalyzeRequest) -> AnalyzeResult:
        if err := self._maybe_fail(req.job_id):
            return err
        raw = self._load("analyze_response.json")
        raw["job_id"] = req.job_id
        return _parse(raw, AnalyzeResponse)

    def revise(self, req: ReviseRequest) -> ReviseResult:
        if err := self._maybe_fail(req.job_id):
            return err
        text = req.message.strip().lower()  # same fixture choice as agent/mock.py
        name = ("revise_question_response.json" if text.endswith("?")
                else "revise_add_response.json" if text.startswith("add")
                else "revise_response.json")
        raw = self._load(name)
        raw["job_id"] = req.job_id
        return _parse(raw, ReviseResponse)


class LocalAgentClient:
    """For when Gavin runs the agent on a laptop: `cd agent && python main.py`."""

    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("AGENT_LOCAL_URL", "http://localhost:8080/invocations")

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read())

    def analyze(self, req: AnalyzeRequest) -> AnalyzeResult:
        return _parse(self._post(req.model_dump()), AnalyzeResponse)

    def revise(self, req: ReviseRequest) -> ReviseResult:
        return _parse(self._post(req.model_dump()), ReviseResponse)


class AgentCoreClient:
    """The deployed agent. read_timeout is long because a run takes ~60 s; retries are OFF
    so a slow run is never started twice."""

    def __init__(self):
        import boto3
        from botocore.config import Config

        self.arn = os.environ["AGENT_RUNTIME_ARN"]
        self.client = boto3.client(
            "bedrock-agentcore", config=Config(read_timeout=540, retries={"max_attempts": 0})
        )

    def _invoke(self, payload: dict) -> dict:
        resp = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.arn,
            runtimeSessionId=f"phact-{payload['job_id']}-{uuid.uuid4().hex}",  # must be 33+ chars
            payload=json.dumps(payload).encode(),
        )
        return parse_agentcore_body(resp["response"].read())

    def analyze(self, req: AnalyzeRequest) -> AnalyzeResult:
        return _parse(self._invoke(req.model_dump()), AnalyzeResponse)

    def revise(self, req: ReviseRequest) -> ReviseResult:
        return _parse(self._invoke(req.model_dump()), ReviseResponse)


def get_agent_client():
    mode = os.getenv("AGENT_MODE", "mock")
    if mode == "mock":
        return MockAgentClient()
    if mode == "local":
        return LocalAgentClient()
    if mode == "agentcore":
        return AgentCoreClient()
    raise ValueError(f"Unknown AGENT_MODE={mode!r}; use mock, local or agentcore")
