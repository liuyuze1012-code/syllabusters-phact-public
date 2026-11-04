# Data

The raw files ASPPH provided, sorted by how PHACT uses them. Cleaned versions for the knowledge base go in [`../knowledge-base/`](../knowledge-base/), not here.

## How each file is used

| File | Folder | Use | Tag (`source_type`) |
|---|---|---|---|
| CEPH competency guidelines | `reference/` | **Checklist:** typed into `ceph_competencies.json` and given to the AI in full every time. Not searched. | n/a |
| ASPPH AI Framework | `reference/ASPPH Initiatives/` | **Main evidence** for every AI recommendation | `guidance` |
| Competency Mapping | `reference/ASPPH Initiatives/…/Workforce Development/` | **Workforce expectations** for each gap (US-7) | `workforce` |
| Public Health Leadership Report 2025 | same folder | Leadership skill gaps, teaching methods | `workforce` |
| Shared Vision & Unified Strategy 2024 | `…/Partnerships/` | School–practice links, statistics | `guidance` |
| CPH exam competencies | `reference/Other Competencies/` | Optional second framework | `guidance` |
| Applied Learning and Training page | `…/Applied Practice/` | Optional: practice-based assignments | `guidance` |
| GovernmentalPublicHealth fact sheet | `…/Workforce Research/` | Pitch statistics only | n/a |
| SOPHE and CHES competencies | `reference/Other Competencies/` | **Cite by number only.** It has a no-reproduction notice. | n/a |
| LSS infographic, DI_JTA fact sheet, CDI, CHW, saved web pages | various | **Not loaded:** marketing, image-only, low relevance, or duplicates | n/a |

## Test syllabi (never cited)

| File | Role |
|---|---|
| `test-syllabi/PHC6149-…pdf` | *Not in the public repo* (a real syllabus with an instructor's contact details). We tested on it privately. |
| `test-syllabi/Synthetic/MPH_Syllabus_05_West_Pacific.docx` | Backup demo (Biostatistics) |
| `test-syllabi/Synthetic/MPH_Syllabus_01–04` | Testing, and the program-wide heatmap |

**To do:** no file has a student's name or email. Add a fake one (e.g. a TA line with `jane.doe@student.example.edu`) to one synthetic syllabus so the redaction demo works.

## Rules

- Test syllabi must never be loaded into the knowledge base. If the AI has seen a test input, testing it proves nothing.
- AI claims must cite the AI Framework. The workforce files never mention AI, so they can back skill and job claims only.
- Keep ASPPH's exact wording when cleaning files, because the chunk text becomes the citation snippet.
