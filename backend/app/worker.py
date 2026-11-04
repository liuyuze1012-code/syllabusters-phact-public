"""The job worker Lambda. Invoked asynchronously by POST /api/jobs; may run up to 10 min.

    QUEUED → RUNNING → (safety gate) → agent → save results → COMPLETE | FAILED

With AGENT_MODE=mock (the default) the agent call returns the fixtures, so the whole
backend can be built and tested before the AI harness exists.
"""

from phact_contracts.agent import AnalyzeRequest, ErrorResponse

from app.services.agent_client import get_agent_client


def handler(event, context):
    job_id = event["job_id"]
    # TODO 1: update JOB#<id> → RUNNING
    # TODO 2: load the syllabus text (already scrubbed at upload), course settings,
    #         confirmed competencies, targets; build the context (services/context_builder.py)
    req = AnalyzeRequest.model_validate(event["request"])  # TODO: build from DynamoDB instead
    result = get_agent_client().analyze(req)
    if isinstance(result, ErrorResponse):
        # TODO: JOB → FAILED with result.message
        return {"ok": False, "job_id": job_id, "message": result.message}
    # TODO 3: save ANALYSIS + EDIT# items + passages; JOB → COMPLETE with result_id
    return {"ok": True, "job_id": job_id, "edits": len(result.edits)}
