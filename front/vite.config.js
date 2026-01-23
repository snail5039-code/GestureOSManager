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

      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },

      // ✅ 추가
      "/motion": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },

      // "/ws": { target: "ws://localhost:8080", ws: true, changeOrigin: true },
    },
  },
});
