import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import GestureSettingsPanel from "./GestureSettingsPanel";
// ✅ PNG 대신 SVG 로고 컴포넌트로 교체 (여백/테두리 문제 해결)
// import gaLogo from "../assets/ga-logo.png";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function safeContains(el, target) {
  return !!el && !!target && el.contains(target);
}

function StatusChip({ tone = "neutral", children, title }) {
  const base =
    "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] leading-none ring-1 select-none";

  // ✅ warn(카메라 미연결) 톤 추가 + 기존 톤은 그대로
  const toneCls =
    tone === "ok"
      ? "bg-emerald-500/10 ring-emerald-400/25 text-base-content"
      : tone === "bad"
        ? "bg-rose-500/10 ring-rose-400/25 text-base-content"
        : tone === "warn"
          ? "bg-fuchsia-500/12 ring-fuchsia-400/30 text-base-content"
          : "bg-base-100/20 ring-base-300/50 text-base-content opacity-95";

  return (
    <span className={cn(base, toneCls)} title={title}>
      {children}
    </span>
  );
}

/* =========================
   Brand Logo (SVG)
   - No outer border/box
   - Bigger, tighter fill
========================= */
function LogoMark({ className = "" }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="gaGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#22d3ee" />
          <stop offset="1" stopColor="#3b82f6" />
        </linearGradient>

        <filter id="gaGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.4" result="b" />
          <feColorMatrix
            in="b"
            type="matrix"
            values="
              0 0 0 0 0.10
              0 0 0 0 0.75
              0 0 0 0 1.00
              0 0 0 0.80 0
            "
            result="c"
          />
          <feMerge>
            <feMergeNode in="c" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Subtle slash */}
      <path
        d="M9 50 C20 43, 34 40, 56 39"
        fill="none"
        stroke="url(#gaGrad)"
        strokeWidth="3.3"
        strokeLinecap="round"
        opacity="0.75"
      />

      {/* GA */}
      <g filter="url(#gaGlow)">
        <text
          x="7"
          y="44"
          fontSize="38"
          fontFamily="ui-sans-serif, system-ui, Inter, Arial"
          fontWeight="900"
          letterSpacing="-2"
          fill="url(#gaGrad)"
        >
          GA
        </text>
      </g>

      {/* Pixel sparks */}
      <rect
        x="49.5"
        y="10"
        width="4.2"
        height="4.2"
        rx="1.1"
        fill="#22d3ee"
        opacity="0.98"
      />
      <rect
        x="55.2"
        y="14"
        width="3.2"
        height="3.2"
        rx="1"
        fill="#60a5fa"
        opacity="0.9"
      />
      <rect
        x="47.6"
        y="16.2"
        width="2.6"
        height="2.6"
        rx="0.9"
        fill="#93c5fd"
        opacity="0.78"
      />
    </svg>
  );
}

/* =========================
   Small Icons
========================= */
function IconChevronDown() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      className="opacity-70"
    >
      <path
        d="m6 9 6 6 6-6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function IconGrid() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      className="opacity-85"
    >
      <path d="M4 4h7v7H4V4Z" stroke="currentColor" strokeWidth="1.6" />
      <path d="M13 4h7v7h-7V4Z" stroke="currentColor" strokeWidth="1.6" />
      <path d="M4 13h7v7H4v-7Z" stroke="currentColor" strokeWidth="1.6" />
      <path d="M13 13h7v7h-7v-7Z" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}
function IconTraining() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      className="opacity-85"
    >
      <path
        d="M4 19V5m0 14h16"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M8 15l3-3 2 2 5-6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function IconBolt() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      className="opacity-85"
    >
      <path
        d="M13 2 3 14h8l-1 8 10-12h-8l1-8Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function IconPhone() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      className="opacity-85"
    >
      <path
        d="M8 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M11 18h2"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function TabBtn({ active, children, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg px-3 py-2 text-xs font-semibold ring-1 transition",
        active
          ? "bg-base-100/35 ring-base-300/70"
          : "bg-base-100/15 ring-base-300/45 opacity-90 hover:opacity-100 hover:bg-base-100/25",
      )}
    >
      <span className="whitespace-nowrap">{children}</span>
    </button>
  );
}

