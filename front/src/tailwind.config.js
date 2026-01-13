// @ts-nocheck
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: { extend: {} },
  plugins: [require("daisyui")],
  daisyui: {
    themes: [
      {
        dark: {
          // ===== base (네가 원래 쓰던 다크) =====
          "base-100": "#070c16", // 앱 바탕
          "base-200": "#0b1220", // 패널/상단바
          "base-300": "#0f1a2e", // 더 진한 구간
          "base-content": "#e7eaf0",

          // ===== accent (네 코드의 sky 톤) =====
          "primary": "#38bdf8",
          "primary-content": "#06121d",

          // ✅ success를 초록이 아니라 "네가 쓰는 블루"로 고정 (초록 금지 핵심)
          "success": "#38bdf8",
          "success-content": "#06121d",

          // ===== states =====
          "info": "#38bdf8",
          "info-content": "#06121d",

          "warning": "#fbbf24",
          "warning-content": "#231800",

          "error": "#fb7185",
          "error-content": "#2a060c",

          // ===== misc =====
          "neutral": "#0b1020",
          "neutral-content": "#e7eaf0",

          "--rounded-box": "1rem",
          "--rounded-btn": "0.75rem",
          "--rounded-badge": "9999px",
        },
      },
      "light",
      "acid",
      "valentine",
    ],
  },
};
