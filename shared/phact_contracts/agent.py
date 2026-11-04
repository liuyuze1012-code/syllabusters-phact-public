"""The contract between the backend worker and the AI agent.

Every field the backend sends to the agent, and every field the agent sends back,
is defined here. The backend, the agent, the mock and the tests all import these
classes, so a change here is a change for everyone: agree on it as a team first.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CEPH_COUNT = 22  # CEPH MPH foundational competencies

AssessmentType = Literal["simulation", "real_world", "ai_assisted"]


# ---------- Input: what the backend sends ----------

class Course(BaseModel):
    code: str
    level: Literal["MPH", "DrPH", "BS", "other"] = "MPH"
    format: Literal["in_person", "online_sync", "online_async", "hybrid"]
    size: int = Field(ge=1)


class Targets(BaseModel):
    ai_level: int = Field(ge=0, le=4, description="Desired AI-incorporation level on the 0–4 rubric")
    assessment_types: list[AssessmentType] = []


class SchoolRule(BaseModel):
    id: str = Field(description="e.g. GU-AI-2 or DEF-AI-1")
    text: str


class Context(BaseModel):
    """Assembled by the backend from DynamoDB. The agent never reads the database itself."""
    school_rules: list[SchoolRule] = []
    policy_source: Literal["school", "phact_default"] = "phact_default"
    professor: str = Field("", description="Short preference summary")
    memory: str = Field("", description="Decision-memory summary, at most ~300 words")


class AnalyzeRequest(BaseModel):
    mode: Literal["analyze"] = "analyze"
    job_id: str
    syllabus_text: str = Field(description="Already PII-scrubbed by the Safety gate")
    course: Course
    confirmed_competencies: list[int] = Field(description="CEPH ids (1–22) assigned to this course")
    targets: Targets
    context: Context = Context()


# ---------- Shared pieces of the output ----------

class Section(BaseModel):
    id: str = Field(description="Stable id, e.g. week-6")
    kind: Literal["heading", "objective", "week", "assignment", "policy", "other",
                  "instructions", "task", "rubric"]  # the last three: sections of an assessment (homework, exam, project…)
    title: str
    text: str


class Assignment(BaseModel):
    id: str
    section_id: str
    title: str
    weight: float | None = Field(None, description="Share of the final grade, 0–1")
    what_it_tests: str
    assessed: bool = Field(description="Graded work, not just practice")


class Outline(BaseModel):
    sections: list[Section]
    assignments: list[Assignment] = []
    ai_policy: str | None = None
    claimed_competencies: list[int] = []


class Passage(BaseModel):
    """A knowledge base chunk. The snippet is the exact chunk text, never a paraphrase."""
    id: str = Field(description="P1, P2, …")
    title: str
    section: str | None = None
    snippet: str
    uri: str
    source_type: Literal["guidance", "workforce", "exemplar", "practice"]  # practice = PHACT pattern cards


class Workforce(BaseModel):
    text: str
    evidence: list[str] = Field(description="Passage ids")


class CompetencyResult(BaseModel):
    id: int = Field(ge=1, le=CEPH_COUNT)
    status: Literal["covered", "partial", "missing", "not_assigned"]
    evidence: list[str] = Field([], description="Section ids")
    reason: str = ""
    rule: str | None = Field(None, description="CEPH interpretation rule applied, if any")
    workforce: Workforce | None = None


class AIRating(BaseModel):
    score: int = Field(ge=0, le=4)
    mode: Literal["prohibited", "restricted", "collaborative", "unstated"]
    reasons: list[str]


class Assessments(BaseModel):
    simulation: int = 0
    real_world: int = 0
    ai_assisted: int = 0


class Evidence(BaseModel):
    id: str
    title: str
    snippet: str
    uri: str


class Edit(BaseModel):
    edit_id: str
    version: int = 1
    section_id: str
    op: Literal["replace", "insert_after", "delete"]
    original: str | None = Field(None, description="Exact text being replaced or deleted")
    proposed: str | None = None
    rationale: str = Field(description="AI suggestion. No citations in here")
    evidence: list[Evidence] = Field([], description="Evidence from sources, kept apart from the rationale")
    school_rule: str | None = None
    ceph: list[int] = []
    reflection_activity: str | None = None
    # The 8-part "strong suggestion" (assessments). Where = section/original; why = rationale + ceph;
    # what the AI gets wrong + how students check = reflection_activity.
    aias_level: int | None = Field(None, ge=1, le=5, description="AI Assessment Scale level this change sets for the task")
    ai_role: str | None = Field(None, description="What AI does and what the student does")
    rubric_row: str | None = Field(None, description="How the AI-related work is graded")
    ai_use_statement: str | None = Field(None, description="Ready-to-paste instruction for students")
    practicalities: str | None = Field(None, description="Time cost, free or licensed tool, equity note")
    requires: list[str] = Field([], description="Edit ids that must be accepted with this one (e.g. a grading "
                                "rebalance), or the syllabus stops making sense")
    supervisor: Literal["pass", "flagged", "not_run"] = "not_run"
    supervisor_note: str | None = Field(None, description="Why the Supervisor flagged it, or which citations it removed")
    status: Literal["draft", "accepted", "rejected"] = "draft"
    purpose: Literal["ai_incorporation", "workforce", "competency"] | None = Field(
        None, description="Why this change exists: bring AI in, update to a workforce standard, or complete a CEPH competency")


class Meta(BaseModel):
    timings_ms: dict[str, int] = {}
    models: dict[str, str] = {}
    tokens: dict[str, int] = {}
    mock: bool = False


# ---------- Output: what the agent returns ----------

class AnalyzeResponse(BaseModel):
    ok: Literal[True] = True
    job_id: str
    outline: Outline
    competencies: list[CompetencyResult]
    ai_rating: AIRating
    assessments: Assessments
    edits: list[Edit]
    passages: list[Passage]
    meta: Meta = Meta()

    @field_validator("competencies")
    @classmethod
    def all_22(cls, v: list[CompetencyResult]) -> list[CompetencyResult]:
        ids = sorted(c.id for c in v)
        if ids != list(range(1, CEPH_COUNT + 1)):
            raise ValueError("competencies must contain each CEPH id 1–22 exactly once")
        return v


class ErrorResponse(BaseModel):
    ok: Literal[False] = False
    job_id: str
    error: str = Field(description="Machine code, e.g. unreadable_syllabus")
    message: str = Field(description="Friendly text shown to the professor")


# ---------- Revise (chat edit) ----------

class ChatTurn(BaseModel):
    role: Literal["professor", "assistant"]
    text: str


class ReviseRequest(BaseModel):
    mode: Literal["revise"] = "revise"
    job_id: str
    analysis_id: str
    message: str = Field(description="Already checked by the Safety gate")
    scope: Literal["edits", "section", "all"] = Field(
        "all", description="What the professor is pointing at: selected edits, one section, or the whole syllabus"
    )
    target_edit_ids: list[str] = Field([], description="Used when scope is 'edits'")
    section_id: str | None = Field(None, description="Used when scope is 'section'")
    history: list[ChatTurn] = Field([], description="Last 6 turns at most")
    outline: Outline
    edits: list[Edit]
    passages: list[Passage]
    context: Context = Context()


class ReviseResponse(BaseModel):
    ok: Literal[True] = True
    job_id: str
    kind: Literal["change", "add", "question"] = Field(
        description="change: rewrote edits · add: new edit(s) from a new search · question: answered, nothing changed"
    )
    edits: list[Edit] = Field([], description="New versions of changed edits, or new edits. Empty for a question")
    new_passages: list[Passage] = Field([], description="Passages found for an 'add' request, numbered after the existing ones")
    removed_edit_ids: list[str] = Field([], description="Edits the professor asked to drop")
    reply: str = Field(description="Short chat reply shown in the Edit studio")
    meta: Meta = Meta()

    @model_validator(mode="after")
    def question_changes_nothing(self) -> "ReviseResponse":
        if self.kind == "question" and (self.edits or self.new_passages or self.removed_edit_ids):
            raise ValueError("a 'question' reply must not change edits or passages")
        return self
