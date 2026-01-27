import axios from "axios";

// ✅ 중요: 브라우저에서 직접 8082로 치지 말고, Vite proxy(/api)를 통해 동일 오리진처럼 사용
// 그러면 refreshToken 쿠키도 안정적으로 붙는다.
const baseURL = "/api";

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

/* ===============================
   Bridge (Manager -> Web SSO)
   =============================== */

// accessToken을 직접 넘기고 싶으면 인자로 전달.
// (이미 interceptor로 Authorization이 붙는다면 인자 없이도 동작)
export async function bridgeStart(accessToken) {
  const headers = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const r = await accountApi.post("/auth/bridge/start", null, { headers });
  return r?.data;
}

// 프론트(5174)에서 /bridge?code= 로 들어가면 App.jsx가 consume 하도록 구성 권장.
// 그래도 필요하면 이걸로 탭을 열 수 있음.
export function openWebWithBridge({ code, webOrigin = "http://localhost:5174" } = {}) {
  const url = `${webOrigin}/bridge?code=${encodeURIComponent(code)}`;
  window.open(url, "_blank", "noreferrer");
}
