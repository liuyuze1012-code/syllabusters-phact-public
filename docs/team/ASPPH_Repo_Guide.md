# PHACT Hackathon: File-by-File Guide to the ASPPH Folder

Source: `github.com/12turnbullb/us-breaking-barriers-2026` → `ASPPH/` folder
Event: AWS Breaking Barriers 2026, Washington DC, Nov 3–5 · Team 31 (one of 6 ASPPH teams)

Each file has a **Value** rating for our MVP:
- 🔴 **Critical:** read it before kickoff
- 🟡 **Useful:** skim it, or have the AI read it
- ⚪ **Low:** skip it unless you have spare time

---

## 0. The map (read this first)

```
ASPPH/
├── Vision Document          🔴  WHY: problem, users, success criteria
├── Technical Document       🔴  HOW: AWS stack + known traps
├── PHACT/
│   ├── User Stories         🔴  WHAT: the 18-feature to-do list (MUST/SHOULD/COULD/STRETCH)
│   ├── Appendix A Press     🟡  Pitch material: ASPPH's own words, goals, numbers
│   └── Appendix B Diagram   🟡  The long-term architecture (bigger than the MVP!)
├── PHACT UX-UI Design/      🔴  7-screen wireframe; this is the Design target
├── Data/                        The library the AI reads and cites
│   ├── CEPH competencies    🔴  THE 22 accreditation competencies (core of the gap table)
│   ├── ASPPH Initiatives/
│   │   ├── AI Framework     🔴  Main source for AI recommendations
│   │   └── Workforce Center/  12 PDFs → "what employers expect" (3 are valuable)
│   ├── Other Competencies/  🟡  5 secondary frameworks (optional)
│   └── Approved Syllabi/    🔴  Test inputs: 1 real + 5 synthetic
└── ARIE Files/              🟡  How ASPPH's existing chatbot works (context only)
```

---

## 1. Core documents

### Vision Document 🔴
The business case: 150+ schools are each working out AI in their teaching on their own, and most faculty lack the confidence and resources to do it. It defines the MVP as one loop: **sign in → upload syllabus → cited recommendations → competency gap table → human approval → export**. It also lists what is out of scope and ends with 4 **Open Questions**. Those questions are where teams can make their own product decisions.

### Technical Document 🔴
The prescribed stack:

| Layer | What's required |
|---|---|
| Frontend | React on Amplify |
| Backend | Python FastAPI on Lambda, behind API Gateway |
| Sign-in | Cognito |
| AI | Claude on Bedrock; Strands agents on AgentCore |
| Knowledge base | Bedrock Knowledge Base over S3 Vectors |
| Safety | Comprehend for PII, Guardrails |
| Infrastructure-as-code | CDK in TypeScript |

The most valuable section is **"Implementation Notes and Known Gotchas,"** a list of traps someone has already hit. Give it to whichever engineer builds the backend.

---

## 2. `PHACT/` folder

### User Stories 🔴 (the most important planning file)
There are 18 stories grouped into 9 "epics" (feature areas). Each story has acceptance criteria, meaning concrete checks for "done."

| Priority | Stories |
|---|---|
| **MUST** (10) | US-1 Sign-in · US-3 Load sources · US-4 Sync KB · US-9 Citations · US-5 Upload syllabus · US-6 AI recommendations · US-7 Competency mapping · US-8 Guardrails · US-10 Review/approve · US-11 Export · US-13 Deploy |
| **SHOULD** | US-2 Role-based views · US-14 Generate course materials · US-15 Related resources · US-12 Logging |
| **COULD** | US-18 Admin source management · US-16 Community sharing (a UI-only mockup is fine) |
| **STRETCH** | US-17 AI sandbox |

**Details that are easy to miss:**
- **US-6:** Recommendations can suggest **AI-resistant assessments** (oral exams, handwritten work), not only ways to *add* AI. That's a more nuanced and credible take, and most teams will miss it.
- **US-7:** The competency table must also show **workforce expectations** (what employers want). It is also meant to be a *reusable* capability, not tied to one screen.
- **US-9:** Clicking a citation must open the source or excerpt, and evidence must be visually separated from AI synthesis.
- **US-11:** Exports keep source attribution and approval status. Sharing is opt-in.

**⚠️ The documents contradict each other.** Raise these with the ASPPH reps or your team lead on Day 1:

