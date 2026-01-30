import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ command }) => ({
  // ✅ Electron(file://)에서 /assets 깨지는 거 방지
  base: command === "build" ? "./" : "/",

  plugins: [react(), tailwindcss()],
  resolve: { dedupe: ["react", "react-dom"] },

  // Tailwind v4(+daisyUI 등)가 @property(at-rule)를 출력하는데,
  // 일부 CSS minifier에서 "Unknown at rule: @property" 로 빌드가 터질 수 있음.
  // 설치본 안정성을 위해 CSS minify를 끔.
  build: {
    cssMinify: false,
  },

  server: {
    host: true,
    port: 5174,
    strictPort: true,

    // ✅ dev 서버에서만 의미 있음 (build에는 영향 없음)
    // ✅ 더 구체적인 경로를 먼저 둬야 함
    proxy: {
      "/api/auth": {
        target: "http://127.0.0.1:8082",
        changeOrigin: true,
        secure: false,
      },
      "/api/members": {
        target: "http://127.0.0.1:8082",
        changeOrigin: true,
        secure: false,
      },

      // 나머지 API는 8080
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
        secure: false,
      },

      "/motion": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
        secure: false,
      },
    },
  },
}));
