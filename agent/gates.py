"""Code checks between stations (HARNESS.md section 3). This is what makes citations trustworthy.

check_edit: the gate on every proposed or revised edit:
  - the section exists
  - for replace/delete, `original` really appears in that section (whitespace-insensitive)
  - every evidence id is a passage we actually gave the model
  - every school rule id is one we gave it
  - an edit that adds an AI tool has a reflection activity
  - the rationale doesn't smuggle in citations
"""

import re

from phact_contracts.agent import Outline, Passage

AI_TOOL = re.compile(r"\b(chatgpt|copilot|claude|gemini|generative ai|ai tool|ai-generated|ai assistant|large language model|llm)\b", re.I)
CITATION_IN_TEXT = re.compile(r"\b(according to|as stated in|asph framework says|aspph (?:ai )?framework (?:says|states))\b|\bP\d+\b", re.I)


def squash(text: str) -> str:
    """Compare text ignoring layout: whitespace runs, table pipes and curly quotes don't matter."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[\s|]+", " ", text).strip().lower()


AI_MENTION = re.compile(r"\b(AI|A\.I\.|chatgpt|copilot|claude|gemini|llms?|large language models?)\b", re.I)
PERMITS_USE = re.compile(r"\b(may (use|ask|prompt|consult|try|run|query)|can (use|ask|prompt)|are allowed|is allowed|"
                         r"are permitted|is permitted|permitted to use|encouraged to (use|try)|optional(ly)?|"
                         r"use an? (ai|chatbot)|ask an? (ai|chatbot))\b", re.I)
FORBIDS_USE = re.compile(r"\b(not (permitted|allowed)|prohibited|may not|must not|cannot use|banned|no ai)\b", re.I)


def violates_ban(text: str) -> bool:
    """True if text lets students USE AI (a ban allows teaching ABOUT AI, not using it).

    Checked sentence by sentence: a sentence that mentions AI and grants permission, without
    also forbidding it, is a violation. "Students may ask an AI tool…" fails;
    "Students may not use AI…" and "Students critique an AI-generated chart" pass.
    """
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        if AI_MENTION.search(sentence) and PERMITS_USE.search(sentence) and not FORBIDS_USE.search(sentence):
            return True
    return False


SCHEDULE_CHARS = 280  # about two lines: "Leadership Strategy Case Brief (10 pts, due Mar 25); see Assignments"


def check_edit(edit: dict, outline: Outline, passages: list[Passage], rule_ids: set[str],
               ai_stance: str | None = None) -> list[str]:
    problems = []
    if ai_stance == "ban" and violates_ban(edit.get("proposed") or ""):
        problems.append("the course bans AI, but this edit lets students use AI tools; teach about AI instead")
    sections = {s.id: s for s in outline.sections}
    sec = sections.get(edit.get("section_id"))
    if sec is None:
        return [f"section {edit.get('section_id')!r} doesn't exist"]
    op = edit.get("op")
    if op in ("replace", "delete"):
        original = edit.get("original") or ""
        if len(original.strip()) < 3:
            problems.append(f"{op} needs the exact original text")
        elif squash(original) not in squash(sec.text):
            problems.append(f"original text not found word for word in section {sec.id!r}")
    if op in ("replace", "insert_after") and not (edit.get("proposed") or "").strip():
        problems.append("proposed text is empty")
    # Format fit: a schedule entry must stay schedule-sized. A 120-word assignment brief pasted into one
    # week's row made the syllabus lopsided (Gavin's PHC 6149 test, Nov 3).
    proposed = (edit.get("proposed") or "").strip()
    if sec.kind == "week" and op in ("replace", "insert_after"):
        limit = max(SCHEDULE_CHARS, int(2.5 * len((edit.get("original") or "").strip())))
        if len(proposed) > limit:
            problems.append(f"too long for the schedule ({len(proposed)} characters, limit {limit}): keep this week's "
                            "entry as short as the rows around it (a title, points and due date), and put the full "
                            "description in the assignments section as a separate edit linked with `requires`")
    known = {p.id for p in passages}
    if not edit.get("evidence_ids"):  # US-6: every recommendation cites at least one ASPPH source
        problems.append("cites no ASPPH passage; every edit needs at least one supporting passage")
    bad = [e for e in edit.get("evidence_ids", []) if e not in known]
    if bad:
        problems.append(f"cites passages that weren't provided: {bad}")
    if edit.get("school_rule") and edit["school_rule"] not in rule_ids:
        problems.append(f"cites unknown school rule {edit['school_rule']!r}")
    if AI_TOOL.search(edit.get("proposed") or "") and not (edit.get("reflection_activity") or "").strip():
        problems.append("adds an AI tool without a reflection activity")
    if CITATION_IN_TEXT.search(edit.get("rationale") or ""):
        problems.append("rationale contains citations; evidence belongs in evidence_ids only")
    return problems


# ---------- assessments: the 8-part "strong suggestion" (see aias.py, prompts/propose_assessment.md) ----------
PARTS = {"ai_role": "what the AI does and what the student does", "rubric_row": "how it is graded (a rubric row)",
         "ai_use_statement": "the AI-use statement for students", "reflection_activity": "what the AI gets wrong and how students check",
         "practicalities": "practicalities (time, free or licensed tool, equity)"}
PAID_TOOL = re.compile(r"\b(chatgpt plus|chatgpt pro|claude pro|gemini advanced|copilot pro|paid (?:plan|subscription|account)|"
                       r"premium (?:plan|subscription))\b", re.I)


NEGATED = re.compile(r"\b(no|not|without|never|don'?t|doesn'?t|isn'?t|aren'?t|avoid|instead of|rather than|free)\b", re.I)


def check_suggestion(edit: dict, ai_stance: str | None = None) -> list[str]:
    """Extra checks for assessment suggestions. A suggestion that brings AI into a task must name its AIAS
    level (within what the course allows) and include every part a professor needs to use it."""
    import aias
    problems = []
    level = edit.get("aias_level")
    touches_ai = bool(AI_MENTION.search(edit.get("proposed") or "")) or level is not None
    if not touches_ai:
        return problems
    if level is None:
        problems.append("brings AI into the task but has no aias_level (1-5)")
        return problems
    if not 1 <= level <= 5:
        problems.append("aias_level must be 1-5")
        return problems
    cap = aias.max_level(ai_stance)
    if level > cap:
        problems.append(f"AIAS level {level} is above what this course allows (stance {ai_stance or 'restricted'}: up to level {cap})")
    if level >= 2:
        for key, what in PARTS.items():
            if len((edit.get(key) or "").strip()) < 20:
                problems.append(f"missing or too thin: {what}")
    blob = " ".join(str(edit.get(k) or "") for k in ("proposed", "ai_role", "practicalities", "ai_use_statement"))
    # Sentence by sentence, and only when it RELIES on a paid plan: "no paid subscription needed" is the
    # opposite (it dropped a good edit, Nov 4).
    for sentence in re.split(r"(?<=[.!?;])\s+", blob):
        if PAID_TOOL.search(sentence) and not NEGATED.search(sentence):
            problems.append("relies on a paid AI plan; suggest a free or school-licensed tool so every student can take part")
            break
    return problems