| Topic | User Stories say | Vision/Tech docs say |
|---|---|---|
| Guardrails | "on input **and output**," with Guardrail PII redaction | **Input only**; never attach to agent output; use Comprehend for PII |
| Async jobs | Step Functions | AgentCore through a worker Lambda |
| US-14 Generate materials | SHOULD | **Out of scope** (Phase 2) |
| US-2 Roles | SHOULD | MUST |
| Hosting/IaC | Amplify *or* S3+CloudFront; CDK, SAM *or* Terraform | Amplify + CDK |

*How to read this:* the Tech doc looks like it was written by someone who actually built it and hit the problems. **On technical conflicts, follow the Tech doc.** On priority conflicts, ask ASPPH.

### Appendix A: Press Release 🟡 (pitch goldmine)
A press release written as if PHACT launched in September 2026. Useful contents:
- **Pilot goals:**
  - 10–20 faculty champions at 5–10 schools
  - 10–15 courses adapted
  - 10+ AI learning modules
  - 250+ students reached
- **Scale:** 150+ schools, and **103,000+** deans, faculty, staff and students
- **Key phrase:** AI should *"support, not replace, faculty expertise"* (human in the loop)
- **It explicitly promises "visual heatmaps"** of competency coverage. This confirms the heatmap idea fits ASPPH's own vision.
- **Quoted:** the ASPPH CEO, and the **Dean of GMU's College of Public Health**. Many participants on the 6 ASPPH teams are GMU students, so expect GMU interest in the room.

### Appendix B: Architecture Diagram 🟡
One picture of the **full long-term platform**. It shows:
- users and the app layer
- Cognito and IAM
- AI orchestration (Bedrock, AgentCore, Lambda, Step Functions, Guardrails)
- the RAG/knowledge layer (S3 Vectors)
- 8 source types
- outputs → human review → approved
- cross-cutting services (CloudWatch, CloudTrail, Backup, WAF, VPC, Secrets Manager)

⚠️ **It is bigger than the MVP.** It includes a SageMaker sandbox, which the Tech doc *disallows*, plus WAF, VPC and Backup, which are deferred. Use it in the pitch for a "here's where this goes" slide. Don't try to build all of it.

---

## 3. `PHACT UX-UI Design/` 🔴

One very wide image containing **7 grayscale wireframes**. The faculty persona is "Dr. Elena Marchetti."

| # | Screen | What's on it |
|---|---|---|
| 1 | **Login** | Split layout (image on the left, form on the right), MyASPPH branding |
| 2 | **Home Dashboard** | Welcome message, "Transform Your Syllabus" call to action, stat cards (syllabi, competencies mapped, activity), recent uploads, saved recommendations, tiles for AI Tools / Resources / Community |
| 3 | **Syllabus Upload** | Drag-and-drop (PDF/DOCX/TXT, 25 MB max), progress bar, "Process Syllabus" button, side panel showing the analysis steps (Parse → Map → Generate) and a "Quality Guardrails" note |
| 4 | **AI Recommendations** | Course header, **Guardrails Compliance** box (Ethical AI Use, Bias Mitigation, ASPPH Alignment), summary counts, filter chips (Teaching Methods / Assessment Tools / Content Enhancement), expandable cards each with Recommendation, Implementation Approach, **Rationale (ASPPH Sources)** and Guardrail Status |
| 5 | **Competency Mapping Insights** | Coverage %, foundational vs. concentration counts, **coverage heatmap matrix** (F01–F12, C01–C08, colored High/Med/Low/Not Covered), competency detail rows (syllabus section, alignment strength, framework citation, AI suggestion), Gaps Analysis, Guardrails Verification checklist |
| 6 | **Review & Approve** | Original syllabus (left) next to proposed changes grouped by section (right), checkboxes, notes, version history, "Request Revisions" / "Approve All" |
| 7 | **Export & Share** | PDF, Word, **JSON for learning-management systems (LMS)** and CSV downloads; shareable link; email colleagues; "Add to Repository"; feedback stars |

**Observations:**
- These are **wireframes** (gray boxes, no colors or branding). Turning them into a polished ASPPH-branded interface is a clear way to win Design points.
- The heatmap in the mockup uses generic labels (F01–F12). The real CEPH framework has **22** foundational competencies in 8 groups. Building it with the real 22 is more accurate than the mockup.
- The Review screen's **original-next-to-proposed** layout is already the "tracked changes" idea. Doing it well is high value.

---

## 4. `Data/`: the knowledge library

### 4a. `CEPH competency guidelines.pdf` 🔴 (4 pages)
**The 22 MPH Foundational Competencies**, grouped into 8 domains:

