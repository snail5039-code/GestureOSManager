// src/components/TitleBar.jsx

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

export default function TitleBar({
  hudOn,
  onToggleHud,
  screen,
  onChangeScreen,
  theme,
  setTheme,
}) {
  const onMin = () => window.managerWin?.minimize?.();
  const onMax = () => window.managerWin?.toggleMaximize?.();
  const onClose = () => window.managerWin?.close?.();

  // ✅ return(JSX) 밖에서만 선언해야 함
  const THEME_PRESETS = ["dark", "light", "acid", "valentine"];

  return (
    <div
      className="navbar bg-base-200 h-11 flex items-center justify-between px-3 select-none border-b border-white/10 bg-gradient-to-b from-[#0b1020] to-[#070b14]"
      style={{ WebkitAppRegion: "no-drag" }}
      onDoubleClick={onMax}
    >
      {/* LEFT: Logo + Title + Screen Tabs */}
      <div className="flex items-center gap-3 text-slate-200">
        <div className="w-6 h-6 rounded-md bg-white/10 flex items-center justify-center text-xs">
          GA
        </div>
        <span className="font-semibold text-sm">Gesture Agent Manager</span>

        {/* 화면 전환 탭 */}
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

          <button
            type="button"
            onClick={() => onChangeScreen?.("vkey")}
            className={cn(
              "px-3 py-1 text-xs rounded-md transition",
              screen === "vkey"
                ? "bg-white/20 text-white"
                : "text-white/70 hover:bg-white/10 hover:text-white"
            )}
          >
            VKey
          </button>
        </div>

        {/* HUD 토글 */}
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

      {/* THEME BUTTONS */}
      <div
        className="ml-2 inline-flex items-center rounded-full ring-1 ring-white/10 bg-slate-900/35 p-1"
        style={{ WebkitAppRegion: "no-drag" }}
      >
        {THEME_PRESETS.map((th) => {
          const active = theme === th;

          return (
            <button
              key={th}
              type="button"
              onClick={() => setTheme?.(th)}
              className={cn(
                "btn btn-sm rounded-full",
                active
                  ? "btn-primary" : "btn-ghost"
              )}
              title={`테마: ${th}`}
            >
              {th}
            </button>
          );
        })}
      </div>

      {/* RIGHT: Window Controls */}
      <div
        className="flex items-center gap-2"
        style={{ WebkitAppRegion: "no-drag" }}
      >
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
