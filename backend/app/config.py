"""All settings, read once from environment variables (CDK sets them on the Lambdas)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    table_name: str = os.getenv("TABLE_NAME", "phact-local")
    uploads_bucket: str = os.getenv("UPLOADS_BUCKET", "phact-uploads-local")
    exports_bucket: str = os.getenv("EXPORTS_BUCKET", "phact-exports-local")
    knowledge_bucket: str = os.getenv("KNOWLEDGE_BUCKET", "phact-knowledge-local")
    intake_bucket: str = os.getenv("INTAKE_BUCKET", "phact-intake-local")
    worker_function: str = os.getenv("WORKER_FUNCTION", "")
    guardrail_id: str = os.getenv("GUARDRAIL_ID", "")
    guardrail_version: str = os.getenv("GUARDRAIL_VERSION", "DRAFT")
    agent_mode: str = os.getenv("AGENT_MODE", "mock")          # mock | local | agentcore
    dev_auth: bool = os.getenv("DEV_AUTH", "0") == "1"         # fake user for local runs only


settings = Settings()
