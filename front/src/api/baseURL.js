// src/api/baseURL.js
export const IS_FILE = window.location.protocol === "file:";

// ✅ 설치본(file://)에서는 로컬 서버로 직접 연결
// - Manager(JAR): 8080
// - Web(Spring):  8082
export const MANAGER_ORIGIN = IS_FILE ? "http://127.0.0.1:8080" : "";
export const WEB_ORIGIN = IS_FILE ? "http://127.0.0.1:8082" : "";

// "/api/..." 형태를 안전하게 절대/상대 둘 다로 만들어줌
export function apiUrl(path) {
  if (!path) return path;
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/")) path = "/" + path;
  return MANAGER_ORIGIN + path;
}

export function webUrl(path) {
  if (!path) return path;
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/")) path = "/" + path;
  return WEB_ORIGIN + path;
}
