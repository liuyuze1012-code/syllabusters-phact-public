"""The chatbot (revise mode, HARNESS.md section 4): understand → search if needed → rewrite → gates.

R1 understand: fast model, thinking off. Decides change / add / question and whether a new search is needed,
               and how clear the request is. Vague requests (hybrid, decided in code):
                 unclear_scope  → the readings would change DIFFERENT things: ask one question with buttons
                 unclear_amount → only "how much" is open: use a stated default and say so in the reply
               Research: models tend to assume rather than ask; ask only when readings differ materially.
R2 retrieve:   code. Only for requests that need new evidence; new passages continue the numbering (P9, P10…).
R3 rewrite:    strong model. Same gates as Station 4; one retry for failing edits; the rest are dropped.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from phact_contracts.agent import ChatTurn, Context, Edit, Outline, Passage

import gates
import llm
from retrieval import PassageStack
from steps import supervise
from steps.propose import DraftEdit, context_blocks, fix_rule, passage_blocks, to_edit

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
UNDERSTAND = (PROMPTS / "chat_understand.md").read_text()
REVISE = (PROMPTS / "chat_revise.md").read_text()
CLARIFY_MARK = "Quick check:"
ASSESS_NOTE = ("<assessment_mode>This document is ONE graded assessment. Every edit that involves AI must be a complete "
               "design: aias_level (within the course limit: ban 1, restricted up to 3, open up to 5), ai_role, rubric_row, "
               "ai_use_statement, reflection_activity (what the AI gets wrong and how students check) and practicalities "
               "(time, a free or school-licensed tool, an equity note).</assessment_mode>\n")


class Option(BaseModel):
    label: str        # button text, 2–6 words
    message: str      # the fully specified request sent if the professor clicks it


class Intent(BaseModel):
    kind: Literal["change", "add", "question", "off_topic"]
    target_edit_ids: list[str] = []
    search_query: str | None = None
    clarity: Literal["clear", "unclear_scope", "unclear_amount"] = "clear"
    question: str | None = None          # unclear_scope: the one question to ask
    options: list[Option] = []           # unclear_scope: 2–4 readings
    assumption: str | None = None        # unclear_amount: the default PHACT will use


class ReviseOut(BaseModel):
    reply: str
    edits: list[DraftEdit] = []
    removed_edit_ids: list[str] = []


def _edit_blocks(edits: list[Edit]) -> str:
    return "\n".join(
        f'<edit id="{e.edit_id}" version="{e.version}" section="{e.section_id}" op="{e.op}" status="{e.status}">\n'
        f"original: {e.original}\nproposed: {e.proposed}\nrationale: {e.rationale}\n"
        f"evidence: {[ev.id for ev in e.evidence]}  ceph: {e.ceph}  reflection: {e.reflection_activity}  requires: {e.requires}\n"
        + (f"aias_level: {e.aias_level}  ai_role: {e.ai_role}\nrubric_row: {e.rubric_row}\nai_use_statement: {e.ai_use_statement}\n"
           f"practicalities: {e.practicalities}\n" if e.aias_level else "") + "</edit>"
        for e in edits)


def run(message: str, history: list[ChatTurn], outline: Outline, edits: list[Edit], passages: list[Passage],
        context: Context, ai_stance: str | None = None, mode: str = "syllabus") -> dict:
    """mode="assessment": the document is one graded assessment; every edit must be a complete AIAS design."""
    stats_all = []
    # R1: understand
    summary = "\n".join(f"{e.edit_id} ({e.section_id}): {(e.proposed or e.op)[:120]}" for e in edits)
    intent, s = llm.call(station="chat-understand", tier="fast", system=UNDERSTAND,
                         user=f"<edits>\n{summary}\n</edits>\n<message>{message}</message>",
                         schema=Intent, effort="low", max_tokens=1500, think=False)
    stats_all.append(s)

    # Ask at most once in a row: if PHACT just asked, the professor's answer is acted on, never re-questioned.
    just_asked = bool(history) and history[-1].role == "assistant" and history[-1].text.startswith(CLARIFY_MARK)
    if intent.kind not in ("off_topic", "question") and intent.clarity == "unclear_scope" \
            and len(intent.options) >= 2 and not just_asked:
        return {"kind": "clarify", "reply": f"{CLARIFY_MARK} {intent.question or 'What should I change?'}",
                "options": [o.model_dump() for o in intent.options[:4]], "edits": [], "removed_edit_ids": [],
                "new_passages": [], "dropped": [], "searches": [], "stats": [x.__dict__ for x in stats_all]}
    # a button answer is already fully specified: no "I assumed" on top of it
    assumption = intent.assumption if intent.clarity != "clear" and not just_asked else None

    if intent.kind == "off_topic":  # scope check with context; the guardrail handles clear-cut categories
        import safety
        return {"kind": "blocked", "reply": safety.FRIENDLY, "edits": [], "removed_edit_ids": [], "new_passages": [],
                "dropped": [], "searches": [], "stats": [x.__dict__ for x in stats_all]}

    # R2: search, only when new evidence is needed
    stack = PassageStack(start=len(passages) + 1, existing=passages)
    new_ids = []
    if intent.search_query and intent.kind != "question":
        new_ids = stack.add(intent.search_query, ["guidance", "workforce"], k=4, why="chat: " + message[:60])
    all_passages = stack.passages

    # R3: rewrite / answer
    sections = "\n".join(f'<section id="{x.id}" title="{x.title}">\n{x.text}\n</section>' for x in outline.sections)
    chat = "\n".join(f'<chat role="{t.role}">{t.text}</chat>' for t in history[-6:])
    user = (f"{sections}\n\n{_edit_blocks(edits)}\n\n{passage_blocks(all_passages)}\n\n{context_blocks(context)}\n\n"
            f"<course_ai_stance>{ai_stance or 'not stated: follow <professor>'}</course_ai_stance>\n{chat}\n{ASSESS_NOTE if mode == "assessment" else ""}<intent kind=\"{intent.kind}\" targets=\"{','.join(intent.target_edit_ids)}\"/>\n"
            + (f"<assumption>{assumption}</assumption>\n" if assumption else "") + f"<message>{message}</message>")
    out, s = llm.call(station="chat-revise", tier="strong", system=REVISE, user=user,
                      schema=ReviseOut, effort="medium", max_tokens=10000)
    stats_all.append(s)

    rule_ids = {r.id for r in context.school_rules}
    current = {e.edit_id: e for e in edits}
    kept, dropped = [], []
    for d in (out.edits if intent.kind != "question" else []):
        fix_rule(d, rule_ids)
        problems = gates.check_edit(d.model_dump(), outline, all_passages, rule_ids, ai_stance)
        if mode == "assessment":
            problems += gates.check_suggestion(d.model_dump(), ai_stance)
        if problems:
            dropped.append({"edit_id": d.edit_id, "problems": problems})
            continue
        version = current[d.edit_id].version + 1 if d.edit_id in current else 1
        d.requires = [r for r in d.requires if r in current or r in {x.edit_id for x in out.edits}]
        kept.append(to_edit(d, all_passages, version=version))

    if kept:  # changed edits get the same Supervisor check as first drafts
        kept, s = supervise.run(kept, outline, all_passages, context, ai_stance)
        stats_all += s

    reply = out.reply
    if assumption and not reply.lower().startswith("i assumed"):
        reply = f"I assumed: {assumption}. Tell me if you meant something else.\n\n{reply}"
    if dropped:
        reply += f"\n\n(PHACT held back {len(dropped)} change(s) that failed its source checks.)"
    return {
        "kind": intent.kind, "reply": reply, "assumption": assumption, "edits": [e.model_dump() for e in kept],
        "removed_edit_ids": [i for i in out.removed_edit_ids if i in current],
        # only passages that weren't already in the conversation (a re-found passage keeps its old id)
        "new_passages": [p.model_dump() for p in all_passages if p.id in new_ids and p.id not in {q.id for q in passages}],
        "dropped": dropped, "searches": stack.queries,
        "stats": [x.__dict__ for x in stats_all],
    }
