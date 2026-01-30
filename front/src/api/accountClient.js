import axios from "axios";

const isFile = typeof window !== "undefined" && window.location.protocol === "file:";

// dev(vite)에서는 proxy(/api) 유지
// 설치본(file://)에서는 직접 백엔드로
const baseURL = isFile ? "http://localhost:8082/api" : "/api";

export const accountApi = axios.create({
  baseURL,
  withCredentials: true,
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
