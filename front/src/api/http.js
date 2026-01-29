// src/api/http.js
// - Vite dev: proxy 사용(상대경로)
// - Prod(설치본): 8082(auth) / 8080(agent)로 직접 붙임

const DEV = (() => {
  try { return import.meta.env.DEV; } catch { return false; }
})();

const AUTH_BASE = (() => {
  if (DEV) return ""; // dev는 proxy로 /api/auth... 그대로
  return (import.meta.env.VITE_AUTH_API_BASE || "http://127.0.0.1:8082");
})();

const AGENT_BASE = (() => {
  if (DEV) return ""; // dev는 proxy로 /api/... 그대로
  return (import.meta.env.VITE_AGENT_API_BASE || "http://127.0.0.1:8080");
})();

function pickBase(urlPath) {
  // urlPath는 "/api/..." 같은 형태로 들어온다고 가정
  if (urlPath.startsWith("/api/auth/") || urlPath.startsWith("/api/members/")) return AUTH_BASE;
  // 나머지 /api/*, /motion/* 는 agent
  return AGENT_BASE;
}

export async function apiFetch(url, options) {
  const u = String(url || "");
  const base = u.startsWith("/api/") || u.startsWith("/motion/") ? pickBase(u) : "";
  const full = base ? `${base}${u}` : u;
  return fetch(full, options);
}
