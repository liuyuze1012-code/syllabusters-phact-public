"""How the API server reaches the PHACT agent (agent/service.py).

    PHACT_AGENT=local      (default) run it in this process: local development and tests
    PHACT_AGENT=agentcore  invoke it on Amazon Bedrock AgentCore (AGENT_RUNTIME_ARN), as on AWS

Same JSON in, same JSON out on both paths. Each professor gets their own AgentCore session (an isolated
microVM, reused while warm); a session is derived from the user's id, never from their name or email.
"""

import hashlib
import json
import os
import uuid

MODE = os.getenv("PHACT_AGENT", "local")
ARN = os.getenv("AGENT_RUNTIME_ARN", "")
_client = None


class AgentError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _session() -> str:
    try:
        import accounts
        sub = (accounts.JOB_USER.get(None) or {}).get("sub")
    except Exception:  # noqa: BLE001
        sub = None
    # the deployed agent version is part of the id: after a deploy, every professor gets a fresh session
    # running the new code (a warm session would otherwise keep the old code until it idles out)
    base = hashlib.sha256(f"phact:{os.getenv('AGENT_VERSION', '')}:{sub}".encode()).hexdigest() if sub else uuid.uuid4().hex * 2
    return f"phact-{base[:40]}"  # AgentCore wants ≥ 33 characters


def _invoke(op: str, x: dict, session: str) -> dict:
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config
        _client = boto3.client("bedrock-agentcore", region_name=os.getenv("AWS_REGION", "us-west-2"),
                               config=Config(read_timeout=900, connect_timeout=10, retries={"max_attempts": 2}))
    r = _client.invoke_agent_runtime(agentRuntimeArn=ARN, runtimeSessionId=session, qualifier="DEFAULT",
                                     contentType="application/json", accept="application/json",
                                     payload=json.dumps({"op": op, "input": x}).encode())
    return json.loads(r["response"].read())


def call(op: str, x: dict) -> dict:
    if MODE == "agentcore":
        session = _session()
        try:
            r = _invoke(op, x, session)
        except Exception as e:  # noqa: BLE001 — a busy or broken session: one retry in a fresh one
            if "Throttl" in type(e).__name__ or "Conflict" in str(e) or "busy" in str(e).lower():
                r = _invoke(op, x, f"phact-{uuid.uuid4().hex}{uuid.uuid4().hex[:8]}")
            else:
                raise
    else:
        import service
        r = service.handle(op, x)
    if isinstance(r, dict) and isinstance(r.get("error"), dict):
        raise AgentError(r["error"].get("type", "error"), r["error"].get("message", "The agent failed."))
    return r
