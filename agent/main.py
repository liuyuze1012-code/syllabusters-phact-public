"""AgentCore entrypoint for the PHACT agent.

PRELIMINARY PLACEHOLDER: with PHACT_MOCK=1 (the default for now) it returns the shared
fixtures, validated against the contract. The real pipeline (pipeline/analyze.py) replaces
this once the harness is built. See HARNESS.md.

Local:  python main.py   →  POST http://localhost:8080/invocations
"""

import os

from mock import mock_analyze, mock_revise

try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
except ImportError:  # lets the mock run without the AgentCore SDK installed
    BedrockAgentCoreApp = None

USE_MOCK = os.getenv("PHACT_MOCK", "1") == "1"


def handle(payload: dict) -> dict:
    mode = payload.get("mode")
    if USE_MOCK:
        if mode == "analyze":
            return mock_analyze(payload)
        if mode == "revise":
            return mock_revise(payload)
    else:
        from pipeline import analyze, revise  # real harness, not built yet
        if mode == "analyze":
            return analyze.run(payload)
        if mode == "revise":
            return revise.run(payload)
    return {"ok": False, "job_id": payload.get("job_id", ""), "error": "unknown_mode",
            "message": "Something went wrong on our side. Please try again."}


if BedrockAgentCoreApp is not None:
    app = BedrockAgentCoreApp()
    app.entrypoint(handle)

if __name__ == "__main__":
    if BedrockAgentCoreApp is None:
        raise SystemExit("pip install bedrock-agentcore to serve on :8080 (tests can call handle() directly)")
    app.run()
