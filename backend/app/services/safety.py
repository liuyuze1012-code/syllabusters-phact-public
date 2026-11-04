"""The Safety gate (US-8). Runs on EVERY text before it reaches the agent:
syllabus text, preference notes, and every chat-edit message.

1. Comprehend DetectPiiEntities → replace NAME/EMAIL/PHONE/ADDRESS with tags like [EMAIL_1]
   (100 KB limit per call: split long text by section).
2. Bedrock ApplyGuardrail(source="INPUT") → block off-topic or manipulative input.
"""

from dataclasses import dataclass


@dataclass
class SafetyResult:
    text: str              # the scrubbed text
    blocked: bool          # Guardrail intervened
    message: str | None    # friendly message when blocked
    pii_found: int = 0


def scrub_pii(text: str) -> tuple[str, int]:
    raise NotImplementedError  # TODO: comprehend.detect_pii_entities(Text=..., LanguageCode="en")


def check_guardrail(text: str) -> tuple[bool, str | None]:
    raise NotImplementedError  # TODO: bedrock-runtime apply_guardrail(guardrailIdentifier, guardrailVersion, source="INPUT", content=[...])


def run(text: str) -> SafetyResult:
    scrubbed, n = scrub_pii(text)
    blocked, msg = check_guardrail(scrubbed)
    return SafetyResult(text=scrubbed, blocked=blocked, message=msg, pii_found=n)
