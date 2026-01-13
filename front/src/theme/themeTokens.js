// src/theme/themeTokens.js

export const THEMES = ["dark", "white", "pink", "purple"];

export const THEME = {
  dark: {
    page: "bg-[#070c16] text-slate-100",
    topbar:
      "border-white/10 bg-gradient-to-r from-[#0b4aa2]/22 via-[#0b1220]/85 to-[#0b1220]/85",
    bgGlow1: "bg-sky-500/10",
    bgGlow2: "bg-emerald-500/8",
    grid:
      "bg-[linear-gradient(to_right,rgba(255,255,255,.10)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,.10)_1px,transparent_1px)] opacity-[0.08]",
    panel: "bg-slate-950/45 ring-white/10",
    panel2: "bg-slate-950/55 ring-white/10",
    panelSoft: "bg-slate-900/35 ring-white/10",
    muted: "text-slate-400",
    muted2: "text-slate-300/80",
    dot: "bg-sky-300 shadow-[0_0_18px_rgba(56,189,248,0.65)]",
  },

  white: {
    page: "bg-white text-slate-900",
    topbar: "border-slate-200 bg-gradient-to-r from-sky-50 via-white to-white",
    bgGlow1: "bg-sky-500/10",
    bgGlow2: "bg-emerald-500/10",
    grid:
      "bg-[linear-gradient(to_right,rgba(15,23,42,.10)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,.10)_1px,transparent_1px)] opacity-[0.12]",
    panel: "bg-white ring-slate-200",
    panel2: "bg-white ring-slate-200",
    panelSoft: "bg-slate-50 ring-slate-200",
    muted: "text-slate-500",
    muted2: "text-slate-600",
    dot: "bg-sky-500 shadow-[0_0_18px_rgba(14,165,233,0.35)]",
  },

  pink: {
    page: "bg-[#fff5f8] text-slate-900",
    topbar: "border-pink-200 bg-gradient-to-r from-pink-100/70 via-white to-white",
    bgGlow1: "bg-pink-500/14",
    bgGlow2: "bg-fuchsia-500/10",
    grid:
      "bg-[linear-gradient(to_right,rgba(225,29,72,.12)_1px,transparent_1px),linear-gradient(to_bottom,rgba(225,29,72,.12)_1px,transparent_1px)] opacity-[0.10]",
    panel: "bg-white ring-pink-200/70",
    panel2: "bg-white ring-pink-200/70",
    panelSoft: "bg-pink-50 ring-pink-200/70",
    muted: "text-slate-500",
    muted2: "text-slate-600",
    dot: "bg-pink-500 shadow-[0_0_18px_rgba(236,72,153,0.30)]",
  },

  purple: {
    page: "bg-[#f7f5ff] text-slate-900",
    topbar:
      "border-violet-200 bg-gradient-to-r from-violet-100/70 via-white to-white",
    bgGlow1: "bg-violet-500/14",
    bgGlow2: "bg-indigo-500/10",
    grid:
      "bg-[linear-gradient(to_right,rgba(124,58,237,.12)_1px,transparent_1px),linear-gradient(to_bottom,rgba(124,58,237,.12)_1px,transparent_1px)] opacity-[0.10]",
    panel: "bg-white ring-violet-200/70",
    panel2: "bg-white ring-violet-200/70",
    panelSoft: "bg-violet-50 ring-violet-200/70",
    muted: "text-slate-500",
    muted2: "text-slate-600",
    dot: "bg-violet-500 shadow-[0_0_18px_rgba(139,92,246,0.28)]",
  },
};
