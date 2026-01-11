function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

export default function TitleBar({ hudOn, onToggleHud, screen, onChangeScreen }) {
  const onMin = () => window.managerWin?.minimize?.();
  const onMax = () => window.managerWin?.toggleMaximize?.();
  const onClose = () => window.managerWin?.close?.();

  return (
    <div
      className="h-11 flex items-center justify-between px-3 select-none border-b border-white/10 bg-gradient-to-b from-[#0b1020] to-[#070b14]"
      style={{ WebkitAppRegion: "drag" }}
      onDoubleClick={onMax}
    >
      {/* LEFT: Logo + Title + Screen Tabs */}
      <div className="flex items-center gap-3 text-slate-200">
        <div className="w-6 h-6 rounded-md bg-white/10 flex items-center justify-center text-xs">
          GA
        </div>
        <span className="font-semibold text-sm">Gesture Agent Manager</span>

        {/* ✅ 화면 전환 탭 (드래그 영역에서 제외) */}
        <div
          className="ml-2 flex items-center gap-1 bg-white/5 p-1 rounded-lg"
          style={{ WebkitAppRegion: "no-drag" }}
        >
          <button
            type="button"
            onClick={() => onChangeScreen?.("dashboard")}
            className={cn(
              "px-3 py-1 text-xs rounded-md transition",
              screen === "dashboard"
                ? "bg-white/20 text-white"
                : "text-white/70 hover:bg-white/10 hover:text-white"
            )}
          >
            Dashboard
          </button>

          <button
            type="button"
            onClick={() => onChangeScreen?.("rush")}
            className={cn(
              "px-3 py-1 text-xs rounded-md transition",
              screen === "rush"
                ? "bg-white/20 text-white"
                : "text-white/70 hover:bg-white/10 hover:text-white"
            )}
          >
            Rush
          </button>
        </div>

        {/* ✅ HUD 토글 (원하면 TitleBar에도 둠) */}
        <button
          type="button"
          onClick={() => onToggleHud?.()}
          className={cn(
            "ml-1 px-3 py-1 text-xs rounded-lg transition",
            hudOn
              ? "bg-emerald-500/15 border border-emerald-400/25 text-emerald-50 hover:bg-emerald-500/25"
              : "bg-white/5 border border-white/10 text-white/80 hover:bg-white/10"
          )}
          style={{ WebkitAppRegion: "no-drag" }}
          title="Toggle HUD"
        >
          HUD: {hudOn ? "ON" : "OFF"}
        </button>
      </div>

      {/* RIGHT: Window Controls (no-drag) */}
      <div className="flex items-center gap-2" style={{ WebkitAppRegion: "no-drag" }}>
        <button
          className="w-10 h-8 rounded-md hover:bg-white/10 text-slate-200"
          onClick={onMin}
          title="Minimize"
        >
          —
        </button>
        <button
          className="w-10 h-8 rounded-md hover:bg-white/10 text-slate-200"
          onClick={onMax}
          title="Maximize"
        >
          □
        </button>
        <button
          className="w-10 h-8 rounded-md hover:bg-red-500/30 text-slate-200"
          onClick={onClose}
          title="Close"
        >
          ×
        </button>
      </div>
    </div>
  );
}
