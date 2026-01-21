import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { accountApi, attachAccountInterceptors, tryRefreshAccessToken } from "../api/accountClient";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

const LS_KEY = "gos.accountAccessToken";

export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);

  const getToken = () => localStorage.getItem(LS_KEY);
  const setToken = (t) => {
    if (!t) localStorage.removeItem(LS_KEY);
    else localStorage.setItem(LS_KEY, t);
  };

  const logout = async () => {
    try {
      await accountApi.post("/auth/logout", null); // ✅ refreshToken DB 삭제 + 쿠키 만료
    } catch {}
    setToken(null);
    setUser(null);
  };

  const refreshMe = async () => {
    const res = await accountApi.get("/members/me");
    setUser(res?.data?.user || null);
    return res?.data?.user || null;
  };

  const loginWithCredentials = async (loginId, loginPw) => {
    const res = await accountApi.post("/members/login", { loginId, loginPw });
    const token = res?.data?.accessToken;
    if (!token) throw new Error("NO_TOKEN");
    setToken(token);
    return await refreshMe();
  };

  useEffect(() => {
    attachAccountInterceptors({
      getAccessToken: getToken,
      setAccessToken: setToken,
      onLogout: logout,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ✅ 부팅 시: (1) localStorage 토큰 있으면 me, (2) 없으면 refreshToken 쿠키로 token 발급 시도
  useEffect(() => {
    (async () => {
      try {
        const t = getToken();
        if (t) {
          await refreshMe();
        } else {
          // refreshToken 쿠키가 있으면 accessToken 새로 발급
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

  const value = useMemo(
    () => ({
      user,
      isAuthed: !!user,
      booting,
      loginWithCredentials,
      refreshMe,
      logout,
    }),
    [user, booting]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
