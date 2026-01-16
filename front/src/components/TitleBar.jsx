import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function StatusChip({ tone = "neutral", children, title }) {
  const base =
    "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] leading-none ring-1 select-none";
  const toneCls =
    tone === "ok"
      ? "bg-emerald-500/12 ring-emerald-400/25 text-base-content"
      : tone === "bad"
      ? "bg-rose-500/12 ring-rose-400/25 text-base-content"
      : "bg-base-100/35 ring-base-300/50 text-base-content opacity-95";

  return (
    <span className={cn(base, toneCls)} title={title}>
      {children}
    </span>
  );
}

export default function TitleBar({
  hudOn,
  onToggleHud,
  osHudOn,
  onToggleOsHud,
  screen,
  onChangeScreen,
  theme,
  setTheme,

  // ✅ 추가: Dashboard 폴링 결과를 여기로 올려서 표시
  agentStatus, // { connected:boolean, locked:boolean, mode:string, modeText?:string }
}) {
  const onMin = () => window.managerWin?.minimize?.();
  const onMax = () => window.managerWin?.toggleMaximize?.();
  const onClose = () => window.managerWin?.close?.();

  const THEME_PRESETS = useMemo(
    () => [
      { id: "dark", label: "다크" },
      { id: "light", label: "라이트" },
      { id: "neon", label: "네온" },
      { id: "rose", label: "로즈" },
      { id: "devil", label: "데빌" },
    ],
    []
  );

  const MODE_LABEL = useMemo(
    () => ({
      MOUSE: "마우스",
      KEYBOARD: "키보드",
      PRESENTATION: "프레젠테이션",
      DRAW: "그리기",
      RUSH: "러쉬",
      VKEY: "가상키보드",
      DEFAULT: "기본",
    }),
    []
  );

  const currentThemeLabel =
    THEME_PRESETS.find((t) => t.id === theme)?.label ?? theme ?? "dark";

  const connected = !!agentStatus?.connected;
  const locked = !!agentStatus?.locked;
  const modeText =
    agentStatus?.modeText ??
    MODE_LABEL?.[agentStatus?.mode] ??
    agentStatus?.mode ??
    "-";

  // =========================
  // Theme Select Popover (Portal)
  // =========================
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);
  const popRef = useRef(null);
  const [pos, setPos] = useState({ top: 48, left: 0, width: 220 });

  const calcPos = () => {
    const el = btnRef.current;
    if (!el) return;

    const r = el.getBoundingClientRect();
    const margin = 8;
    const width = Math.max(180, r.width + 24);

    const desiredLeft = r.right - width;
    const left = Math.max(margin, Math.min(desiredLeft, window.innerWidth - width - margin));
    const top = Math.min(r.bottom + margin, window.innerHeight - margin);

    setPos({ top, left, width });
  };

  useEffect(() => {
    if (!open) return;
    calcPos();

    const onDown = (e) => {
      const t = e.target;
      const btn = btnRef.current;
      const pop = popRef.current;
      if (!btn || !pop) return;
      if (btn.contains(t) || pop.contains(t)) return;
      setOpen(false);
    };

    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };

    const onResize = () => calcPos();
    const onScroll = () => calcPos();

    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, true);

    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  const ThemePopover = open
    ? createPortal(
        <div
          ref={popRef}
          style={{
            position: "fixed",
            top: pos.top,
            left: pos.left,
            width: pos.width,
            zIndex: 99999,
          }}
          className={cn(
            "rounded-xl shadow-2xl ring-1",
            "bg-base-200 text-base-content border border-base-300/60",
            "p-2"
          )}
        >
          <div className="text-[11px] px-2 py-1 opacity-70">Theme</div>
          <ul className="menu menu-sm w-full">
            {THEME_PRESETS.map((t) => {
              const active = t.id === theme;
              return (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setTheme?.(t.id);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex items-center justify-between rounded-lg",
                      active ? "active font-semibold" : ""
                    )}
                  >
                    <span>{t.label}</span>
                    {active ? <span className="opacity-70">✓</span> : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>,
        document.body
      )
    : null;

  return (
    <div
      className={cn(
        "navbar h-11 px-3 select-none",
        "border-b border-base-300/50",
        "bg-base-200/80 backdrop-blur",
        "text-base-content"
      )}
      style={{ WebkitAppRegion: "no-drag" }}
      onDoubleClick={onMax}
    >
      {/* LEFT */}
      <div className="flex items-center gap-3">
        <div className="w-6 h-6 rounded-md bg-base-300/40 ring-1 ring-base-300/60 flex items-center justify-center text-xs font-bold">
          GA
        </div>
        <span className="font-semibold text-sm">Gesture Agent Manager</span>

        {/* Tabs */}
        <div className="ml-2 flex items-center gap-1 bg-base-100/40 ring-1 ring-base-300/50 p-1 rounded-lg">
          <button
            type="button"
            onClick={() => onChangeScreen?.("dashboard")}
            className={cn(
              "px-3 py-1 text-xs rounded-md transition",
              screen === "dashboard"
                ? "bg-base-300/50 text-base-content"
                : "opacity-80 hover:bg-base-300/30 hover:opacity-100"
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
                ? "bg-base-300/50 text-base-content"
                : "opacity-80 hover:bg-base-300/30 hover:opacity-100"
            )}
          >
            Rush
          </button>
        </div>

        {/* ✅ 여기: 연결/잠금/모드만 살려서 위쪽으로 */}
        <div className="ml-2 flex items-center gap-1.5">
          <StatusChip tone={connected ? "ok" : "bad"} title="에이전트 연결 상태">
            {connected ? "연결됨" : "끊김"}
          </StatusChip>
          <StatusChip tone={locked ? "bad" : "ok"} title="제스처 잠금 상태">
            {locked ? "잠금" : "해제"}
          </StatusChip>
          <StatusChip tone="neutral" title="현재 모드">
            모드: {modeText}
          </StatusChip>
        </div>

        {/* WEB HUD 토글 */}
        <button
          type="button"
          onClick={() => onToggleHud?.()}
          className={cn(
            "ml-2 px-3 py-1 text-xs rounded-lg transition ring-1",
            hudOn
              ? "bg-primary/15 ring-primary/25 text-base-content hover:bg-primary/20"
              : "bg-base-100/35 ring-base-300/50 opacity-90 hover:opacity-100 hover:bg-base-100/50"
          )}
          title="Toggle WEB HUD"
        >
          HUD: {hudOn ? "ON" : "OFF"}
        </button>

        {/* OS HUD 토글 */}
        <button
          type="button"
          onClick={() => onToggleOsHud?.()}
          className={cn(
            "px-3 py-1 text-xs rounded-lg transition ring-1",
            osHudOn
              ? "bg-primary/10 ring-primary/20 text-base-content hover:bg-primary/15"
              : "bg-base-100/35 ring-base-300/50 opacity-90 hover:opacity-100 hover:bg-base-100/50"
          )}
          title="Toggle OS HUD"
        >
          OS HUD: {osHudOn ? "ON" : "OFF"}
        </button>
      </div>

      {/* RIGHT */}
      <div className="ml-auto flex items-center gap-2" style={{ WebkitAppRegion: "no-drag" }}>
        <button
          ref={btnRef}
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "btn btn-sm rounded-lg",
            "bg-base-100/35 border border-base-300/60",
            "hover:bg-base-100/55",
            "text-base-content"
          )}
          aria-expanded={open}
        >
          <span className="text-xs opacity-70 mr-2">Theme</span>
          <span className="text-xs font-semibold">{currentThemeLabel}</span>
          <span className="ml-2 opacity-60">▾</span>
        </button>

        {ThemePopover}

        <div className="flex items-center gap-2">
          <button className="w-10 h-8 rounded-md hover:bg-base-300/40" onClick={onMin} title="Minimize">
            —
          </button>
          <button className="w-10 h-8 rounded-md hover:bg-base-300/40" onClick={onMax} title="Maximize">
            □
          </button>
          <button className="w-10 h-8 rounded-md hover:bg-error/25" onClick={onClose} title="Close">
            ×
          </button>
        </div>
      </div>
    </div>
  );
}
