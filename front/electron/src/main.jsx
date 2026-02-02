import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";
import { applyTheme, getInitialTheme } from "./theme/applyTheme";
import AuthProvider from "./auth/AuthProvider.jsx";

/**
 * ✅ file:// 설치본에서 "/api/..." 가 "C:\api\..." 로 해석되는 문제를 런타임에서 강제 교정
 * - fetch("/api/...") → http://127.0.0.1:8080/api/...
 * - XHR("/api/...")   → http://127.0.0.1:8080/api/...
 * - fetch("/audio/...") / "/sfx/..." → 앱 파일 기준 상대경로로 변환
 *
 * ⚠️ 이건 "소스 여기저기 /api 하드코딩"이 남아있어도 무조건 먹게 하는 안전장치.
 */
(function installFileProtocolShim() {
  if (typeof window === "undefined") return;

  const proto = window.location.protocol;
  const isPackaged = proto === "file:" || proto === "app:" || proto === "gestureos:";

  if (!isPackaged) return;

  const API_ORIGIN = "http://127.0.0.1:8080";

  const toAppAssetUrl = (absPath) => {
    // absPath: "/audio/xxx.mp3" 같은 형태
    const p = String(absPath || "");
    return new URL("." + (p.startsWith("/") ? p : "/" + p), document.baseURI).toString();
  };

  const rewriteUrl = (url) => {
    const u = String(url || "");

    // API
    if (u.startsWith("/api/") || u === "/api") return API_ORIGIN + u;

    // public assets
    if (u.startsWith("/audio/") || u.startsWith("/sfx/") || u.startsWith("/images/") || u.startsWith("/icons/")) {
      return toAppAssetUrl(u);
    }

    return u;
  };

  // ---- fetch shim
  const _fetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    try {
      if (typeof input === "string") {
        return _fetch(rewriteUrl(input), init);
      }
      if (input && typeof input === "object" && "url" in input) {
        const req = input;
        const nextUrl = rewriteUrl(req.url);
        // Request는 immutable일 수 있어서 새로 생성
        const nextReq = new Request(nextUrl, req);
        return _fetch(nextReq, init);
      }
    } catch (e) {
      // fallthrough
    }
    return _fetch(input, init);
  };

  // ---- XHR shim (axios 포함)
  const _open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, async, user, password) {
    const nextUrl = rewriteUrl(url);
    return _open.call(this, method, nextUrl, async, user, password);
  };

  // ---- Audio src shim (new Audio("/audio/..."))
  const _Audio = window.Audio;
  window.Audio = function (src) {
    if (typeof src === "string") src = rewriteUrl(src);
    return new _Audio(src);
  };
  window.Audio.prototype = _Audio.prototype;
})();

applyTheme(getInitialTheme());
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>
);