| # | Domain |
|---|---|
| 1–4 | Evidence-based Approaches |
| 5–6 | Public Health & Health Care Systems |
| 7–11 | Planning & Management |
| 12–15 | Policy |
| 16–17 | Leadership |
| 18–20 | Communication |
| 21 | Interprofessional Practice |
| 22 | Systems Thinking |

**The hidden gem:** each competency comes with an "interpretation" that says what does *not* count as evidence. For example, role-play doesn't satisfy #21, an essay alone doesn't satisfy #16, and a logic model doesn't satisfy #22. Building these rules into the AI lets PHACT say *"your assignment doesn't meet CEPH's evidence bar,"* not just "this mentions leadership." That makes the gap analysis credible to accreditation experts.

*Build tip:* the PDF is a two-column table that extracts messily. Type the 22 items into a small JSON file by hand.

### 4b. `ASPPH Initiatives/ASPPH AI Framework.pdf` 🔴 (11 pages, 22 MB)
ASPPH's June 2026 AI strategy. It is **the main citable source for AI recommendations**. It covers 4 focus areas: Education; Teaching & Learning; Practice & Research; Policy/Regulatory.

Recommendations from it that PHACT should *apply*:
- Faculty choose an AI-use mode: **full ban, restricted, or transparent collaborative use**. PHACT could ask which one the professor wants.
- Pair AI tool exposure with **critical reflection on its limits**.
- Embed data literacy, machine-learning fundamentals, digital ethics and prompt engineering.
- Use capstones to show applied AI skills.
- Run a **"Missing Voices"** analysis of datasets (bias).
- Treat AI as **decision support, not a decision-maker**.
- Align with the NIST, WHO, OECD and ISO 42001 standards.

**Pitch angle:** an AWS staff member (Abdul Shaikh) sits on the task force that wrote it.
*Build tip:* extract the text once; don't feed the 22 MB file to the model repeatedly.

### 4c. `ASPPH Initiatives/Center for Public Health Workforce Development/` (12 PDFs)
**This is the source for the "workforce expectations" column.** None of these files mention AI directly; they cover data science, leadership and job skills.

| File | Value | Why |
|---|---|---|
| **Workforce Development/Competency Mapping.pdf** (32 pages) | 🔴 | 10 leadership skill themes (Data-Informed Decision Making, Change Management, Equity, etc.) mapped to CEPH and other standards. **Backbone of the workforce column.** Tables extract badly, so rebuild them by hand. |
| **Partnerships/Shared Vision & Unified Strategy 2024** (48 pages) | 🟡 | Best statistics: **100% of schools place students with health departments, but only 46% co-develop curriculum with them** |
| **Workforce Development/Public Health Leadership Report 2025** (26 pages) | 🟡 | **Only 44 of 5,158 programs focus on leadership**; teaching recommendations (simulations, case studies) |
| Applied Practice/Applied Learning and Training | 🟡 | Fellowships and practicums; 2,100+ CDC fellows since 1982 |
| Continuing Education/CDI information | ⚪ | 6 disease-intervention job domains (for epidemiology courses) |
| Continuing Education/Credentialing & CE | ⚪ | Names "data science" as an emerging skill |
| Workforce Research/GovernmentalPublicHealth-Factsheet | ⚪ | Says job analyses help schools align teaching |
| Workforce Research/Workforce Research (web page) | ⚪ | Points to an AJPH 2024 paper on aligning education with workforce demand. That paper is worth finding. |
| Continuing Education/Disease Intervention | ⚪ | Duplicates the CDI file |
| Partnerships/Academic and Practice Partnerships | ⚪ | List of links |
| Workforce Development/Workforce Development (web page) | ⚪ | Duplicates the reports |
| Workforce Research/DI_JTA_fact_sheet | ⚪ | **Image only, no text.** It would be indexed as empty unless run through OCR (text recognition) |

**Best pitch statistics from this folder:**
1. Only **46%** of schools co-develop curriculum with health departments, yet **100%** send students to them. *(Shared Vision 2024)*
2. **1 in 3** government public health leaders left their jobs in 2020–21. *(Competency Mapping)*
3. Only **~14%** of the public health workforce has a formal public health degree. *(Competency Mapping)*
4. ASPPH members: **80,000+ students, 10,000+ faculty and staff**. *(Shared Vision 2024)*

