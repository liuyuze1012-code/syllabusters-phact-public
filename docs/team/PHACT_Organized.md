# PHACT: All Hackathon Info, Organized

The categories, in the order you'd use them:
1. **Client requirements:** what ASPPH wants built, and what's off-limits
2. **Reference data:** what the AI reads and cites
3. **Test inputs:** what we upload to test it (this is *not* reference data)
4. **Extra info:** background, pitch material, logistics
5. **Requirements → prompt rules:** how 1 + 2 turn into the AI's instructions

---

## 1. Client requirements

### 1a. The 10 MUST features (from the User Stories)
Each is "done" when its check passes.

| # | Feature | Done when… |
|---|---|---|
| US-1 | Sign in | Login uses Cognito; logged-out users go to the login page; 2 roles: faculty and admin |
| US-3 | Load sources | 3 or more source types are stored in encrypted storage, each tagged with metadata |
| US-4 | Sync knowledge base | A test search returns relevant passages, each with its source document |
| US-5 | Upload syllabus | PDF, DOCX or pasted text are accepted; the file stays private; the extracted text is shown back to the user |
| US-6 | AI recommendations | Each recommendation names a **specific** module, assignment or objective and cites **at least one** ASPPH source; it may suggest AI-*resistant* assessments; results return in under ~60 seconds |
| US-7 | Competency mapping | A table of objective → CEPH competency → gap, citing CEPH, plus **workforce expectations** |
| US-8 | Guardrails | A student name or email is shown redacted; an off-topic prompt is blocked with a friendly message |
| US-9 | Citations | Each citation shows a title and a snippet, and clicking opens the source. **Evidence is visibly separated from AI opinion.** |
| US-10 | Review and approve | Output can be edited; its status moves from Draft to Approved or Rejected, with user and time recorded |
| US-11 | Export | DOCX or PDF export, **approved items only**, with sources kept |
| US-13 | Deploy | Reachable at one URL; built as infrastructure-as-code (code that sets up the AWS resources) |

**SHOULD** (only once the MUSTs work): US-2 role-based views · US-14 generate course materials · US-15 related resources · US-12 logging
**COULD / STRETCH** (a mockup is fine): US-16 community sharing · US-18 admin source management · US-17 AI sandbox

### 1b. Non-negotiable rules
- **Personal data** (names, emails) is removed *before* text reaches the AI and never appears in logs.
- **A human approves** everything before it is exported or shared.
- **Only synthetic or public data** is used.
- **Prescribed stack:**

  | Part | Technology |
  |---|---|
  | Website | React on Amplify |
  | Backend | Python FastAPI on Lambda |
  | Sign-in | Cognito |
  | AI | Claude on Bedrock + AgentCore |
  | Knowledge base | S3 Vectors |
  | Infrastructure-as-code | CDK |

- **Long AI work runs in the background**, because a web request times out after 29 seconds.
- **The code goes in a public GitHub repo** before judging.
- **Spending is capped at $500** per sandbox.

### 1c. The look (UX mockup)
There are 7 screens in this order: Login → Dashboard → Upload → **Recommendations** → **Competency heatmap** → **Review side-by-side** → Export.
The layout is set; the visual style is ours to choose. The three bolded screens decide most of the Design score.

### 1d. Unresolved conflicts: ask on Day 1
| Topic | User Stories | Tech doc | Our default |
|---|---|---|---|
| Guardrail placement | On input and output | Input only | Tech doc |
| Background jobs | Step Functions | AgentCore + worker Lambda | Tech doc |
| US-14 generate materials | SHOULD | Out of scope | Skip unless ASPPH asks |
| Workforce data | "ASPPH is preparing" | Not in the repo | Ask; fall back to the Competency Mapping report |


---

## 2. Reference data (what the AI reads and cites)

Sources split by **how** the AI uses them.

### 2a. Checklist: given to the AI in full, every time
| Source | Why it's not in the search index |
|---|---|
| **CEPH 22 competencies** + their "doesn't count as evidence" rules | Every syllabus must be checked against **all 22**. A search would return only the top few. Typed up by hand as a clean list. |

