// src/theme/themeTokens.js
export const THEMES = ["dark", "light", "neon", "rose", "devil"];

export const THEME = {
  dark: {
    page: "bg-[#070c16] text-slate-100",
    topbarFx:
      "border-white/10 bg-gradient-to-r from-sky-500/15 via-[#0b1220]/85 to-[#0b1220]/85",
    glow1: "bg-sky-500/10",
    glow2: "bg-emerald-500/8",
    grid:
      "bg-[linear-gradient(to_right,rgba(255,255,255,.10)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,.10)_1px,transparent_1px)] opacity-[0.08]",
    panel: "bg-slate-950/45 ring-white/12",
    panel2: "bg-slate-950/55 ring-white/12",
    panelSoft: "bg-slate-900/35 ring-white/12",
    chip: "bg-slate-950/45 ring-white/12",
    input: "bg-slate-950/55 ring-white/12 text-slate-100 placeholder:text-slate-500",
    divider: "bg-white/10",
    text: "text-slate-100",
    text2: "text-slate-200",
    muted: "text-slate-400",
    muted2: "text-slate-300/80",
    dot: "bg-sky-300 shadow-[0_0_18px_rgba(56,189,248,0.65)]",
    btn: "bg-white/5 ring-white/12 hover:bg-white/10 text-slate-100",
    miniMapBg: "bg-slate-900/35",
    miniMapRing: "ring-white/12",

    colors: {
      bg0: "#060a14",
      bg1: "#0b1020",
      fog: "#070a14",
      grid: "#8aa0c8",
      lane: "#0a0f1f",
      rail: "#9be7ff",
      left: "#7dd3fc",
      right: "#ff4fd8",
      hitCore: "#c7f3ff",
      white: "#ffffff",
    },
  },

  light: {
    page: "bg-white text-slate-900",
    topbarFx: "border-slate-200 bg-gradient-to-r from-sky-50 via-white to-white",
    glow1: "bg-sky-500/10",
    glow2: "bg-emerald-500/10",
    grid:
      "bg-[linear-gradient(to_right,rgba(15,23,42,.10)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,.10)_1px,transparent_1px)] opacity-[0.12]",
    panel: "bg-white ring-slate-200",
    panel2: "bg-white ring-slate-200",
    panelSoft: "bg-slate-50 ring-slate-200",
    chip: "bg-slate-100 ring-slate-200",
    input: "bg-white ring-slate-300 text-slate-900 placeholder:text-slate-400",
    divider: "bg-slate-200",
    text: "text-slate-900",
    text2: "text-slate-800",
    muted: "text-slate-500",
    muted2: "text-slate-600",
    dot: "bg-sky-500 shadow-[0_0_18px_rgba(14,165,233,0.35)]",
    btn: "bg-white ring-slate-300 hover:bg-slate-50 text-slate-900",
    miniMapBg: "bg-white",
    miniMapRing: "ring-rose-200",

    colors: {
      bg0: "#ffffff",
      bg1: "#f1f5f9",
      fog: "#e2e8f0",
      grid: "#334155",
      lane: "#e2e8f0",
      rail: "#0ea5e9",
      left: "#0ea5e9",
      right: "#db2777",
      hitCore: "#0f172a",
      white: "#ffffff",
    },
  },

  neon: {
    page: "bg-[#020b10] text-cyan-50",
    topbarFx: "bg-gradient-to-r from-cyan-500/30 via-cyan-400/10 to-transparent",
    glow1: "bg-cyan-400/25",
    glow2: "bg-teal-400/20",
    grid:
      "bg-[linear-gradient(to_right,rgba(34,211,238,.18)_1px,transparent_1px),linear-gradient(to_bottom,rgba(34,211,238,.18)_1px,transparent_1px)] opacity-[0.12]",
    panel: "bg-[#020f14]/85 ring-cyan-400/35",
    panel2: "bg-[#020f14]/70 ring-cyan-400/25",
    panelSoft: "bg-[#02131a]/55 ring-cyan-400/25",
    text: "text-cyan-50",
    text2: "text-cyan-200",
    muted: "text-cyan-300/60",
    muted2: "text-cyan-200/70",
    chip: "bg-cyan-500/10 ring-cyan-400/35",
    divider: "bg-cyan-400/20",
    btn: "bg-cyan-500/15 ring-cyan-400/35 text-cyan-50 hover:bg-cyan-500/25",
    input:
      "bg-[#02131a] ring-cyan-400/35 text-cyan-50 placeholder:text-cyan-300/40",
    dot: "bg-cyan-300 shadow-[0_0_24px_rgba(34,211,238,0.85)]",
    miniMapBg: "bg-[#02131a]",
    miniMapRing: "ring-cyan-400/25",

    colors: {
      bg0: "#020b10",
      bg1: "#02131a",
      fog: "#02131a",
      grid: "#22d3ee",
      lane: "#020f14",
      rail: "#00E5FF",
      left: "#00E5FF",
      right: "#ff4fd8",
      hitCore: "#c7f3ff",
      white: "#ffffff",
    },
  },

  rose: {
    page: "bg-[#fff7f9] text-slate-900",
    topbarFx: "bg-gradient-to-r from-rose-300/40 via-transparent to-transparent",
    glow1: "bg-rose-300/30",
    glow2: "bg-pink-300/20",
    grid:
      "bg-[linear-gradient(to_right,rgba(244,63,94,.12)_1px,transparent_1px),linear-gradient(to_bottom,rgba(244,63,94,.12)_1px,transparent_1px)] opacity-[0.08]",
    panel: "bg-white ring-rose-200",
    panel2: "bg-white ring-rose-200",
    panelSoft: "bg-rose-50 ring-rose-200",
    text: "text-slate-900",
    text2: "text-slate-700",
    muted: "text-slate-500",
    muted2: "text-slate-600",
    chip: "bg-rose-100 ring-rose-300",
    divider: "bg-rose-200",
    btn: "bg-rose-100 ring-rose-300 text-slate-900 hover:bg-rose-200",
    input: "bg-white ring-rose-300 text-slate-900",
    dot: "bg-sky-500 shadow-[0_0_14px_rgba(14,165,233,0.45)]",
    miniMapBg: "bg-white",
    miniMapRing: "ring-rose-200",

    colors: {
      bg0: "#FBF7F9",
      bg1: "#F2F4F7",
      fog: "#E5E7EB",
      grid: "#fb7185",
      lane: "#ffffff",
      rail: "#FF4F8B",
      left: "#38bdf8",
      right: "#FF4F8B",
      hitCore: "#111827",
      white: "#ffffff",
    },
  },

  devil: {
    _isBright: false,

    page: "bg-[#09060F] text-[#F4ECFF]",
    topbarFx:
      "border-white/10 bg-gradient-to-r from-[#FF4FD8]/20 via-[#0F0A1A]/80 to-[#0F0A1A]/80",
    glow1: "bg-[#C084FC]/26",
    glow2: "bg-[#FF4FD8]/18",
    grid:
      "bg-[linear-gradient(to_right,rgba(244,236,255,.10)_1px,transparent_1px),linear-gradient(to_bottom,rgba(244,236,255,.10)_1px,transparent_1px)] opacity-[0.06]",

    panel: "bg-[#151027]/88 ring-[#C084FC]/18",
    panel2: "bg-[#151027]/78 ring-[#C084FC]/14",
    panelSoft: "bg-[#1B1330]/55 ring-[#C084FC]/14",
    chip: "bg-[#1B1330]/55 ring-[#C084FC]/14",
    divider: "bg-[#C084FC]/12",

    // ✅ 입력/셀렉트 “선택 후 글자 흰색” 문제를 여기서 잡아줌
    // - text를 base-content로 강제
    // - option은 라이트 배경이라 글자 검정으로 강제
    input:
      "bg-[#0F0A1A] ring-white/12 text-[#F4ECFF] placeholder:text-[#C9B6E7]/55 " +
      "[&>option]:bg-white [&>option]:text-slate-900",
    text: "text-[#F4ECFF]",
    text2: "text-[#E9DDFF]",
    muted: "text-[#C9B6E7]/70",
    muted2: "text-[#C9B6E7]/80",

    dot: "bg-[#C084FC] shadow-[0_0_18px_rgba(192,132,252,0.65)]",

    // ✅ 버튼은 퍼플/핑크 포인트로
    btn: "bg-white/5 ring-white/12 hover:bg-white/10 text-[#F4ECFF]",

    miniMapBg: "bg-white",
    miniMapRing: "ring-violet-200",

    colors: {
      bg0: "#09060F",
      bg1: "#0F0A1A",
      fog: "#09060F",
      grid: "#C084FC",
      lane: "#0B0713",
      rail: "#C084FC",
      left: "#A78BFA",
      right: "#FF4FD8",
      hitCore: "#F4ECFF",
      white: "#FFFFFF",
    },
  },
};