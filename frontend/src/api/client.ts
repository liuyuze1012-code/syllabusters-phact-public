// The only place that talks to the backend. With VITE_USE_MOCKS=1 it returns src/mocks/*.json,
// so screens can be built before the backend exists. Endpoints match docs/contracts.md.
import analysisMock from '../mocks/analyze_response.json';

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === '1';
const BASE = import.meta.env.VITE_API_URL ?? '';

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  // TODO: add the Cognito ID token: Authorization: Bearer <token> (fetchAuthSession from aws-amplify)
  const r = await fetch(`${BASE}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => call<{ ok: boolean; agent_mode: string }>('/health'),
  getAnalysis: async (id: string) => (USE_MOCKS ? analysisMock : call(`/api/analyses/${id}`)),
  // TODO: me, listCourses, createCourse, uploadUrl, registerSyllabus, saveSettings,
  //       startJob, getJob (poll every 3 s), decideEdit, exportDocx, school*, review*
};
