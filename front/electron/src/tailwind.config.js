// tailwind.config.js
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
          "base-100": "#070c16",
          "base-200": "#0b1220",
          "base-300": "#0f1a2e",
          "base-content": "#e7eaf0",

          "primary": "#38bdf8",
          "primary-content": "#06121d",

          // ✅ 오른쪽 레인/판정용 (Rush에서 text-secondary 사용)
          "secondary": "#ff4fd8",
          "secondary-content": "#1a0614",

          "success": "#38bdf8",
          "success-content": "#06121d",

          "info": "#38bdf8",
          "info-content": "#06121d",

          "warning": "#fbbf24",
          "warning-content": "#231800",

          "error": "#fb7185",
          "error-content": "#2a060c",

          "neutral": "#0b1020",
          "neutral-content": "#e7eaf0",
        },

        neon: {
          "base-100": "#05080D",
          "base-200": "#0B1220",
          "base-300": "#111C33",
          "base-content": "#E7EAF0",

          "primary": "#00E5FF",
          "primary-content": "#001018",

          // ✅ 네온도 오른쪽은 핑크 유지
          "secondary": "#ff4fd8",
          "secondary-content": "#1a0614",

          "info": "#00E5FF",
          "info-content": "#001018",

          "success": "#00E5FF",
          "success-content": "#001018",

          "warning": "#FBBF24",
          "warning-content": "#231800",

          "error": "#FB7185",
          "error-content": "#2A060C",

          "neutral": "#0B1020",
          "neutral-content": "#E7EAF0",
        },

        rose: {
          "base-100": "#FBF7F9",
          "base-200": "#F2F4F7",
          "base-300": "#E5E7EB",
          "base-content": "#111827",

          "primary": "#FF4F8B",
          "primary-content": "#FFFFFF",

          // ✅ 로즈에서 secondary는 블루 계열(왼/오 대비 살리고 싶으면)
          //    (원하면 secondary도 핑크로 두고, info를 블루로 써도 됨)
          "secondary": "#38BDF8",
          "secondary-content": "#06121d",

          "info": "#38BDF8",
          "info-content": "#06121d",

          "success": "#38BDF8",
          "success-content": "#06121d",

          "warning": "#F59E0B",
          "warning-content": "#231800",

          "error": "#EF4444",
          "error-content": "#FFFFFF",

          "neutral": "#1F2937",
          "neutral-content": "#FFFFFF",
        },

        devil: {
          // ✅ 다크 베이스(쿠로미 느낌 핵심)
          "base-100": "#0C0814",   // 배경
          "base-200": "#151027",   // 카드/패널
          "base-300": "#231A3C",   // 테두리/분리
          "base-content": "#F6F0FF",

          // ✅ 퍼플(메인) + 핑크(포인트)
          "primary": "#C084FC",            // 퍼플
          "primary-content": "#120A1E",

          "secondary": "#FF4FD8",          // 핫핑크
          "secondary-content": "#16040F",

          "accent": "#A78BFA",             // 라벤더(보조)
          "accent-content": "#120A1E",

          "neutral": "#140B1F",
          "neutral-content": "#F4ECFF",

          "info": "#7DD3FC",
          "success": "#34D399",
          "warning": "#FBBF24",
          "error": "#FB7185",
        }

      },
      "light",
    ],
  },
};
