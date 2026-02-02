// front/src/runtime/endpoints.js
// ✅ 설치본(file://)에서도 API가 C:\api 같은 파일경로로 해석되지 않도록
//    "항상 절대 URL"로 만들어주는 유틸 + 포트 라우팅

function isPackagedProtocol() {
  if (typeof window === "undefined") return false;
  const p = window.location.protocol;
  // Electron: file: / app: / 커스텀 프로토콜(쓰는 경우) 대응
  return p === "file:" || p === "app:" || p === "gestureos:";
}

export function isPackaged() {
  return isPackagedProtocol();
}

// ---- Origins (설치본 기준 포트)
// ✅ 네 curl 결과 기준:
//   - /api/pairing  : 8080 에서 200
//   - /api/ai/*     : 8080
//   - /api/control/*: 8080
//   - /api/auth/*   : 8082 (웹 연동/브릿지 등)
const ORIGIN_CONTROL = "http://127.0.0.1:8080";
const ORIGIN_AI = "http://127.0.0.1:8080";
const ORIGIN_PAIRING = "http://127.0.0.1:8080";
const ORIGIN_AUTH = "http://127.0.0.1:8082";

// ---- BaseURL (axios용)
// ⚠️ baseURL에는 절대 /api 를 붙이지 말 것.
//    (요청 경로가 /api/... 를 이미 포함하거나, 일부 코드가 /api 를 붙여 호출할 수 있어서
//     /api/api 를 만들기 쉬움)
export function controlApiBaseURL() {
  // axios 전용 baseURL (기본 호출이 "/control/..." 형태라서 /api를 붙여줌)
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

// ---- URL helpers (fetch용: 항상 절대 URL 반환)
function normalizeApiPath(path) {
  let p = String(path || "");
  if (!p) return "/api";

  // 이미 풀 URL이면 그대로
  if (/^https?:\/\//i.test(p)) return p;

  // 앞에 / 정리
  if (!p.startsWith("/")) p = "/" + p;

  // /api/api/... 중복 제거
  p = p.replace(/^\/api\/+api\/+/, "/api/");

  // /api 가 없으면 붙임
  if (!/^\/api(\/|$)/i.test(p)) p = "/api" + p;

  // 한번 더 안전장치
  p = p.replace(/^\/api\/+api\/+/, "/api/");
  return p;
}

function makeUrl(origin, path) {
  const apiPath = normalizeApiPath(path);
  // dev/prod 웹(프록시)에서는 origin이 "/api"일 수 있으니 그때는 상대경로 유지
  if (origin === "/api") {
    // origin이 /api면 normalizeApiPath가 /api/...를 만들기 때문에 /api/api 방지로 한 번 정리
    return apiPath.replace(/^\/api\/+api\/+/, "/api/");
  }

  // ✅ origin이 이미 .../api 로 끝나고 apiPath가 /api/...이면 중복 제거
  const o = String(origin || "").replace(/\/+$/, "");
  if (o.endsWith("/api") && apiPath.startsWith("/api/")) {
    return o + apiPath.slice(4); // remove leading "/api"
  }
  return o + apiPath;
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


// --------------------
// Backward-compatible exports (extra)
// --------------------
export function controlOrigin() {
  // origin only (no /api)
  return isPackagedProtocol() ? ORIGIN_CONTROL : window.location.origin;
}
export function pairingOrigin() {
  return isPackagedProtocol() ? ORIGIN_PAIRING : window.location.origin;
}
export function aiOrigin() {
  return isPackagedProtocol() ? ORIGIN_AI : window.location.origin;
}
export function authOrigin() {
  return isPackagedProtocol() ? ORIGIN_AUTH : window.location.origin;
}

// ---- WS (agent)
export function wsUrl(path = "/ws/agent") {
  const p = String(path || "/ws/agent");
  const fixed = p.startsWith("/") ? p : `/${p}`;
  if (isPackagedProtocol()) return `ws://127.0.0.1:8080${fixed}`;
  return fixed;
}

// ---- 레거시 호환
export function apiBaseURL() {
  return controlApiBaseURL();
}

export function apiUrl(path = "") {
  return controlApiUrl(path);
}
