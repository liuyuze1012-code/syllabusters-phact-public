"""The phone line to Claude. Every station calls Claude through `call()` and nothing else.

One call = one request to Claude on Amazon Bedrock that must come back as a validated Pydantic
object (structured output). This file owns everything that is the same for every station:
which model, effort, timeouts, retries, prompt caching, reading the stop reason, and logging.

Settings (HARNESS.md section 3b):
    MODEL_STRONG  default us.anthropic.claude-opus-5-5   (judgment and writing)
    MODEL_FAST    default us.anthropic.claude-haiku-5-5  (reading, counting, checking)
    AWS_REGION    default us-west-2
Credentials come from the normal AWS chain (~/.aws/credentials locally, the runtime role on AgentCore).
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Literal, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

Tier = Literal["strong", "fast"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
T = TypeVar("T", bound=BaseModel)

REGION = os.getenv("AWS_REGION", "us-west-2")
MODELS: dict[str, str] = {
    "strong": os.getenv("MODEL_STRONG", "us.anthropic.claude-opus-5-5"),
    "fast": os.getenv("MODEL_FAST", "us.anthropic.claude-haiku-5-5"),
}
TIMEOUT_S: dict[str, float] = {"strong": 60.0, "fast": 30.0}

log = logging.getLogger("phact.llm")
_client: anthropic.AnthropicBedrock | None = None


class LLMError(Exception):
    """A station's call failed for good. `code` is machine-readable; the pipeline decides what the professor sees."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class CallStats:
    station: str
    model: str
    effort: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms: int = 0
    stop_reason: str = ""
    request_id: str = ""
    attempts: int = 0
    notes: list[str] = field(default_factory=list)


def client() -> anthropic.AnthropicBedrock:
    # InvokeModel path with cross-region profiles (us.anthropic.*). The newer Mantle endpoint
    # returned "model not found" in our sandbox on Nov 3; swap the client here if that changes.
    global _client
    if _client is None:
        _client = anthropic.AnthropicBedrock(aws_region=REGION, max_retries=2)  # SDK retries 429/5xx/connection
    return _client


MAX_TOKENS_CAP = 16000  # above this, non-streaming requests risk SDK/HTTP timeouts


def call(*, station: str, tier: Tier, system: str, user: str, schema: type[T], effort: Effort,
         max_tokens: int, think: bool = True, timeout_s: float | None = None) -> tuple[T, CallStats]:
    """Send one request and return (validated object, stats).

    `system` is the station's frozen instructions (cached); `user` is this request's data.
    Never put per-request data (IDs, timestamps, syllabus text) in `system`, or caching breaks.

    `max_tokens` must cover thinking AND the answer: current models always think first, and
    thinking counts against the limit (a too-small limit returns stop_reason "max_tokens" with
    no answer at all).

    `think=False` turns thinking off for mechanical stations (indexing, counting). Only the fast
    model (Haiku 5.5) accepts this, at effort high or below; Opus 5.5 always thinks.
    """
    if not think and tier != "fast":
        raise ValueError("think=False is only supported on the fast model (Haiku 5.5)")
    with _span(station, MODELS[tier]) as span:
        parsed, stats = _call(station=station, tier=tier, system=system, user=user, schema=schema, effort=effort,
                              max_tokens=max_tokens, think=think, timeout_s=timeout_s)
        if span is not None:
            span.set_attribute("gen_ai.usage.input_tokens", stats.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", stats.output_tokens)
            span.set_attribute("gen_ai.response.finish_reasons", [stats.stop_reason])
            span.set_attribute("phact.latency_ms", stats.latency_ms)
        return parsed, stats


def _span(station: str, model: str):
    """OpenTelemetry GenAI span (semantic conventions) for one Claude call. A no-op when telemetry isn't running
    (local dev) or the package is missing. Never contains prompt or syllabus text: only names and counts."""
    from contextlib import nullcontext
    try:
        from opentelemetry import trace
    except ImportError:
        return nullcontext()
    return trace.get_tracer("phact.llm").start_as_current_span(
        f"chat {model}", attributes={"gen_ai.operation.name": "chat", "gen_ai.system": "aws.bedrock",
                                     "gen_ai.request.model": model, "phact.station": station})


def _call(*, station: str, tier: Tier, system: str, user: str, schema: type[T], effort: Effort,
          max_tokens: int, think: bool = True, timeout_s: float | None = None) -> tuple[T, CallStats]:
    model = MODELS[tier]
    stats = CallStats(station=station, model=model, effort=effort)
    request = dict(
        model=model,
        max_tokens=min(max_tokens, MAX_TOKENS_CAP),
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        # Structured output: the API constrains the reply to this JSON schema. We validate it
        # ourselves (instead of messages.parse) so the stop reason is always visible first.
        output_config={"effort": effort, "format": {"type": "json_schema",
                                                    "schema": anthropic.transform_schema(schema)}},
    )
    if not think:
        request["thinking"] = {"type": "disabled"}
    for attempt in (1, 2):
        stats.attempts = attempt
        started = time.monotonic()
        try:
            response = client().with_options(timeout=timeout_s or TIMEOUT_S[tier]).messages.create(**request)
        except anthropic.APITimeoutError as e:
            raise LLMError("timeout", f"{station} took over {timeout_s or TIMEOUT_S[tier]:.0f}s") from e
        except anthropic.RateLimitError as e:
            raise LLMError("rate_limited", "Bedrock throttled after retries") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"api_{e.status_code}", str(e)[:300]) from e
        except anthropic.APIConnectionError as e:
            raise LLMError("connection", str(e)[:300]) from e

        stats.latency_ms += int((time.monotonic() - started) * 1000)
        usage = response.usage
        stats.input_tokens += usage.input_tokens
        stats.output_tokens += usage.output_tokens
        stats.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        stats.stop_reason = response.stop_reason or ""
        stats.request_id = getattr(response, "_request_id", "") or ""

        if response.stop_reason == "refusal":
            raise LLMError("refusal", str(getattr(response, "stop_details", "")))
        if response.stop_reason == "max_tokens":
            stats.notes.append(f"attempt {attempt}: ran out of room at max_tokens={request['max_tokens']}")
            if attempt == 2 or request["max_tokens"] >= MAX_TOKENS_CAP:
                raise LLMError("max_tokens", f"{station} needed more than {request['max_tokens']} tokens")
            request["max_tokens"] = min(request["max_tokens"] * 2, MAX_TOKENS_CAP)
            continue
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            parsed = schema.model_validate_json(text)
        except ValidationError as e:
            stats.notes.append(f"attempt {attempt}: reply didn't match the schema")
            if attempt == 2:
                raise LLMError("invalid_output", str(e)[:300]) from e
            continue

        log.info("llm call %s", {k: v for k, v in stats.__dict__.items() if k != "notes"})  # never content
        return parsed, stats

    raise LLMError("invalid_output", station)  # unreachable, keeps type-checkers happy