function ToggleRow({ title, desc, checked, onToggle }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl ring-1 ring-base-300/45 bg-base-100/12 px-4 py-3">
      <div className="min-w-0">
        <div className="text-sm font-semibold whitespace-nowrap">{title}</div>
        <div className="text-[11px] opacity-70 truncate">{desc}</div>
      </div>
      <input
        type="checkbox"
        className="toggle toggle-sm"
        checked={!!checked}
        onChange={onToggle}
      />
    </div>
  );
}

function MenuItem({ active, icon, title, sub, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-lg px-3 py-2 ring-1 transition",
        "flex items-center gap-3",
        active
          ? "bg-base-100/30 ring-base-300/70"
          : "bg-base-100/10 ring-base-300/45 hover:bg-base-100/20",
      )}
    >
      <div
        className={cn(
          "h-9 w-9 rounded-lg ring-1 grid place-items-center shrink-0",
          active
            ? "bg-primary/10 ring-primary/25"
            : "bg-base-100/10 ring-base-300/45",
        )}
      >
        {icon}
      </div>

      <div className="min-w-0">
        <div className="text-sm font-semibold whitespace-nowrap">{title}</div>
        {sub ? (
          <div className="text-[11px] opacity-70 truncate">{sub}</div>
        ) : null}
      </div>

      {active ? (
        <span className="ml-auto text-[11px] font-semibold opacity-70 whitespace-nowrap">
          현재
        </span>
      ) : (
        <span className="ml-auto opacity-40">›</span>
      )}
    </button>
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
  onOpenPairing,
  agentStatus,
}) {
  const onMin = () =>
    window.managerWin &&
    window.managerWin.minimize &&
    window.managerWin.minimize();
  const onMax = () =>
    window.managerWin &&
    window.managerWin.toggleMaximize &&
    window.managerWin.toggleMaximize();
  const onClose = () =>
    window.managerWin && window.managerWin.close && window.managerWin.close();

  const THEME_PRESETS = useMemo(
    () => [
      { id: "dark", label: "다크" },
      { id: "light", label: "라이트" },
      { id: "neon", label: "네온" },
      { id: "rose", label: "로즈" },
      { id: "devil", label: "데빌" },
    ],
    [],
  );

  const MODE_LABEL = useMemo(
    () => ({
      MOUSE: "마우스",
      PRESENTATION: "프레젠테이션",
      DRAW: "그리기",
      RUSH: "러쉬",
      VKEY: "가상키보드",
      KEYBOARD: "키보드",
      DEFAULT: "기본",
    }),
    [],
  );

  const SCREEN_LABEL = useMemo(
    () => ({
      dashboard: "Dashboard",
      train: "Training",
      rush: "Rush",
      settings: "Settings",
    }),
    [],
  );

  const currentThemeLabel =
    (THEME_PRESETS.find((t) => t.id === theme) || {}).label || theme || "dark";

  const connected = !!(agentStatus && agentStatus.connected);
  const locked = !!(agentStatus && agentStatus.locked);

  // ✅ Dashboard -> onHudState 로 올라온 cameraPresent를 agentStatus에 태워서 여기서 표시
  const cameraPresent = agentStatus ? agentStatus.cameraPresent : undefined;

  const modeText =
    (agentStatus && agentStatus.modeText) ||
    MODE_LABEL[(agentStatus && agentStatus.mode) || "DEFAULT"] ||
    (agentStatus && agentStatus.mode) ||
    "-";

  // Theme popover
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);
  const popRef = useRef(null);
  const [pos, setPos] = useState({ top: 48, left: 0, width: 220 });

  // Settings popover + 탭
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState("motion"); // 'display' | 'motion'
  const gearBtnRef = useRef(null);
  const settingsPopRef = useRef(null);
  const [settingsPos, setSettingsPos] = useState({
    top: 48,
    left: 0,
    width: 860,
  });

  // Menu popover
  const [menuOpen, setMenuOpen] = useState(false);
  const menuBtnRef = useRef(null);
  const menuPopRef = useRef(null);
  const [menuPos, setMenuPos] = useState({ top: 48, left: 0, width: 320 });

  const calcPos = () => {
    const el = btnRef.current;
    if (!el) return;

    const r = el.getBoundingClientRect();
    const margin = 8;
    const width = Math.max(200, r.width + 40);

    const desiredLeft = r.right - width;
    const left = Math.max(
      margin,
      Math.min(desiredLeft, window.innerWidth - width - margin),
    );
    const top = Math.min(r.bottom + margin, window.innerHeight - margin);

    setPos({ top, left, width });
  };

  const calcSettingsPos = () => {
    const el = gearBtnRef.current;
    if (!el) return;

    const r = el.getBoundingClientRect();
    const margin = 10;

    // ✅ 설정 모달: 더 크게, 더 쓰기 편하게
    const ideal = Math.min(
      980,
      Math.max(760, Math.round(window.innerWidth * 0.78)),
    );
    const width = Math.max(
      640,
      Math.min(ideal, window.innerWidth - margin * 2),
    );

    const desiredLeft = r.right - width;
    const left = Math.max(
      margin,
      Math.min(desiredLeft, window.innerWidth - width - margin),
    );
    const top = Math.min(r.bottom + margin, window.innerHeight - margin);

    setSettingsPos({ top, left, width });
  };

  const calcMenuPos = () => {
    const el = menuBtnRef.current;
    if (!el) return;

    const r = el.getBoundingClientRect();
    const margin = 8;
    const width = 320;

    const desiredLeft = r.left;
    const left = Math.max(
      margin,
      Math.min(desiredLeft, window.innerWidth - width - margin),
    );
    const top = Math.min(r.bottom + margin, window.innerHeight - margin);

    setMenuPos({ top, left, width });
  };

  // Theme popover events
  useEffect(() => {
    if (!open) return;
    calcPos();

    const onDown = (e) => {
      const t = e.target;
      if (safeContains(btnRef.current, t) || safeContains(popRef.current, t))
        return;
      setOpen(false);
    };
    const onKey = (e) => e.key === "Escape" && setOpen(false);
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

  // Settings popover events
  useEffect(() => {
    if (!settingsOpen) return;
    calcSettingsPos();

    const onDown = (e) => {
      const t = e.target;
      if (
        safeContains(gearBtnRef.current, t) ||
        safeContains(settingsPopRef.current, t)
      )
        return;
      setSettingsOpen(false);
    };
    const onKey = (e) => e.key === "Escape" && setSettingsOpen(false);
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

  // Menu popover events
  useEffect(() => {
    if (!menuOpen) return;
    calcMenuPos();

    const onDown = (e) => {
      const t = e.target;
      if (
        safeContains(menuBtnRef.current, t) ||
        safeContains(menuPopRef.current, t)
      )
        return;
      setMenuOpen(false);
    };
    const onKey = (e) => e.key === "Escape" && setMenuOpen(false);
    const onResize = () => calcMenuPos();
    const onScroll = () => calcMenuPos();

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
  }, [menuOpen]);

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
            WebkitAppRegion: "no-drag",
          }}
          className={cn(
            "no-drag",  
            "rounded-xl shadow-2xl ring-1",
            "bg-base-200/95 text-base-content border border-base-300/60",
            "backdrop-blur-md",
            "p-2",
          )}
        >
          <div className="text-[11px] px-2 py-1 opacity-70">Theme</div>
          <ul className="menu menu-sm w-full">
            {THEME_PRESETS.map((tItem) => {
              const active = tItem.id === theme;
              return (
                <li key={tItem.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setTheme && setTheme(tItem.id);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex items-center justify-between rounded-lg",
                      active ? "active font-semibold" : "",
                    )}
                  >
                    <span className="whitespace-nowrap">{tItem.label}</span>
                    {active ? <span className="opacity-70">✓</span> : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>,
        document.body,
      )
    : null;

  const MenuPopover = menuOpen
    ? createPortal(
        <div
          ref={menuPopRef}
          style={{
            position: "fixed",
            top: menuPos.top,
            left: menuPos.left,
            width: menuPos.width,
            zIndex: 99999,
            WebkitAppRegion: "no-drag",
          }}
          className={cn(
            "no-drag", 
            "rounded-xl shadow-2xl ring-1",
            "bg-base-200/92 text-base-content border border-base-300/60",
            "backdrop-blur-md",
            "p-3",
          )}
        >
          <div className="text-[11px] px-1 py-1 opacity-70">메뉴</div>

          <div className="mt-2 space-y-2">
            <MenuItem
              active={screen === "dashboard"}
              icon={<IconGrid />}
              title="Dashboard"
              sub="상태/모드/컨트롤"
              onClick={() => {
                onChangeScreen && onChangeScreen("dashboard");
                setMenuOpen(false);
              }}
            />
            <MenuItem
              active={screen === "train"}
              icon={<IconTraining />}
              title="Training"
              sub="랜드마크/학습/프로필"
              onClick={() => {
                onChangeScreen && onChangeScreen("train");
                setMenuOpen(false);
              }}
            />
            <MenuItem
              active={screen === "rush"}
              icon={<IconBolt />}
              title="Rush"
              sub="러쉬 UI"
              onClick={() => {
                onChangeScreen && onChangeScreen("rush");
                setMenuOpen(false);
              }}
            />
          </div>

          <div className="my-3 h-px bg-base-300/55" />

          <MenuItem
            active={false}
            icon={<IconPhone />}
            title="휴대폰 연결"
            sub="QR 페어링"
            onClick={() => {
              onOpenPairing && onOpenPairing();
              setMenuOpen(false);
            }}
          />
        </div>,
        document.body,
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
            height: "min(90vh, 860px)",
            zIndex: 99999,
            WebkitAppRegion: "no-drag",
          }}
          className={cn(
            "no-drag",
            "rounded-xl shadow-2xl ring-1",
            "bg-base-200/92 text-base-content border border-base-300/60",
            "backdrop-blur-md",
            "overflow-hidden",
            "flex flex-col",
          )}
        >
          {/* Header + Tabs */}
          <div className="p-4 border-b border-base-300/45 bg-base-100/8">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-base font-semibold whitespace-nowrap">
                  설정
                </div>
                <div className="text-[12px] opacity-70 mt-0.5 truncate">
                  표시 옵션 / 모션(제스처) 세팅
                </div>
              </div>

              <button
                type="button"
                className={cn(
                  "h-9 w-9 grid place-items-center rounded-lg ring-1",
                  "bg-base-100/18 ring-base-300/55",
                  "hover:bg-base-100/30 transition",
                )}
                onClick={() => setSettingsOpen(false)}
                title="닫기"
              >
                ×
              </button>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
              <TabBtn
                active={settingsTab === "display"}
                onClick={() => setSettingsTab("display")}
              >
                표시 설정
              </TabBtn>
              <TabBtn
                active={settingsTab === "motion"}
                onClick={() => setSettingsTab("motion")}
              >
                모션 세팅
              </TabBtn>
            </div>
          </div>

          {/* Body */}
          {settingsTab === "display" ? (
            <div className="flex-1 min-h-0 overflow-auto p-4">
              <div className="rounded-xl ring-1 ring-base-300/45 bg-base-100/10 p-4">
                <div className="text-sm font-semibold">
                  HUD 표시 옵션 (WEB/OS)
                </div>
                <div className="text-[12px] opacity-70 mt-1">
                  자주 쓰는 토글은 여기서만 관리
                </div>

                <div className="mt-4 space-y-3">
                  <ToggleRow
                    title="WEB HUD"
                    desc="웹 오버레이 HUD 표시"
                    checked={hudOn}
                    onToggle={() => onToggleHud && onToggleHud()}
                  />
                  <ToggleRow
                    title="OS HUD"
                    desc="OS 커서/오버레이 HUD 표시"
                    checked={osHudOn}
                    onToggle={() => onToggleOsHud && onToggleOsHud()}
                  />
                </div>
              </div>

              <div className="mt-4 text-[11px] opacity-60">
                팁: HUD는 CPU/GPU 부하가 생길 수 있으니 필요할 때만 켜는 것을
                권장합니다.
              </div>
            </div>
          ) : (
            <div className="flex-1 min-h-0">
              <GestureSettingsPanel
                theme={theme}
                embedded
                onRequestClose={() => setSettingsOpen(false)}
              />
            </div>
          )}
        </div>,
        document.body,
      )
    : null;

  const currentPageLabel = SCREEN_LABEL[screen] || "Dashboard";

  return (
    <div
      className={cn(
        // ✅ 타이틀바 확 키움
        "navbar h-14 px-4 select-none titlebar-drag",
        "border-b border-base-300/45",
        "bg-base-200/78 backdrop-blur-md",
        "text-base-content",
      )}
      onDoubleClick={onMax}
    >
      {/* LEFT */}
      <div className="flex items-center gap-3 min-w-0">
        {/* ✅ 로고: 더 크고, 테두리/원형 없음 */}
        <div className="w-14 h-14 flex items-center justify-center shrink-0 overflow-hidden">
          <LogoMark className="w-12 h-12 pointer-events-none" />
        </div>

        <span className="font-semibold text-[15px] whitespace-nowrap">
          Gesture Agent Manager
        </span>

        {/* PAGE dropdown */}
        <button
          ref={menuBtnRef}
          type="button"
          onClick={() => {
            setOpen(false);
            setSettingsOpen(false);
            setMenuOpen((v) => !v);
          }}
          className={cn(
            "btn btn-sm rounded-lg",
            "bg-base-100/18 border border-base-300/55",
            "hover:bg-base-100/28",
            "text-base-content",
          )}
          aria-expanded={menuOpen}
          title="메뉴"
          style={{ WebkitAppRegion: "no-drag" }}
        >
          <span className="inline-flex items-center gap-2 whitespace-nowrap">
            <span className="text-[11px] opacity-70">PAGE</span>
            <span className="text-xs font-semibold">{currentPageLabel}</span>
            <IconChevronDown />
          </span>
        </button>

        {MenuPopover}

        {/* 상태 칩 */}
        <div className="ml-1 flex items-center gap-1.5 min-w-0">
          <StatusChip
            tone={connected ? "ok" : "bad"}
            title="에이전트 연결 상태"
          >
            {connected ? "연결됨" : "끊김"}
          </StatusChip>

          <StatusChip tone={locked ? "bad" : "ok"} title="제스처 잠금 상태">
            {locked ? "잠금" : "해제"}
          </StatusChip>
          {/* ✅ 사진처럼: 카메라 미연결일 때만 상단에 표시 */}
          {cameraPresent === false ? (
            <StatusChip tone="warn" title="카메라 연결 상태">
              카메라 미연결
            </StatusChip>
          ) : null}
          <StatusChip tone="neutral" title="현재 모드">
            모드: {modeText}
          </StatusChip>
        </div>
      </div>

      {/* RIGHT */}
      <div
        className="ml-auto flex items-center gap-2"
        style={{ WebkitAppRegion: "no-drag" }}
      >
        <button
          ref={gearBtnRef}
          type="button"
          onClick={() => {
            setOpen(false);
            setMenuOpen(false);
            setSettingsTab("motion");
            setSettingsOpen((v) => !v);
          }}
          className={cn(
            "btn btn-sm rounded-lg",
            "bg-base-100/18 border border-base-300/55",
            "hover:bg-base-100/28",
            "text-base-content",
          )}
          aria-expanded={settingsOpen}
          title="설정"
        >
          <span className="text-xs font-semibold whitespace-nowrap">설정</span>
        </button>

        {SettingsPopover}

        <button
          ref={btnRef}
          type="button"
          onClick={() => {
            setMenuOpen(false);
            setOpen((v) => !v);
          }}
          className={cn(
            "btn btn-sm rounded-lg",
            "bg-base-100/18 border border-base-300/55",
            "hover:bg-base-100/28",
            "text-base-content",
          )}
          aria-expanded={open}
          title="테마"
        >
          <span className="text-[11px] opacity-70 mr-2 whitespace-nowrap">
            Theme
          </span>
          <span className="text-xs font-semibold whitespace-nowrap">
            {currentThemeLabel}
          </span>
          <span className="ml-2 opacity-60">▾</span>
        </button>

        {ThemePopover}

        <div className="flex items-center gap-2">
          <button
            className="no-drag w-10 h-8 rounded-md hover:bg-base-300/30"
            onClick={onMin}
            title="Minimize"
          >
            —
          </button>
          <button
            className="no-drag w-10 h-8 rounded-md hover:bg-base-300/30"
            onClick={onMax}
            title="Maximize"
          >
            □
          </button>
          <button
            className="no-drag w-10 h-8 rounded-md hover:bg-error/20"
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
