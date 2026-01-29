import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  // ✅ Electron(file://)에서도 /assets 경로 깨지지 않게
  base: "./",

  plugins: [react(), tailwindcss()],

  resolve: { dedupe: ["react", "react-dom"] },

  server: {
    proxy: {
      // ✅ 계정/인증/회원 API는 8082 (Spring)
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

      // ✅ 나머지 /api 는 8080 (Python Agent API)
      "^/api/.*": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },

      // motion도 8080
      "^/motion/.*": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
