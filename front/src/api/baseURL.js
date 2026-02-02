// src/api/baseURL.js
// 로컬 설치본 전용(하드코딩):
// - 기본 기능 API: 8080
// - 인증/회원: 8082

export const MANAGER_ORIGIN = "http://localhost:8080";
export const WEB_ORIGIN = "http://localhost:8082";

function isAbsoluteUrl(s) {
  return /^https?:\/\//i.test(String(s || ""));
}

// "/api/..." 또는 "/control/..." 등 어떤 형태든 안전하게 절대 URL로 변환
export function apiUrl(path) {
  if (!path) return path;
  if (isAbsoluteUrl(path)) return path;
  let p = String(path);
  if (!p.startsWith("/")) p = "/" + p;
  return MANAGER_ORIGIN + p;
}

export function webUrl(path) {
  if (!path) return path;
  if (isAbsoluteUrl(path)) return path;
  let p = String(path);
  if (!p.startsWith("/")) p = "/" + p;
  return WEB_ORIGIN + p;
}
