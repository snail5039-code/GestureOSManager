// src/runtime/endpoints.js

function isPackagedProtocol() {
  if (typeof window === "undefined") return false;
  const p = window.location.protocol;
  return p === "file:" || p === "app:" || p === "gestureos:";
}

export function isPackaged() {
  return isPackagedProtocol();
}

// ✅ 네 curl 결과 기준:
// - control/status, hud/show, ai/chat, pairing => 8080 ( /api/* )
// - login/bridge/auth                           => 8082 ( /api/* )
const ORIGIN_CONTROL = "http://127.0.0.1:8080";
const ORIGIN_AI = "http://127.0.0.1:8080";
const ORIGIN_PAIRING = "http://127.0.0.1:8080";
const ORIGIN_AUTH = "http://127.0.0.1:8082";

/** -------------------------
 * axios baseURL (항상 /api 포함)
 * ------------------------- */
export function controlApiBaseURL() {
  return isPackagedProtocol() ? `${ORIGIN_CONTROL}/api` : "/api";
}
export function aiApiBaseURL() {
  return isPackagedProtocol() ? `${ORIGIN_AI}/api` : "/api";
}
export function pairingApiBaseURL() {
  return isPackagedProtocol() ? `${ORIGIN_PAIRING}/api` : "/api";
}
export function authApiBaseURL() {
  return isPackagedProtocol() ? `${ORIGIN_AUTH}/api` : "/api";
}

/** -------------------------
 * fetch용 절대 URL 생성기
 * - file://에서 fetch("/api/...") => C:\api\...로 깨지는 문제 방지
 * - /api/api 중복 방지
 * ------------------------- */
function normalizeApiPath(path) {
  let p = String(path || "");
  if (!p) return "/api";
  if (/^https?:\/\//i.test(p)) return p;

  if (!p.startsWith("/")) p = "/" + p;

  // /api/api 중복 제거
  p = p.replace(/^\/api\/+api\/+/, "/api/");

  // /api 없으면 붙이기
  if (!/^\/api(\/|$)/i.test(p)) p = "/api" + p;

  // 다시 한 번 중복 제거
  p = p.replace(/^\/api\/+api\/+/, "/api/");
  return p;
}

function makeUrl(base, path) {
  const apiPath = normalizeApiPath(path);

  // dev/prod(프록시)에서는 상대경로 유지
  if (base === "/api") {
    return apiPath.replace(/^\/api\/+api\/+/, "/api/");
  }

  // baseURL은 http://127.0.0.1:8080/api 형태
  const b = String(base || "").replace(/\/+$/, "");

  // base가 .../api 로 끝나면 /api 중복 제거
  if (b.endsWith("/api") && apiPath.startsWith("/api/")) {
    return b + apiPath.slice(4);
  }
  return b + apiPath;
}

export function controlApiUrl(path = "") {
  return makeUrl(controlApiBaseURL(), path);
}
export function aiApiUrl(path = "") {
  return makeUrl(aiApiBaseURL(), path);
}
export function pairingApiUrl(path = "") {
  return makeUrl(pairingApiBaseURL(), path);
}
export function authApiUrl(path = "") {
  return makeUrl(authApiBaseURL(), path);
}

/** -------------------------
 * WS (agent)
 * - 설치본에서는 8080 ws로 고정
 * ------------------------- */
export function wsUrl(path = "/ws/agent") {
  const p = String(path || "/ws/agent");
  const fixed = p.startsWith("/") ? p : `/${p}`;
  if (isPackagedProtocol()) return `ws://127.0.0.1:8080${fixed}`;
  return fixed;
}

/** (레거시 호환: 기존 코드가 apiBaseURL / apiUrl을 쓰는 경우 대비) */
export function apiBaseURL() {
  return controlApiBaseURL();
}
export function apiUrl(path = "") {
  return controlApiUrl(path);
}
