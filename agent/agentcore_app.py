"""Amazon Bedrock AgentCore entrypoint: the PHACT agent (service.py) hosted on an AgentCore Runtime.

AgentCore calls POST /invocations with the JSON payload {"op": ..., "input": {...}}; we return service.handle's
JSON. Each professor gets their own AgentCore session (an isolated microVM), chosen by the caller.
The deploy script copies this file to the package root; the agent code sits in ./agent, as in the repo.

Local test:  python agent/agentcore_app.py   then   POST http://localhost:8080/invocations
"""

import os
import sys
from pathlib import Path

# AgentCore Observability: start AWS's OpenTelemetry distro (ADOT) before anything else is imported, the same as
# launching with `opentelemetry-instrument`. AgentCore supplies the exporter settings; spans and token usage then
# show in the AgentCore Observability dashboard. Never blocks the agent if telemetry can't start.
if os.getenv("AWS_EXECUTION_ENV") or os.getenv("AGENT_OBSERVABILITY_ENABLED") or os.getenv("PHACT_OTEL") == "1":
    try:
        from opentelemetry.instrumentation.auto_instrumentation import initialize
        initialize()
    except Exception as e:  # noqa: BLE001
        print(f"observability not started: {e}")

HERE = Path(__file__).resolve().parent
AGENT = HERE / "agent" if (HERE / "agent" / "service.py").exists() else HERE  # package root, or the repo's agent/
sys.path[:0] = [str(AGENT), str(AGENT.parent / "shared"), str(HERE)]  # phact_contracts: repo shared/ or package root

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

import service  # noqa: E402

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    return service.handle(payload.get("op", ""), payload.get("input") or {})


if __name__ == "__main__":
    app.run()
