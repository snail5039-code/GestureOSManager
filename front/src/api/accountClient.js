// src/api/accountClient.js
import axios from "axios";

// ✅ baseURL 결정 규칙
// - DEV( vite dev server ): "/api" (proxy 사용)
// - PROD( 설치본/빌드 ): "http://127.0.0.1:8082/api" (직결)
// - file:// 로 열려도 PROD면 직결이 우선
const DEV_BASE = "/api";
const PROD_BASE = "http://127.0.0.1:8082/api";

function getBaseURL() {
  // Vite build-time flags
  const isDev = (() => {
    try { return import.meta.env.DEV; } catch { return false; }
  })();

  if (isDev) return DEV_BASE;

  // packaged/prod에서는 무조건 로컬 스프링으로 직결
  // (proxy가 없으니까)
  return PROD_BASE;
}

const baseURL = getBaseURL();

export const accountApi = axios.create({
  baseURL,
  withCredentials: true, // refreshToken 쿠키 사용
  timeout: 8000,
  headers: { Accept: "application/json" },
});

const refreshApi = axios.create({
  baseURL,
  withCredentials: true,
  timeout: 8000,
  headers: { Accept: "application/json" },
});

let refreshPromise = null;

export function attachAccountInterceptors({ getAccessToken, setAccessToken, onLogout }) {
  accountApi.interceptors.request.use((config) => {
    const t = getAccessToken?.();
    if (t) config.headers.Authorization = `Bearer ${t}`;
    return config;
  });

  accountApi.interceptors.response.use(
    (res) => res,
    async (err) => {
      const status = err?.response?.status;
      const cfg = err?.config;

      if (!cfg || status !== 401 || cfg._retry) return Promise.reject(err);
      cfg._retry = true;

      try {
        if (!refreshPromise) {
          refreshPromise = refreshApi
            .post("/auth/token", null) // baseURL이 .../api 이므로 "/auth/token"이면 최종 .../api/auth/token
            .then((r) => r?.data?.accessToken || null)
            .finally(() => {
              refreshPromise = null;
            });
        }

        const newToken = await refreshPromise;
        if (!newToken) throw new Error("NO_REFRESH_TOKEN");

        setAccessToken?.(newToken);
        cfg.headers = { ...(cfg.headers || {}), Authorization: `Bearer ${newToken}` };
        return accountApi(cfg);
      } catch {
        await onLogout?.();
        return Promise.reject(err);
      }
    }
  );
}

export async function tryRefreshAccessToken() {
  try {
    const r = await refreshApi.post("/auth/token", null);
    return r?.data?.accessToken || null;
  } catch (e) {
    if (e?.response?.status === 401) return null;
    throw e;
  }
}

/* ===============================
   Bridge (Manager -> Web SSO)
   =============================== */

export async function bridgeStart(accessToken) {
  const headers = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const r = await accountApi.post("/auth/bridge/start", null, { headers });
  return r?.data;
}

export function openWebWithBridge({ code, webOrigin = "http://localhost:5174" } = {}) {
  const url = `${webOrigin}/bridge?code=${encodeURIComponent(code)}`;
  window.open(url, "_blank", "noreferrer");
}
