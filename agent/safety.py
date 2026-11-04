"""The Safety gate (US-8). Runs before any text reaches Claude.

scrub_pii(text):     Amazon Comprehend finds personal data; code swaps each item for a tag like [EMAIL_1].
                     Dates are NOT scrubbed (Comprehend calls "Week 6" a date; the schedule must survive).
check_message(text): the Bedrock Guardrail blocks off-topic, harmful, or prompt-attack chat messages and
                     returns a friendly refusal instead of an error.
The backend's app/services/safety.py can import or copy this module unchanged.
"""

import json
import os
import re
from pathlib import Path

import boto3

REGION = os.getenv("AWS_REGION", "us-west-2")
SCRUB_TYPES = {"NAME", "EMAIL", "PHONE", "ADDRESS", "SSN", "CREDIT_DEBIT_NUMBER", "USERNAME", "PASSWORD",
               "BANK_ACCOUNT_NUMBER", "DRIVER_ID", "PASSPORT_NUMBER"}
# Low on purpose: missing a real person is worse than over-redacting. (At 0.8, "Dr. Maria Lopez"
# scored 0.79 and leaked, Nov 3.) Names use 0.7, which still drops junk like "D. 2023" (0.62).
MIN_SCORE = 0.5
MIN_NAME_SCORE = 0.7
# Authors in reading lists score 1.0 too ("Helm-Murtagh", "Galea"), so score can't separate them from
# real people; the text right AFTER the name can: citations, not credentials or emails.
CITATION_AFTER = re.compile(r"^\s*(?:et al|\(eds?\.?\)|&|and\s+[A-Z]|\(?(?:19|20)\d\d|,\s*[A-Z]\.\s|\(book\)|book\b|text\b|"
                            r"editors?\b|[;\n]?\s*o?\s*ch\.?\s*\d|& sons)", re.I)
YEAR = re.compile(r"\b(?:19|20)\d\d\b")  # "Miranda, D. 2023": a name with a year in it is a citation
# Comprehend calls course codes addresses; tagging "PHC 6149" would hide the course from Claude.
COURSE_CODE = re.compile(r"^[A-Z]{2,5}\s?-?\d{3,4}[A-Z]?$")
CHUNK = 90_000  # Comprehend allows 100 KB per call

_ids_file = Path(__file__).with_name("guardrail_ids.json")
_ids = json.loads(_ids_file.read_text()) if _ids_file.exists() else {}
GUARDRAIL_ID = os.getenv("GUARDRAIL_ID", _ids.get("guardrail_id", ""))
GUARDRAIL_VERSION = os.getenv("GUARDRAIL_VERSION", _ids.get("guardrail_version", "DRAFT"))
FRIENDLY = _ids.get("friendly_message", "PHACT can only help with this course's syllabus.")


def scrub_pii(text: str) -> tuple[str, dict[str, int]]:
    """Return (scrubbed text, counts by type). The same value always gets the same tag."""
    clean, counts, _ = scrub(text)
    return clean, counts


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put the real values back (for the professor's OWN exported document only)."""
    for tag, value in mapping.items():
        text = text.replace(tag, value)
    return text


def scrub(text: str, existing: dict[str, str] | None = None) -> tuple[str, dict[str, int], dict[str, str]]:
    """Return (scrubbed text, counts by type, {tag: original value}). The map stays on the server
    so the professor's own export can be restored; it is never sent to Claude. `existing` continues an
    earlier map (a hand edit to the same syllabus): known values keep their tag, new ones get new numbers."""
    comprehend = boto3.client("comprehend", region_name=REGION)
    spans = []
    for start in range(0, len(text), CHUNK):
        part = text[start:start + CHUNK]
        for e in comprehend.detect_pii_entities(Text=part, LanguageCode="en")["Entities"]:
            if e["Type"] not in SCRUB_TYPES or e["Score"] < MIN_SCORE:
                continue
            value = part[e["BeginOffset"]:e["EndOffset"]]
            if e["Type"] == "NAME":
                if e["Score"] < MIN_NAME_SCORE or YEAR.search(value) or \
                        CITATION_AFTER.match(part[e["EndOffset"]:e["EndOffset"] + 30]):
                    continue  # an author in a citation, not a person in this course
            if e["Type"] == "PHONE" and len(re.sub(r"\D", "", value)) < 7:
                continue  # "9-1-1", a bare area code
            if e["Type"] == "ADDRESS" and (not re.search(r"\d", value) or COURSE_CODE.match(value)):
                continue  # "United States", "Broward Hall", or the course code "PHC 6149"
            spans.append((start + e["BeginOffset"], start + e["EndOffset"], e["Type"]))
    # Give each distinct value one tag, then replace EVERY occurrence of it, so a name Comprehend
    # caught once is scrubbed everywhere (it scored "TA: Jane Doe" low but caught a later "Jane Doe").
    tags: dict[str, str] = {v: t for t, v in (existing or {}).items()}
    counts: dict[str, int] = {}
    for t in (existing or {}):
        m = re.match(r"\[([A-Z_]+?)_(\d+)\]$", t)
        if m:
            counts[m.group(1)] = max(counts.get(m.group(1), 0), int(m.group(2)))
    new_counts: dict[str, int] = {}
    for begin, end, kind in sorted(spans):
        value = text[begin:end].strip()
        if len(value) < 3 or value in tags:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        new_counts[kind] = new_counts.get(kind, 0) + 1
        tags[value] = f"[{kind}_{counts[kind]}]"
    for value in sorted(tags, key=len, reverse=True):  # longest first, so "Jane Doe" wins over "Jane"
        text = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", tags[value], text)
    return text, new_counts, {tag: value for value, tag in tags.items()}


def check_message(text: str) -> tuple[bool, str | None]:
    """Return (allowed, friendly message if blocked).

    The guardrail judges the message with no context, so "Why E4?" looked like a TV channel and was
    blocked as entertainment. For the CHECK ONLY, edit ids become "edit 4" and the message is framed
    as being about syllabus edits. The professor's real message is never changed.
    """
    if not GUARDRAIL_ID:
        return True, None
    framed = "A professor's chat message about proposed edits to their course syllabus: " + \
             re.sub(r"\bE(\d+)\b", r"edit \1", text)
    rt = boto3.client("bedrock-runtime", region_name=REGION)
    r = rt.apply_guardrail(guardrailIdentifier=GUARDRAIL_ID, guardrailVersion=GUARDRAIL_VERSION, source="INPUT",
                           content=[{"text": {"text": framed}}])
    if r["action"] == "GUARDRAIL_INTERVENED":
        outputs = r.get("outputs") or []
        return False, (outputs[0]["text"] if outputs else FRIENDLY)
    return True, None
