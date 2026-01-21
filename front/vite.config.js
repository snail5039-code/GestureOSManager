import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],

  resolve: {
    dedupe: ["react", "react-dom"],
  },

  server: {
    proxy: {
      // ✅ 회원/인증만 Spring(8082)로 보낸다
      // (순서 중요: 아래 "/api" 보다 위에 있어야 함)
      "/api/members": {
        target: "http://localhost:8082",
        changeOrigin: true,
        secure: false,
      },
      "/api/auth": {
        target: "http://localhost:8082",
        changeOrigin: true,
        secure: false,
      },
      "/oauth2/authorization": {
        target: "http://localhost:8082",
        changeOrigin: true,
        secure: false,
      },
      "/login/oauth2": {
        target: "http://localhost:8082",
        changeOrigin: true,
        secure: false,
      },

      // ✅ 그 외 /api는 전부 Agent(8080)
      // - /api/status, /api/train/stats, /api/pairing, /api/hud/show, /api/settings ...
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },

      // 필요하면 WS도 8080으로
      // "/ws": { target: "ws://localhost:8080", ws: true, changeOrigin: true },
    },
  },
});
