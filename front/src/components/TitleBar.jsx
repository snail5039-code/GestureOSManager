import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import GestureSettingsPanel from "./GestureSettingsPanel";

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

  // =========================
  // Settings Popover (Gear)
  // =========================
  const [settingsOpen, setSettingsOpen] = useState(false);
  const gearBtnRef = useRef(null);
  const settingsPopRef = useRef(null);
  const [settingsPos, setSettingsPos] = useState({ top: 48, left: 0, width: 640 });

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

  const calcSettingsPos = () => {
    const el = gearBtnRef.current;
    if (!el) return;

    const r = el.getBoundingClientRect();
    const margin = 10;
    // 화면이 작을 때도 넘치지 않게 clamp
    const ideal = Math.min(760, Math.max(380, Math.round(window.innerWidth * 0.62)));
    const width = Math.max(320, Math.min(ideal, window.innerWidth - margin * 2));

    // 오른쪽 정렬 느낌(기어 버튼 기준으로)
    const desiredLeft = r.right - width;
    const left = Math.max(margin, Math.min(desiredLeft, window.innerWidth - width - margin));
    const top = Math.min(r.bottom + margin, window.innerHeight - margin);

    setSettingsPos({ top, left, width });
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

  useEffect(() => {
    if (!settingsOpen) return;
    calcSettingsPos();

    const onDown = (e) => {
      const t = e.target;
      const btn = gearBtnRef.current;
      const pop = settingsPopRef.current;
      if (!btn || !pop) return;
      if (btn.contains(t) || pop.contains(t)) return;
      setSettingsOpen(false);
    };

    const onKey = (e) => {
      if (e.key === "Escape") setSettingsOpen(false);
    };

    const onResize = () => calcSettingsPos();
    const onScroll = () => calcSettingsPos();

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
  }, [settingsOpen]);

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

  const SettingsPopover = settingsOpen
    ? createPortal(
        <div
          ref={settingsPopRef}
          style={{
            position: "fixed",
            top: settingsPos.top,
            left: settingsPos.left,
            width: settingsPos.width,
            zIndex: 99999,
          }}
          className={cn(
            "rounded-2xl shadow-2xl ring-1",
            "bg-base-200/90 text-base-content border border-base-300/60",
            "backdrop-blur",
            "overflow-hidden"
          )}
        >
          <GestureSettingsPanel
            theme={theme}
            embedded
            onRequestClose={() => setSettingsOpen(false)}
          />
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

          {/* 설정은 오른쪽 기어(⚙)로 이동 */}
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
        {/* Settings (Gear) */}
        <button
          ref={gearBtnRef}
          type="button"
          onClick={() => {
            // 둘 다 열릴 필요 없음
            setOpen(false);
            setSettingsOpen((v) => !v);
          }}
          className={cn(
            "btn btn-sm rounded-lg",
            "bg-base-100/35 border border-base-300/60",
            "hover:bg-base-100/55",
            "text-base-content"
          )}
          aria-expanded={settingsOpen}
          title="제스처 설정"
        >
          <span className="inline-flex items-center gap-2">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="opacity-80"
            >
              <path
                d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"
                stroke="currentColor"
                strokeWidth="1.8"
              />
              <path
                d="M19.4 15a8.3 8.3 0 0 0 .1-6l-2.1-.8a6.8 6.8 0 0 0-1.2-2.1l1-2a8.3 8.3 0 0 0-5.2-2.2l-.7 2.2a6.7 6.7 0 0 0-2.4 0L8.2 1.9A8.3 8.3 0 0 0 3 4.1l1 2a6.8 6.8 0 0 0-1.2 2.1L.7 9a8.3 8.3 0 0 0 .1 6l2.1.8a6.8 6.8 0 0 0 1.2 2.1l-1 2A8.3 8.3 0 0 0 8.2 22l.7-2.2a6.7 6.7 0 0 0 2.4 0L12 22a8.3 8.3 0 0 0 5.2-2.2l-1-2a6.8 6.8 0 0 0 1.2-2.1l2-.7Z"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinejoin="round"
                opacity="0.9"
              />
            </svg>
            <span className="text-xs font-semibold">설정</span>
          </span>
        </button>

        {SettingsPopover}

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
