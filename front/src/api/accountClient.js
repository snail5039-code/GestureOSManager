import axios from "axios";

const isFile = typeof window !== "undefined" && window.location.protocol === "file:";

// dev(vite)에서는 proxy(/api) 유지
// 설치본(file://)에서는 백엔드 포트가 2개라서 요청별로 분기
// - 기본 기능 API: 8080
// - 인증/회원/소셜(auth, members, oauth2 등): 8082
const API_BASE = isFile ? "http://127.0.0.1:8080/api" : "/api";
const AUTH_BASE = isFile ? "http://127.0.0.1:8082/api" : "/api";

function isAuthOrMemberPath(url) {
  const u = String(url || "");
  return (
    u.startsWith("/auth/") ||
    u.startsWith("auth/") ||
    u.startsWith("/members/") ||
    u.startsWith("members/") ||
    u.startsWith("/oauth2/") ||
    u.startsWith("oauth2/") ||
    u.startsWith("/login") ||
    u.startsWith("login") ||
    u.startsWith("/logout") ||
    u.startsWith("logout")
  );
}

function applyBaseRouting(config) {
  if (!isFile || !config) return config;
  // axios 요청 URL(/auth/..., /members/...) 기준으로 baseURL을 고정
  config.baseURL = isAuthOrMemberPath(config.url) ? AUTH_BASE : API_BASE;
  return config;
}

export const accountApi = axios.create({
  // 기본값은 8080으로 잡고, file:// 모드에서만 요청별로 8082로 분기
  baseURL: API_BASE,
  withCredentials: true,
  timeout: 8000,
  headers: { Accept: "application/json" },
});

const refreshApi = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  timeout: 8000,
  headers: { Accept: "application/json" },
});

// file:// 모드 라우팅(요청별 baseURL 분기)
accountApi.interceptors.request.use((config) => applyBaseRouting(config));
refreshApi.interceptors.request.use((config) => applyBaseRouting(config));

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
            .post("/auth/token", null)
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
  const r = await refreshApi.post("/auth/token", null);
  return r?.data?.accessToken || null;
}

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
