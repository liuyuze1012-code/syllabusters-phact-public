"""AWS Lambda entry points (ASPPH Technical Document: FastAPI + Mangum behind API Gateway; worker Lambda for jobs).

  api_handler     API Gateway → Mangum → the FastAPI app in server.py (the same app that runs locally)
  worker_handler  invoked asynchronously with {"job_id": …}; runs the job through the same app (jobs.run)

Environment (set by the deployment): PHACT_AUTH=1, PHACT_AUTH_MODE=jwt, PHACT_JOBS=lambda, WORKER_FUNCTION,
AWS_REGION. The ID token is verified by API Gateway's Cognito JWT authorizer before api_handler runs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mangum import Mangum  # noqa: E402

import jobs  # noqa: E402
import server  # noqa: E402

_asgi = Mangum(server.app, lifespan="off")


def api_handler(event, context):
    return _asgi(event, context)


def worker_handler(event, context):
    jid = (event or {}).get("job_id")
    if not jid:
        return {"ok": False, "error": "no job_id"}
    jobs.run(jid)
    return {"ok": True, "job_id": jid}
