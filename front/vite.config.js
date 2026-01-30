import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => ({
  // ✅ file:// 패키징(설치본)에서는 상대경로로 빌드돼야 함
  base: mode === "development" ? "/" : "./",

  plugins: [react(), tailwindcss()],
  resolve: { dedupe: ["react", "react-dom"] },

  // Tailwind v4 + daisyUI @property 이슈 회피
  build: {
    cssMinify: false,
  },

  server: {
    host: true,
    port: 5174,
    strictPort: true,
    proxy:
      mode === "development"
        ? {
            "/api": {
              target: "http://127.0.0.1:8082",
              changeOrigin: true,
              secure: false,
            },
          }
        : undefined,
  },
}));