### 4d. `Other Competencies/` 🟡 (optional secondary frameworks)
| File | What it is | Use? |
|---|---|---|
| CPH exam competencies.pdf | National public health certification exam: 10 weighted domains (Data & Informatics 12%, Communication 12%, …) | **Best secondary framework**; Domain 1 is a natural hook for AI |
| SOPHE and CHES competencies.pdf | Health education specialist standards: 8 areas, ~160 sub-competencies | Optional. ⚠️ No-reproduction notice, so cite by number and paraphrase |
| CHW competencies.pdf | Texas community health worker skills (8 groups, unnumbered) | Low priority |
| CDI competencies.webp | Pie chart of 6 disease-intervention exam domains | Image only, minor |
| LSS program management principles.png | Lean Six Sigma marketing infographic | **Skip.** Not authoritative |

### 4e. `Approved Syllabi/` 🔴 (the test inputs)

**PHC6149 Public Health Leadership (real, University of Florida, 12 pages)**
- **Best primary demo input.** It is real, which is credible to judges, and it lists its own CEPH claims (#10, #16, #17), so PHACT can *check* them.
- It has **no AI policy** (only one reading mentions AI), so the recommendations have obvious value.
- Its assignments include a negotiation role-play, which CEPH says doesn't count as interprofessional practice (#21). That's a ready-made gap to show.
- Messy tables and a points inconsistency (30 vs. 35 quiz points) let you show robustness.
- ⚠️ It contains a **real instructor's contact info**. Good for the redaction demo, but blur it in any public video or repo.

**5 synthetic syllabi (Word files, about 800 words each)**

| File | Course |
|---|---|
| 01 Northeast | EPID 601 Applied Epidemiologic Methods (no CEPH list) |
| 02 Southeast | PHPM 612 Program Planning & Evaluation |
| 03 Midwest | PUBH 540 Environmental/Occupational Risk Assessment |
| 04 Southwest | HPM 635 Health Policy & Rural Health |
| 05 West Pacific | BIOS 622 Applied Biostatistics & Data Visualization (**best backup demo**) |

- They are cleanly templated: numbered outcomes, a grading table, a weekly schedule and an AI-use policy.
- Some list **outdated or paraphrased CEPH wording**. A good mapper should match those to the current 22 and flag the ones that no longer exist. That's a nice "smart" moment.
- **Five syllabi from different schools are exactly the input for a program-wide heatmap demo.**

**⚠️ There is no student PII in any file.** The success criteria require showing a *student* name or email being redacted, so **we must plant one ourselves** (e.g., add "Contact TA Jane Doe, jane.doe@student.example.edu" to a synthetic syllabus).

---

## 5. `ARIE Files (for Context)/` 🟡

ARIE (AI Resource for Institutional Excellence) is ASPPH's **existing** chatbot, built with AWS.

| File | Contents |
|---|---|
| Arie-Chatbot-Technical-Explanation.pdf (2 pages) | Plain-English walkthrough: API Gateway → Lambda → Knowledge Base → OpenSearch → Bedrock (Claude Sonnet 3.7) → a **"Supervisor" AI that double-checks answers** before sending them → cited answer |
| AI+ARIE+ Solution Architecture.pdf | Diagram: Bedrock Agent + Knowledge Base + IDEA Institute Resource Hub |
| AI+ARIE+Data+Flow+Diagram.pdf | How member chats flow through resource storage |
| ARIE AI+Lifecycle.pdf | Maintenance and update cycle |

**Why it matters:**
1. ASPPH already trusts this pattern (knowledge base plus citations plus Claude), so PHACT should *feel familiar*.
2. **The "Supervisor" idea is reusable.** A second AI pass that checks each recommendation ("does this citation actually support the claim?") would directly power the mockup's "Guardrails Verification" checklist. It would also be a credible extra over other teams.

---

## 6. Takeaways for Team 31

1. **Build order:** follow the 10 MUST stories. Use the Tech doc's "Gotchas" as the engineers' checklist.
2. **Demo input:** PHC6149 (real) as the main demo, BIOS 622 as backup. Plant a fake student email for the PII demo.
3. **Where to stand out:**
   - CEPH "evidence bar" rules make the gap analysis credible.
   - The AI Framework's ban/restricted/collaborative choice plus AI-resistant assessments make the recommendations more nuanced.
   - A real 22-competency heatmap (ASPPH's press release promises one).
   - A side-by-side "tracked changes" review screen.
   - A Supervisor-style verification pass.
4. **Pitch:** the press release numbers (103K community, pilot goals), the workforce statistics, and the human-in-the-loop framing.
5. **Ask on Day 1:**
   - Which side wins on the guardrail and Step Functions conflicts?
   - Is US-14 in or out?
   - What exactly is the "point system"?
   - Is the "sample workforce data ASPPH is preparing" coming?
