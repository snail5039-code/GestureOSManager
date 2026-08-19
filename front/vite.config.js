import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// 매니저 서버(8080)는 모든 /api 요청에 로컬 세션 토큰을 요구한다.
// 개발 중에는 이 dev proxy 가, 설치본에서는 Electron 메인 프로세스가 헤더를 붙인다.
// 어느 쪽이든 렌더러 코드에는 토큰이 들어가지 않는다.
//
// 같은 읽기 로직이 electron/localToken.cjs 에도 있다. vite.config 는 ESM 으로 번들되어
// CJS 모듈을 require 할 수 없어서 여기서는 짧게 다시 구현했다(경로 규칙만 맞추면 된다).
function readLocalToken() {
  try {
    const tokenPath =
      process.env.GOS_TOKEN_PATH || path.join(os.homedir(), ".gestureos", "session.token");
    return fs.readFileSync(tokenPath, "utf8").trim() || null;
  } catch {
    return null; // 서버가 아직 안 떴거나 인증이 꺼진 경우
  }
}

function attachLocalToken(proxy) {
  proxy.on("proxyReq", (proxyReq) => {
    const token = readLocalToken();
    if (token) proxyReq.setHeader("X-GOS-Token", token);
  });
}

const agentTarget = {
  target: "http://127.0.0.1:8080",
  changeOrigin: true,
  secure: false,
  configure: attachLocalToken,
};

export default defineConfig({
  plugins: [react(), tailwindcss()],

  resolve: { dedupe: ["react", "react-dom"] },

  server: {
    proxy: {
      // ✅ 계정/인증/회원 API는 8082 (Spring) — 이쪽은 토큰이 필요 없다
      "^/api/auth/.*": {
        target: "http://localhost:8082",
        changeOrigin: true,
        secure: false,
      },
      "^/api/members/.*": {
        target: "http://localhost:8082",
        changeOrigin: true,
        secure: false,
      },

      // ✅ 나머지 /api 는 8080 (매니저 서버)
      "^/api/.*": agentTarget,

      // motion도 8080
      "^/motion/.*": agentTarget,
    },
  },
});
