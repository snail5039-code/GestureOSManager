// src/auth/AuthProvider.jsx
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useCallback,
} from "react";
import {
  accountApi,
  attachAccountInterceptors,
  tryRefreshAccessToken,
} from "../api/accountClient";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

const LS_KEY = "gos.accountAccessToken";

// 필요하면 환경변수로 제어
const DEFAULT_POLL_MS = 0; // 0이면 폴링 비활성 (예: 15000 넣으면 15초마다 me 동기화)

export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);

  // 이미지 캐시 bust 등에 활용 가능 (me 갱신될 때마다 증가)
  const [profileBump, setProfileBump] = useState(0);

  const getToken = () => localStorage.getItem(LS_KEY);
  const setToken = (t) => {
    if (!t) localStorage.removeItem(LS_KEY);
    else localStorage.setItem(LS_KEY, t);
  };

  // refreshMe 중복 호출 방지
  const inflightRef = useRef(null);

  const logout = useCallback(async () => {
    try {
      // refreshToken DB 삭제 + 쿠키 만료
      // (인터셉터가 /auth/logout엔 refresh 재시도 안 하도록 accountClient에서 막아둠)
      await accountApi.post("/auth/logout", null);
    } catch {
      // ignore
    }
    setToken(null);
    setUser(null);
    setProfileBump((x) => x + 1);
  }, []);

  /**
   * 서버에서 내 정보 다시 조회해 user를 갱신
   * - inflight로 중복 호출 병합
   * - 401/403이면 토큰/세션 만료로 보고 logout
   */
  const refreshMe = useCallback(async () => {
    if (inflightRef.current) return inflightRef.current;

    const p = (async () => {
      try {
        const res = await accountApi.get("/members/me");
        const nextUser = res?.data?.user || null;
        setUser(nextUser);
        setProfileBump((x) => x + 1);
        return nextUser;
      } catch (e) {
        const status = e?.response?.status;

        // 인증 만료/권한 문제면 정리
        if (status === 401 || status === 403) {
          await logout();
          return null;
        }

        throw e;
      } finally {
        inflightRef.current = null;
      }
    })();

    inflightRef.current = p;
    return p;
  }, [logout]);

  const loginWithCredentials = useCallback(
    async (loginId, loginPw) => {
      const res = await accountApi.post("/members/login", { loginId, loginPw });
      const token = res?.data?.accessToken;
      if (!token) throw new Error("NO_TOKEN");
      setToken(token);
      return await refreshMe();
    },
    [refreshMe]
  );

  // 인터셉터는 최초 1회만
  useEffect(() => {
    attachAccountInterceptors({
      getAccessToken: getToken,
      setAccessToken: setToken,
      onLogout: logout,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ✅ 부팅 시:
  // (1) localStorage 토큰 있으면 me
  // (2) 없으면 refreshToken 쿠키로 token 발급 시도 후 me
  useEffect(() => {
    (async () => {
      try {
        const t = getToken();
        if (t) {
          await refreshMe();
        } else {
          const newToken = await tryRefreshAccessToken().catch(() => null);
          if (newToken) {
            setToken(newToken);
            await refreshMe();
          }
        }
      } catch {
        await logout();
      } finally {
        setBooting(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ✅ 포커스/탭 복귀 시 me 동기화
  useEffect(() => {
    if (booting) return;
    if (!user) return;

    const onFocus = () => refreshMe().catch(() => {});
    const onVis = () => {
      if (!document.hidden) refreshMe().catch(() => {});
    };

    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVis);

    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [booting, user, refreshMe]);

  // (옵션) 주기적 동기화
  useEffect(() => {
    if (booting) return;
    if (!user) return;
    const ms = DEFAULT_POLL_MS;
    if (!ms || ms < 1000) return;

    const id = window.setInterval(() => {
      refreshMe().catch(() => {});
    }, ms);

    return () => window.clearInterval(id);
  }, [booting, user, refreshMe]);

  const value = useMemo(
    () => ({
      user,
      isAuthed: !!user,
      booting,
      loginWithCredentials,
      refreshMe,
      logout,
      profileBump,
    }),
    [user, booting, loginWithCredentials, refreshMe, logout, profileBump]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
