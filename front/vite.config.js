import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ command }) => ({
  // ✅ Electron(file://)에서 /assets 깨지는 거 방지
  base: command === "build" ? "./" : "/",

  plugins: [react(), tailwindcss()],
  resolve: { dedupe: ["react", "react-dom"] },

  server: {
    proxy: {
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
      "^/api/.*": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },
      "^/motion/.*": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },
    },
  },
}));
