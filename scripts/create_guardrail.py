"""Create PHACT's Bedrock Guardrail (US-8). Safe to rerun: reuses the guardrail if it exists.

    python scripts/create_guardrail.py      # writes agent/guardrail_ids.json

Checks professor chat messages before Claude sees them:
  - denied topics: concrete off-topic areas (vague topics like "anything not public health" misfire)
  - content filters: hate, insults, sexual, violence, misconduct
  - prompt-attack filter: "ignore your instructions…"
Blocked messages get a friendly reply instead of an error.
"""

import json
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
NAME = "phact-chat-guardrail"
FRIENDLY = ("PHACT can only help with this course's syllabus: its competencies, assignments, sources and AI policy. "
            "Try asking about a specific week or edit.")

TOPICS = [
    {"name": "PersonalFinance", "definition": "Advice about personal investing, stocks, cryptocurrency, taxes, loans, or personal money management.",
     "examples": ["Which stocks should I buy?", "How do I lower my taxes?"]},
    {"name": "PersonalMedicalAdvice", "definition": "Diagnosis or treatment advice for an individual's own health condition or symptoms.",
     "examples": ["What medication should I take for my headache?", "Do I have the flu?"]},
    {"name": "EntertainmentAndCelebrities", "definition": "Movies, TV shows, music, sports results, video games, or celebrity news unrelated to teaching a course.",
     "examples": ["Who won the game last night?", "Recommend a movie for tonight."]},
    # No grant/document topic here on purpose: the guardrail matches words, so "write my NIH grant"
    # and "add a grant-writing assignment for students" look the same to it (both were blocked, Nov 3),
    # and the second is a legitimate edit (ASPPH recommends "Federal grant writing" training).
    # Scope ("is this about the course?") is judged by the chat's understand step instead (kind=off_topic).
    {"name": "CreativeWriting",
     "definition": "Writing poems, song lyrics, jokes, fiction or stories for entertainment.",
     "examples": ["Write a poem about my dog.", "Tell me a funny story."]},
    {"name": "CompletingStudentWork", "definition": "Doing students' graded coursework for them, such as writing a student's essay or answering a student's exam questions.",
     "examples": ["Write the reflection paper for my student.", "Answer the quiz questions for the class."]},
]


def main():
    b = boto3.client("bedrock")
    config = dict(
        name=NAME, description="PHACT: keep professor chat on-topic and safe",
        topicPolicyConfig={"topicsConfig": [{**t, "type": "DENY"} for t in TOPICS]},
        contentPolicyConfig={"filtersConfig": [
            {"type": t, "inputStrength": "MEDIUM", "outputStrength": "NONE"}
            for t in ("HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT")
        ] + [{"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"}]},
        blockedInputMessaging=FRIENDLY, blockedOutputsMessaging=FRIENDLY,
    )
    existing = [g for g in b.list_guardrails()["guardrails"] if g["name"] == NAME]
    if existing:  # rerunning applies the current TOPICS and publishes a new version
        gid = existing[0]["id"]
        b.update_guardrail(guardrailIdentifier=gid, **config)
        print(f"updated guardrail: {gid}")
    else:
        gid = b.create_guardrail(**config)["guardrailId"]
        print(f"created guardrail: {gid}")
    while b.get_guardrail(guardrailIdentifier=gid)["status"] not in ("READY", "FAILED"):
        time.sleep(2)
    version = b.create_guardrail_version(guardrailIdentifier=gid)["version"]
    out = {"guardrail_id": gid, "guardrail_version": version, "friendly_message": FRIENDLY}
    (ROOT / "agent" / "guardrail_ids.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
