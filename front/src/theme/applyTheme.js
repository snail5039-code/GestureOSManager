// src/theme/applyTheme.js
import { THEMES } from "./themeTokens";

const CURSOR_BY_THEME = {
  dark: "auto",
  neon: "auto",
  rose: "auto",
  devil: "url('/cursor/devil.png') 16 16, auto",
};

export function applyTheme(next) {
  const t = THEMES.includes(next) ? next : "dark";

  // ✅ daisyUI는 data-theme 기반
  document.documentElement.setAttribute("data-theme", t);

  // ✅ 테마별 커서 적용
  document.body.style.cursor = CURSOR_BY_THEME[t] || "auto";

  // (선택) 저장 — 네 프로젝트에서 이미 저장 키가 있으면 그 키로 맞춰도 됨
  try {
    localStorage.setItem("theme", t);
  } catch {}

  return t;
}

export function getInitialTheme() {
  try {
    const saved = localStorage.getItem("theme");
    if (saved && THEMES.includes(saved)) return saved;
  } catch {}
  return "dark";
}
