import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss()
  ],
  
  // 1. .glb 파일을 자산(asset)으로 취급하도록 추가
  // 이렇게 해야 Vite가 GLB 파일을 JS 코드로 오해해서 구문 오류(Syntax Error)를 내지 않습니다.
  assetsInclude: ["**/*.glb"], 

  resolve: {
    dedupe: ["react", "react-dom"],
  },

  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        secure: false,
      },
        // "/ws": {

      //   target: "ws://localhost:8080",

      //   ws: true,

      //   changeOrigin: true,

      // },
    },
  },
});