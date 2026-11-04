# Frontend: React on Amplify

**Owner: frontend track.** Everything here is a **placeholder**: the file layout and the screen list are fixed, but the design and implementation belong to the frontend teammate. Layout follows ASPPH's wireframe ([../docs/challenge/ux-mockup.jpg](../docs/challenge/ux-mockup.jpg)); the visual style is ours.

## Run it

```bash
cd frontend
cp .env.example .env.local        # VITE_USE_MOCKS=1 → no backend needed
npm install
npm run dev                       # http://localhost:5173
```

With `VITE_USE_MOCKS=1`, `src/api/client.ts` returns `src/mocks/analyze_response.json`, the same sample result the backend's mock agent returns. Build the screens against it from hour 1. Set `VITE_USE_MOCKS=0` to call the local backend (proxied to `:8000`).

## Files

| File | What it does | Status |
|---|---|---|
| `package.json` | React 18, Vite, Amplify, React Query, React Router | placeholder deps |
| `index.html` | Page shell that mounts the app | ready |
| `vite.config.ts` | Dev server; proxies `/api` and `/health` to the backend | ready |
| `tsconfig.json` | TypeScript settings | ready |
| `.env.example` | Mock switch, API URL, Cognito ids | ready |
| `src/main.tsx` | Mounts the app; configure Amplify Auth here | Amplify TODO |
| `src/App.tsx` | Routes for every screen | ready |
| `src/api/client.ts` | **The only file that calls the backend**; mock switch | most endpoints TODO |
| `src/mocks/analyze_response.json` | Copy of `shared/fixtures/analyze_response.json` | ready |
| `src/pages/Login.tsx` | Step 1: sign in | placeholder |
| `src/pages/Home.tsx` | Step 2: courses, history, profile | placeholder |
| `src/pages/NewCourse.tsx` | Step 3: create a course | placeholder |
| `src/pages/Upload.tsx` | Step 4: upload and confirm extracted text | placeholder |
| `src/pages/SetChecks.tsx` | Steps 5–6: preferences, competencies, AI target, assessment types | placeholder |
| `src/pages/AnalysisReport.tsx` | Steps 7–8: progress, heatmap, AI rating, edits list | placeholder |
| `src/pages/EditStudio.tsx` | Steps 9–11: tracked changes, accept/reject, chat and manual edit | placeholder |
| `src/pages/Export.tsx` | Step 12: download DOCX, save version | placeholder |
| `src/pages/SchoolConsole.tsx` | University admin (stretch) | placeholder |
| `src/pages/ReviewConsole.tsx` | ASPPH reviewer (stretch) | placeholder |
| `src/components/Heatmap.tsx` | The 22-competency grid | placeholder |
| `src/components/EditCard.tsx` | One edit: evidence kept apart from the AI suggestion | placeholder |
| `src/components/CitationChip.tsx` | Source chip that opens the original PDF | placeholder |
| `src/components/TrackedChanges.tsx` | Renders insertions and deletions | placeholder |
| `src/components/JobProgress.tsx` | Polls the job every 3 s | placeholder |

## Rules
- Heatmap colors come from `status` in the data, never from AI text.
- Show evidence (from sources) and rationale (AI suggestion) as visibly different things (US-9).
- If `shared/fixtures/analyze_response.json` changes, copy it to `src/mocks/` again.