### 2b. Library: in the vector database, searched as needed
| Source | What it's allowed to back up |
|---|---|
| **ASPPH AI Framework** ⭐ | **All AI-integration recommendations** (the primary citation) |
| **Competency Mapping report** ⭐ | Workforce expectations: 10 leadership skill areas |
| Shared Vision 2024 | Linking schools with real practice; statistics |
| Leadership Report 2025 | Leadership skill gaps; teaching methods (simulations, case studies) |
| CPH exam competencies (optional) | A second framework, especially data and informatics |
| Applied Learning page (optional) | Practice-based assignments |

### 2c. Excluded: don't load these
- LSS infographic (marketing, not a standard)
- DI_JTA fact sheet (image only, no readable text)
- Duplicate or saved web pages: Disease Intervention, Workforce Development page, Partnerships page
- SOPHE/CHES: cite by number only (it has a no-reproduction notice)
- CHW and CDI: optional, low relevance

### 2d. Citation honesty rule
**No workforce file mentions AI.** AI claims must cite the AI Framework. Workforce files can back skill and job claims only.

---

## 3. Test inputs (what we upload, never cited)

| File | Role |
|---|---|
| **PHC 6149 Leadership (real, University of Florida)** | **Main demo.** No AI policy; claims CEPH #10, #16 and #17 (PHACT can check them); a role-play is a ready-made gap for #21; messy tables; ⚠️ contains real instructor contact info, so blur it in public material |
| **Synthetic 05 Biostatistics** | Backup demo; clean; AI fits naturally |
| Synthetic 01–04 | Testing, plus the program-wide heatmap (5 "schools") |

**To-do:** add a fake student name and email to one synthetic syllabus. **No file has one**, and the redaction demo requires it.

---

## 4. Extra info

| Item | Use it for |
|---|---|
| Press release | **Pitch:** a 103K+ community; pilot goals (10–15 courses, 250+ students); "support, not replace, faculty"; promises "visual heatmaps" |
| Architecture diagram | A **"where this goes next"** pitch slide. It is bigger than the MVP, so don't build all of it. |
| ARIE files | ASPPH already trusts this pattern. **Reuse its "Supervisor" double-check idea.** |
| Workforce statistics | **Pitch:** 46% vs. 100% curriculum co-design; 1 in 3 leaders left; ~14% hold a public health degree |
| Other 11 nonprofits | Ignore |

---

## 5. Requirements → prompt rules

Each rule says what the AI must do and where the rule comes from.

### Recommendations (Screen 4)
1. **Be specific:** name the exact week, module, assignment or objective. *(US-6)*
2. **Cite at least one ASPPH source**, with a title and the exact snippet used. *(US-6, US-9)*
3. **Label each statement** as "Evidence from source" or "AI suggestion." *(US-9)*
4. **Respect the professor's AI-use level** (ban, restricted, or open with disclosure), asked up front. *(AI Framework)*
5. **Pair every AI-tool suggestion with a reflection activity** on the tool's limits. *(AI Framework)*
6. **Allow AI-resistant alternatives**, such as oral exams or handwritten work, where they fit better. *(US-6)*
7. **Don't break CEPH coverage.** Don't replace an assignment that provides evidence for a competency without saying so. *(CEPH)*
8. **Keep AI as decision support.** Never suggest AI make decisions on its own. *(AI Framework)*

### Competency mapping (Screen 5)
9. **Check all 22 CEPH competencies**, not just the obvious ones. *(CEPH)*
10. **Apply CEPH's evidence rules.** Mark a competency "covered" only if an *assessed assignment* meets the bar (e.g., a role-play does not count for #21). *(CEPH interpretations)*
11. **Verify the syllabus's own CEPH claims** and flag outdated competency wording. *(PHC 6149, synthetic syllabi)*
12. **Add a workforce expectation for each gap**, cited to the Competency Mapping report. *(US-7)*

### Safety and honesty (all screens)
13. **If no source supports a claim, say so.** Don't invent a citation. *(US-9)*
14. **Off-topic requests get a friendly refusal.** *(US-8)*
15. **Supervisor pass:** a second check confirms each citation actually supports its claim before the result is shown. *(ARIE pattern)*
