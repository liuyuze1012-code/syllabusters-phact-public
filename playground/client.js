// Shared by the professor app and the admin console.
// 1. On AWS, API Gateway checks a Cognito ID token on every /api call: we keep it in this tab's sessionStorage
//    (cleared when the tab closes) and attach it as `Authorization: Bearer …`. Locally the cookie is used instead.
// 2. Calls that can outlast API Gateway's ~30 s (analyses, chat, PDF reading, publishing) run as async jobs:
//    POST /api/jobs → poll GET /api/jobs/{id} until DONE. The page code just awaits the result as before.
window.PHACT = (() => {
  // Sign-in lasts 1 hour (the Cognito ID token's own lifetime). After that the page signs out and asks again.
  const HOUR = 3600 * 1000;
  let token = null, exp = 0;
  try { token = sessionStorage.getItem("phact_token"); exp = +sessionStorage.getItem("phact_exp") || 0; } catch {}
  if (token && Date.now() > exp) { token = null; try { sessionStorage.removeItem("phact_token"); sessionStorage.setItem("phact_ended", "1"); } catch {} }
  const P = {jobs: false, authMode: "cookie"};
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (url, opts = {}) => {
    if (token && typeof url === "string" && url.startsWith("/api/")) {
      opts = {...opts, headers: {...(opts.headers || {}), Authorization: "Bearer " + token}};
    }
    return nativeFetch(url, opts);
  };
  P.setToken = t => {
    token = t || null; exp = t ? Date.now() + HOUR : 0;
    try { if (t) { sessionStorage.setItem("phact_token", t); sessionStorage.setItem("phact_exp", String(exp)); } else { sessionStorage.removeItem("phact_token"); sessionStorage.removeItem("phact_exp"); } } catch {}
  };
  // a signed-in tab signs itself out when the hour is up, then reloads to the sign-in screen
  setInterval(() => { if (token && Date.now() > exp) { P.setToken(null); try { sessionStorage.setItem("phact_ended", "1"); } catch {} location.reload(); } }, 30000);
  P.sessionEnded = () => { try { const e = sessionStorage.getItem("phact_ended"); sessionStorage.removeItem("phact_ended"); return !!e; } catch { return false; } };
  P.hasToken = () => !!token;
  const LONG = ["/api/extract", "/api/structure", "/api/analyze", "/api/analyze_more", "/api/chat", "/api/classify",
                "/api/assessment/structure", "/api/assessment/analyze", "/api/uni/policy/extract"];
  P.isLong = path => LONG.includes(path) || /^\/api\/admin\/(sources\/(preview|publish|[^/]+\/status)|submissions\/[^/]+\/approve)$/.test(path);
  P.fileToB64 = file => new Promise((ok, bad) => {
    const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.onerror = bad; r.readAsDataURL(file);
  });
  P.runJob = async (path, body, file, method = "POST") => {
    const payload = {path, body: method !== "POST" ? {...(body || {}), _method: method} : body, file};
    const start = await nativeFetch("/api/jobs", {method: "POST", headers: {"Content-Type": "application/json", ...(token ? {Authorization: "Bearer " + token} : {})}, body: JSON.stringify(payload)});
    const j = await start.json().catch(() => ({}));
    if (!start.ok) throw new Error(j.detail || start.statusText);
    const t0 = Date.now();
    for (let wait = 1500; Date.now() - t0 < 15 * 60 * 1000; wait = Math.min(wait + 500, 4000)) {
      await new Promise(r => setTimeout(r, wait));
      const s = await nativeFetch(`/api/jobs/${j.job_id}`, {headers: token ? {Authorization: "Bearer " + token} : {}});
      const st = await s.json().catch(() => ({}));
      if (!s.ok) throw new Error(st.detail || s.statusText);
      if (st.status === "DONE") return st.result;
      if (st.status === "FAILED") throw new Error(st.error || "The job failed.");
    }
    throw new Error("This is taking longer than 15 minutes. Please try again.");
  };
  return P;
})();
