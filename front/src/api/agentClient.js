// src/api/agentClient.js
import axios from "axios";

// ✅ Agent baseURL 결정 규칙
// - DEV(vite dev server): "/api" 또는 "/motion" 같은 상대 경로로 proxy 사용
// - PROD(설치본/빌드): http://127.0.0.1:8080 로 직결
const DEV_AGENT_BASE = ""; // dev에서는 상대경로 그대로 쓰기 위해 빈 문자열
const PROD_AGENT_ORIGIN = "http://127.0.0.1:8080";

function isDev() {
  try {
    return import.meta.env.DEV;
  } catch {
    return false;
  }
}

function getAgentOrigin() {
  if (isDev()) return DEV_AGENT_BASE;
  return import.meta?.env?.VITE_AGENT_API_BASE || PROD_AGENT_ORIGIN;
}

const origin = getAgentOrigin();

// ✅ /api/* 용
export const agentApi = axios.create({
  baseURL: origin, // dev: "" -> "/api/..." 그대로 / prod: "http://127.0.0.1:8080"
  timeout: 8000,
  headers: { Accept: "application/json" },
});

// ✅ /motion/* 용 (같은 8080이지만 경로 분리 편의)
export const motionApi = axios.create({
  baseURL: origin, // dev: "" -> "/motion/..." / prod: "http://127.0.0.1:8080"
  timeout: 8000,
  headers: { Accept: "application/json" },
});
