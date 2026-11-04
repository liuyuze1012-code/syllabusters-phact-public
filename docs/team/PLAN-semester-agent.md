# PHACT semester agent: plan (draft for approval)

Nov 4. After meeting ASPPH staff: supporting professors **throughout the semester** is a stronger value proposition than a one-time syllabus check. PHACT becomes a **course companion**: the syllabus is the course's backbone, and the professor keeps adding materials (assignments, rubrics, lecture slides, discussion prompts, exams, case studies). For each one, PHACT gives concrete, sourced suggestions on integrating AI and covering CEPH competencies.

## 0. The core problem to fix: weak AI suggestions
Today's suggestions are generic ("students use AI to brainstorm, then reflect"). Three causes:
1. **No shared framework for *how much* AI.** We only have ban/restricted/open per course.
2. **No library of proven patterns.** The knowledge base has ASPPH strategy documents, not "here's how a biostatistics assignment uses AI well".
3. **No definition of a "strong" suggestion.** The prompt asks for edits, not for a complete, teachable design.

### Fix 1: adopt the AI Assessment Scale (AIAS) as the backbone
The AIAS (Perkins, Furze, Roe, MacVaugh; [revised Dec 2024](https://arxiv.org/abs/2412.09029), [pilot study](https://web3.arxiv.org/pdf/2403.14692)) is the most widely used framework: **5 levels per task**, from no AI to AI exploration. Every PHACT suggestion names its level, and the level must fit the course stance and the school policy (a code gate, like the AI ban). Per the 2024 revision, show levels as *different*, not *better/worse* (no traffic-light colours).

Mapping to today's course stance (to confirm against the paper):
| Course stance | Allowed AIAS levels |
|---|---|
| ban | 1 (no AI) |
| restricted | 1–3 |
| open | 1–5 |

### Fix 2: a "strong suggestion" has 8 required parts (enforced by schema + gate)
1. **Where**: the exact assignment, step or week
2. **AIAS level**
3. **What AI does / what the student does** (AI is decision support, never the decider)
4. **Why**: the learning goal and CEPH competency it serves
5. **How it's assessed**: a rubric row (no AI activity without an assessment criterion)
6. **Student-facing AI-use statement** (disclosure wording, ready to paste)
7. **Failure mode + reflection**: what the AI gets wrong here and how students check it
8. **Practicalities**: time cost, a free or school-licensed tool, an accessibility/equity note

### Fix 3: a pattern library in the knowledge base (§3)

## 1. UI: from "syllabus revision" to a **course hub**
- **Course hub** (replaces the course page): the **semester timeline** built from the syllabus's weeks. Each week shows its materials as cards (type, AIAS level, competencies, status).
- **+ Add material** to any week: assignment, rubric, lecture slides, reading, discussion prompt, exam/quiz, case/activity. Upload or paste.
- **Material workspace** = today's revise workspace (document right, chat left, citations, accept/reject, Editor, export), with **type-specific suggestions and chips**.
- **Semester coverage**: competencies × graded assessments. Which competencies are actually assessed, where, and at which AIAS level. This replaces "syllabus claims".
- **Course AI plan**: one table of every assessment's AIAS level, checked against the syllabus AI policy (the syllabus and assignments must agree).
- **"This week" panel**: upcoming weeks with no activity or no assessment for a claimed competency → suggestions ("Week 6 has readings only; here are 2 activities").

## 2. Harness: one pipeline, per-document-type stations
Reuse everything that works (extract, scrub, gates, Supervisor, export, chat loop) and add a **document-type layer**:
1. **Classify** the upload (Haiku): assignment / rubric / slides / reading / discussion / exam / case / syllabus. The professor confirms.
2. **Structure, per type** (Haiku, one schema per type), e.g. assignment = task, deliverables, steps, criteria, weight, due week, competencies claimed; rubric = criteria × levels; slides = topics, activities, questions; exam = items by type.
3. **Course context** (new, the "memory"): a compact course profile goes into every call. It holds the stance, school rules, competencies, the week this material belongs to, related materials (the assignment's rubric), and **past decisions** ("rejected AI-tutor ideas twice").
4. **Map** to competencies, for this material.
5. **Retrieve**: pattern cards filtered by `material_type`, `aias_level` ≤ allowed, and competency, plus ASPPH guidance.
6. **Propose, per type** (Opus): new prompts (`propose_assignment.md`, `propose_rubric.md`, `propose_slides.md`, …) sharing the 8-part schema.
7. **Gates** (extended): AIAS level within stance/school range; every AI activity has a rubric criterion; consistency with the syllabus AI policy; plus today's checks.
8. **Supervisor**: also checks the 8 parts are real, not filler.
9. **Export**: revised material, plus a rubric and AI-use statement ready to paste.

## 3. Knowledge base: the pattern library + new credible sources
**New `source_type: practice`** with metadata `material_type`, `aias_level`, `competencies`, `area` (biostat, epi, policy, leadership…).

**Sources to add** (check licences; where reuse isn't allowed, **cite and summarize**, as with SOPHE):
- AIAS revisited ([arXiv 2412.09029](https://arxiv.org/abs/2412.09029)) and the [AIAS pilot](https://web3.arxiv.org/pdf/2403.14692)
- [PAHO guide to designing AI instructions in public health (Oct 2025)](https://www.paho.org/en/news/20-10-2025-paho-publishes-guide-designing-artificial-intelligence-instructions-public-health)
- Public-health teaching examples: [Columbia CTL public health](https://ai.ctl.columbia.edu/engage/public-health), [GMU College of Public Health AI guide](https://publichealth.gmu.edu/about/faculty-resources/ai-resource-guide-teaching-and-course-design), [Northwestern Searle design heuristic](https://searle.northwestern.edu/docs/20230313-designing-learning-experiences_with_generaive_ai_heuristic.pdf)
- Assessment redesign: [Waterloo CTE](https://uwaterloo.ca/centre-for-teaching-excellence/catalogs/tip-sheets/redesigning-unsupervised-assessments-genai-era), [Toronto CTSI design clinic](https://teachingdev.lamp4.utoronto.ca/wp-content/uploads/Generative-AI-Assessment-Design-Clinic-Centre-for-Teaching-Support-Innovation-attach.pdf), [Johns Hopkins classroom guidance](https://teaching.jhu.edu/university-teaching-policies/generative-ai/)
- **The CEPH accreditation criteria themselves** (the long-standing gap behind "no source" flags)

**PHACT pattern cards** (our own writing, each citing those sources, ~25–30 for v1): one per material type × competency area × AIAS level, in the 8-part format. Example: *"Biostatistics problem set · AIAS 3: AI explains code errors; students must run, verify and annotate every fix; rubric row 'verification log'."* A human (ASPPH or the team) reviews each card before publishing. Add retrieval tests per material type.

## 4. Database changes (extends the Day-2 plan)
- `COURSE#<c>#MAT#<id>`: material (type, week, title, versions, AIAS level, competencies, status)
- `ANALYSIS`, `EDIT` and `DECISION` items keyed by **material**, not just syllabus
- `COURSE#<c>#PROFILE`: the compact course memory (stance, competencies, decision summary), updated after each decision
- Coverage is computed from materials' graded tasks, not stored

## 5. What we're missing (decide or explicitly defer)
1. **Student work must never be uploaded** (FERPA). Materials are *instructor* documents. Add a UI warning, plus a check: heavy personal-data counts or many student names → refuse ("this looks like student work").
2. **Copyright**: uploaded slides and readings stay private to that professor and **never** enter the shared knowledge base.
3. **How we know suggestions are "strong"**: a written rubric (the 8 parts + correctness + feasibility), 10–15 golden examples, an LLM-judge for iteration, and ASPPH expert review for the final word. Without this, "better" is opinion.
4. **Consistency across materials**: an assignment's AI rules can't contradict the syllabus policy (gate) or the school policy (Day-2 plan).
5. **Equity**: suggest free or school-licensed tools only. No suggestion that requires a paid account.
6. **Cost**: ~10 materials × ~$0.30 analysis ≈ **$3 per course per semester** plus chat. Still small.
7. **Later, not now**: LMS (Canvas) import/export, calendar nudges or emails ("week 6 is next week"), student-facing tools.

## 6. Steps, in order
| # | Step | Est. |
|---|---|---|
| 1 | **Contracts**: `Material`, `MaterialType`, the 8-part `Suggestion`, AIAS level on edits, `practice` source metadata | 1 h |
| 2 | **Pattern library v1**: collect sources, write ~15 cards for the MVP types, publish to the KB, retrieval tests | 3–4 h |
| 3 | **Harness**: classifier + assignment/rubric structure schemas + course profile + `propose_assignment.md` + AIAS gate + rubric-criterion gate + Supervisor update | 4–5 h |
| 4 | **UI**: course hub (timeline + add material + material cards) → material workspace (reuse) → semester coverage + course AI plan | 4 h |
| 5 | **Eval**: golden examples + judge rubric; compare old vs. new suggestions on 5 assignments | 2 h |
| 6 | **Further types** (slides, discussion, exam) once assignments are strong | later |

**MVP slice (if the demo is tomorrow):** syllabus + **assignment (with its rubric)** as the second type, the course hub timeline, AIAS levels, the 8-part suggestions and ~15 pattern cards. Assignments are where CEPH (graded evidence) and AI integration meet, so they show the most value per hour.
