// src/api/baseURL.js
export const IS_FILE = window.location.protocol === "file:";

// manager jar(8080), auth(8082) 너 환경 기준
export const API_ORIGIN = IS_FILE ? "http://127.0.0.1:8080" : "";
export const AUTH_ORIGIN = IS_FILE ? "http://127.0.0.1:8082" : "";

// "/api/..." 형태를 안전하게 절대/상대 둘 다로 만들어줌
export function apiUrl(path) {
  if (!path) return path;
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/")) path = "/" + path;
  return API_ORIGIN + path;
}
