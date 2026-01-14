// src/components/TitleBar.jsx
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

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

  const currentThemeLabel =
    THEME_PRESETS.find((t) => t.id === theme)?.label ?? theme ?? "dark";

  // =========================
  // Theme Select Popover (Portal)
  // - overflow-hidden에 안 잘리게 fixed + portal
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

    // 오른쪽 정렬 느낌으로: 버튼 right에 맞춰서 팝오버 배치
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
    // 스크롤 컨테이너가 뭘지 몰라서 capture로 받음
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
      {/* LEFT: Logo + Title + Tabs + HUD */}
      <div className="flex items-center gap-3">
        <div className="w-6 h-6 rounded-md bg-base-300/40 ring-1 ring-base-300/60 flex items-center justify-center text-xs font-bold">
          GA
        </div>
        <span className="font-semibold text-sm">Gesture Agent Manager</span>

        {/* 화면 전환 탭 */}
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

        {/* HUD 토글 */}
        <button
          type="button"
          onClick={() => onToggleHud?.()}
          className={cn(
            "ml-1 px-3 py-1 text-xs rounded-lg transition ring-1",
            hudOn
              ? "bg-primary/15 ring-primary/25 text-base-content hover:bg-primary/20"
              : "bg-base-100/35 ring-base-300/50 opacity-90 hover:opacity-100 hover:bg-base-100/50"
          )}
          title="Toggle HUD"
        >
          HUD: {hudOn ? "ON" : "OFF"}
        </button>
      </div>

      {/* RIGHT: Theme select + Window controls */}
      <div
        className="ml-auto flex items-center gap-2"
        style={{ WebkitAppRegion: "no-drag" }}
      >
        {/* ✅ Theme Select (Portal Popover) */}
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

        {/* Window Controls */}
        <div className="flex items-center gap-2">
          <button
            className="w-10 h-8 rounded-md hover:bg-base-300/40"
            onClick={onMin}
            title="Minimize"
          >
            —
          </button>
          <button
            className="w-10 h-8 rounded-md hover:bg-base-300/40"
            onClick={onMax}
            title="Maximize"
          >
            □
          </button>
          <button
            className="w-10 h-8 rounded-md hover:bg-error/25"
            onClick={onClose}
            title="Close"
          >
            ×
          </button>
        </div>
      </div>
    </div>
  );
}
