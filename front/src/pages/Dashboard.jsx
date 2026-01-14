// Dashboard.jsx
import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const POLL_MS = 500;

// 서버에 보내는 mode 값(영문)은 그대로, UI 표시는 한글로
const MODE_OPTIONS = ["MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "RUSH", "VKEY", "DEFAULT"];
const MODE_LABEL = {
  MOUSE: "마우스",
  KEYBOARD: "키보드",
  PRESENTATION: "프레젠테이션",
  DRAW: "그리기",
  RUSH: "러쉬",
  VKEY: "가상 키보드",
  DEFAULT: "기본",
};

const api = axios.create({
  baseURL: "/api",
  timeout: 5000,
  headers: { Accept: "application/json" },
});

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function clamp01(v) {
  if (typeof v !== "number" || Number.isNaN(v)) return null;
  return Math.max(0, Math.min(1, v));
}

function Badge({ children, tone = "slate" }) {
  const map = {
    slate: "bg-slate-800/65 text-slate-200 ring-white/10",
    blue: "bg-sky-500/16 text-sky-200 ring-sky-400/25",
    green: "bg-emerald-500/16 text-emerald-200 ring-emerald-400/25",
    yellow: "bg-amber-500/16 text-amber-200 ring-amber-400/25",
    red: "bg-rose-500/16 text-rose-200 ring-rose-400/25",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs ring-1", map[tone] || map.slate)}>
      {children}
    </span>
  );
}

function Card({ title, right, children, accent = "slate" }) {
  const accentMap = {
    slate: "from-white/10 via-white/0 to-white/0",
    blue: "from-sky-400/22 via-sky-400/0 to-white/0",
    green: "from-emerald-400/22 via-emerald-400/0 to-white/0",
    red: "from-rose-400/22 via-rose-400/0 to-white/0",
    yellow: "from-amber-400/22 via-amber-400/0 to-white/0",
  };

  const glowMap = {
    slate: "shadow-[0_12px_40px_rgba(0,0,0,0.30)]",
    blue: "shadow-[0_16px_55px_rgba(56,189,248,0.10)]",
    green: "shadow-[0_16px_55px_rgba(52,211,153,0.08)]",
    red: "shadow-[0_16px_55px_rgba(244,63,94,0.08)]",
    yellow: "shadow-[0_16px_55px_rgba(251,191,36,0.07)]",
  };

  return (
    <div
      className={cn(
        "rounded-2xl bg-slate-950/45 ring-1 ring-white/10 overflow-hidden",
        glowMap[accent] || glowMap.slate,
        "transition-transform duration-200 hover:-translate-y-[1px]"
      )}
    >
      <div className={cn("h-px w-full bg-gradient-to-r", accentMap[accent] || accentMap.slate)} />
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
        <div className="text-sm font-semibold text-slate-100 tracking-tight">{title}</div>
        {right}
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

function Btn({ tone = "slate", className, ...props }) {
  const map = {
    slate: "bg-slate-800/85 hover:bg-slate-700 text-slate-100",
    blue: "bg-sky-600/90 hover:bg-sky-600 text-white",
    green: "bg-emerald-600/90 hover:bg-emerald-600 text-white",
    red: "bg-rose-600/90 hover:bg-rose-600 text-white",
  };
  return (
    <button
      className={cn(
        "rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition",
        map[tone] || map.slate,
        className
      )}
      {...props}
    />
  );
}

function formatNum(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "-";
  return Number(n).toFixed(digits);
}

/* =========================
   Icons (SVG)
========================= */
function IconPlay() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="opacity-90">
      <path d="M8 5v14l12-7-12-7Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}
function IconStop() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="opacity-90">
      <path d="M7 7h10v10H7V7Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}
function IconRefresh({ spinning }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      className={cn("opacity-90", spinning && "animate-spin")}
    >
      <path
        d="M20 12a8 8 0 1 1-2.34-5.66M20 4v6h-6"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function IconEye() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="opacity-90">
      <path
        d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" stroke="currentColor" strokeWidth="1.7" />
    </svg>
  );
}
function IconLock() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="opacity-90">
      <path
        d="M8 11V8a4 4 0 0 1 8 0v3"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
      <path d="M7 11h10v10H7V11Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}
function IconChevron() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="opacity-85">
      <path
        d="m9 6 6 6-6 6"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* =========================
   Action Tile
========================= */
function ActionTile({ tone = "slate", icon, title, desc, className, ...props }) {
  const map = {
    slate: "bg-gradient-to-b from-white/6 to-white/0 hover:from-white/9 ring-white/10",
    green: "bg-gradient-to-b from-emerald-400/14 to-white/0 hover:from-emerald-400/18 ring-emerald-400/25",
    red: "bg-gradient-to-b from-rose-400/14 to-white/0 hover:from-rose-400/18 ring-rose-400/25",
    blue: "bg-gradient-to-b from-sky-400/14 to-white/0 hover:from-sky-400/18 ring-sky-400/25",
  };

  const chipMap = {
    slate: "bg-slate-950/45 ring-white/10",
    green: "bg-emerald-950/35 ring-emerald-400/20",
    red: "bg-rose-950/35 ring-rose-400/20",
    blue: "bg-sky-950/35 ring-sky-400/20",
  };

  return (
    <button
      className={cn(
        "w-full rounded-2xl p-4 ring-1 transition text-left disabled:opacity-50 disabled:cursor-not-allowed",
        "shadow-[0_10px_35px_rgba(0,0,0,0.25)] hover:shadow-[0_16px_50px_rgba(0,0,0,0.35)]",
        map[tone] || map.slate,
        className
      )}
      {...props}
    >
      <div className="flex items-center gap-3">
        <div className={cn("h-11 w-11 rounded-2xl ring-1 grid place-items-center", chipMap[tone] || chipMap.slate)}>
          <div className="text-slate-100">{icon}</div>
        </div>

        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-100">{title}</div>
          <div className="text-xs text-slate-300/80 mt-0.5 truncate">{desc}</div>
        </div>

        <div className="ml-auto text-slate-300/60">
          <IconChevron />
        </div>
      </div>
    </button>
  );
}

/* =========================
   Switch
========================= */
function Switch({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 items-center rounded-full ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed",
        checked ? "bg-sky-500/30 ring-sky-400/30" : "bg-slate-800/70 ring-white/10"
      )}
      aria-checked={checked}
      role="switch"
    >
      <span
        className={cn(
          "inline-block h-5 w-5 transform rounded-full bg-white/90 transition",
          checked ? "translate-x-5" : "translate-x-1"
        )}
      />
    </button>
  );
}

function StatTile({ label, value, tone = "slate" }) {
  const ring =
    tone === "green"
      ? "ring-emerald-400/22"
      : tone === "blue"
      ? "ring-sky-400/22"
      : tone === "yellow"
      ? "ring-amber-400/22"
      : tone === "red"
      ? "ring-rose-400/22"
      : "ring-white/10";

  const topGlow =
    tone === "green"
      ? "from-emerald-400/20"
      : tone === "blue"
      ? "from-sky-400/20"
      : tone === "yellow"
      ? "from-amber-400/18"
      : tone === "red"
      ? "from-rose-400/18"
      : "from-white/10";

  return (
    <div className={cn("rounded-xl bg-slate-950/45 ring-1 p-3 overflow-hidden", ring)}>
      <div className={cn("h-px w-full bg-gradient-to-r", topGlow, "via-white/0 to-white/0")} />
      <div className="mt-2 text-xs text-slate-400">{label}</div>
      <div className="mt-1 font-semibold text-sm text-slate-100">{value}</div>
    </div>
  );
}

function PointerMiniMap({ x, y }) {
  const cx = clamp01(x);
  const cy = clamp01(y);

  const left = cx === null ? 50 : cx * 100;
  const top = cy === null ? 50 : cy * 100;

  return (
    <div className="rounded-xl bg-slate-950/45 ring-1 ring-white/10 p-3 overflow-hidden">
      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-400">포인터</div>
        <div className="text-xs text-slate-400 tabular-nums">
          {cx === null ? "-" : cx.toFixed(3)} / {cy === null ? "-" : cy.toFixed(3)}
        </div>
      </div>

      <div className="mt-3 relative h-20 rounded-lg bg-slate-900/35 ring-1 ring-white/10 overflow-hidden">
        <div className="absolute inset-0 opacity-[0.20]">
          <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,.08)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,.08)_1px,transparent_1px)] bg-[size:16px_16px]" />
        </div>

        <div
          className="absolute h-2.5 w-2.5 rounded-full bg-sky-300 shadow-[0_0_18px_rgba(56,189,248,0.65)]"
          style={{ left: `${left}%`, top: `${top}%`, transform: "translate(-50%,-50%)" }}
        />
      </div>
    </div>
  );
}

export default function Dashboard({ hudOn, onToggleHud, onHudState, onHudActions } = {}) {
  const [status, setStatus] = useState(null);
  const [mode, setMode] = useState("MOUSE");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [preview, setPreview] = useState(false);
  const previewRef = useRef(false);
  const previewBusyRef = useRef(false);

  const abortRef = useRef(null);
  const pollTimerRef = useRef(null);
  const unmountedRef = useRef(false);

  // Debug
  const [showRaw, setShowRaw] = useState(false);
  const [copied, setCopied] = useState(false);

  /* =========================
     OS HUD (Windows OverlayHUD) Controls
  ========================= */
  const [osHudOn, setOsHudOn] = useState(() => {
    const v = localStorage.getItem("osHudOn");
    return v === null ? true : v === "1";
  });
  const [osHudBusy, setOsHudBusy] = useState(false);

  const [hudStep, setHudStep] = useState(() => {
    const v = Number(localStorage.getItem("osHudStep") ?? 20);
    return Number.isFinite(v) ? v : 20;
  });

  const osHudSyncedRef = useRef(false);

  useEffect(() => {
    localStorage.setItem("osHudOn", osHudOn ? "1" : "0");
  }, [osHudOn]);

  useEffect(() => {
    localStorage.setItem("osHudStep", String(hudStep));
  }, [hudStep]);

  const postHud = useCallback(
    async (path, params) => {
      setOsHudBusy(true);
      setError("");
      try {
        await api.post(path, null, { params });
      } catch (e) {
        const msg = e?.response
          ? `HUD 요청 실패: ${path} (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || `HUD 요청 실패: ${path}`;
        setError(msg);
        throw e;
      } finally {
        setOsHudBusy(false);
      }
    },
    [setError]
  );

  const setOsHudVisible = useCallback(
    async (next) => {
      const prev = osHudOn;
      setOsHudOn(!!next);
      try {
        await postHud("/hud/show", { enabled: !!next });
      } catch {
        setOsHudOn(prev);
      }
    },
    [osHudOn, postHud]
  );

  const nudgeOsHud = useCallback(async (dx, dy) => {
    await postHud("/hud/nudge", { dx: Math.trunc(dx), dy: Math.trunc(dy) });
  }, [postHud]);

  const resetOsHudPos = useCallback(async () => {
    await postHud("/hud/resetpos", {});
  }, [postHud]);

  // OS HUD 초기 1회 동기화
  useEffect(() => {
    if (osHudSyncedRef.current) return;
    osHudSyncedRef.current = true;
    api.post("/hud/show", null, { params: { enabled: osHudOn } }).catch(() => {});
  }, [osHudOn]);

  useEffect(() => {
    previewRef.current = preview;
  }, [preview]);

  const derived = useMemo(() => {
    const s = status || {};
    return {
      connected: !!s.connected,
      enabled: !!s.enabled,
      locked: !!s.locked,
      gesture: s.gesture ?? s.lastGesture ?? "NONE",
      fps: s.fps ?? s.agentFps ?? null,
      scrollActive: !!s.scrollActive,
      canMove: typeof s.canMove === "boolean" ? s.canMove : null,
      canClick: typeof s.canClick === "boolean" ? s.canClick : null,
      mode: s.mode ?? mode,
      type: s.type ?? "STATUS",
      serverPreview: typeof s.preview === "boolean" ? s.preview : undefined,
      pointerX: typeof s.pointerX === "number" ? s.pointerX : null,
      pointerY: typeof s.pointerY === "number" ? s.pointerY : null,
      tracking: typeof s.tracking === "boolean" ? s.tracking : null,
    };
  }, [status, mode]);

  const view = useMemo(() => {
    return {
      connText: derived.connected ? "연결됨" : "끊김",
      enabledText: derived.enabled ? "실행 중" : "정지",
      lockText: derived.locked ? "잠금" : "해제",
      moveText: derived.canMove === null ? "-" : derived.canMove ? "가능" : "불가",
      clickText: derived.canClick === null ? "-" : derived.canClick ? "가능" : "불가",
      scrollText: derived.scrollActive ? "활성" : "비활성",
      trackingText: derived.tracking === null ? "-" : derived.tracking ? "ON" : "OFF",
      modeText: MODE_LABEL[derived.mode] ?? derived.mode,
    };
  }, [derived]);

  const fetchStatus = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const { data } = await api.get("/control/status", { signal: controller.signal });

      setStatus(data);
      setMode((prev) => data?.mode ?? prev);

      if (typeof data?.preview === "boolean") {
        setPreview(data.preview);
        previewRef.current = data.preview;
        if (previewBusyRef.current) previewBusyRef.current = false;
      }

      setError("");
    } catch (e) {
      if (e?.name === "CanceledError" || e?.name === "AbortError") return;

      const msg = e?.response
        ? `상태 조회 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "상태 조회 실패";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const scheduleNextPoll = useCallback(() => {
    if (unmountedRef.current) return;
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    pollTimerRef.current = setTimeout(async () => {
      await fetchStatus();
      scheduleNextPoll();
    }, POLL_MS);
  }, [fetchStatus]);

  useEffect(() => {
    unmountedRef.current = false;

    (async () => {
      await fetchStatus();
      scheduleNextPoll();
    })();

    return () => {
      unmountedRef.current = true;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchStatus, scheduleNextPoll]);

  const postJson = useCallback(
    async (url, body) => {
      setBusy(true);
      setError("");
      try {
        await api.post(url, body ?? {});
        await fetchStatus();
      } catch (e) {
        const msg = e?.response
          ? `요청 실패: ${url} (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || "요청 실패";
        setError(msg);
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus]
  );

  const start = useCallback(() => postJson("/control/start"), [postJson]);
  const stop = useCallback(() => postJson("/control/stop"), [postJson]);

  const togglePreview = useCallback(async () => {
    if (previewBusyRef.current) return;

    const next = !previewRef.current;

    previewBusyRef.current = true;
    previewRef.current = next;
    setPreview(next);

    setBusy(true);
    setError("");
    try {
      await api.post("/control/preview", null, { params: { enabled: next } });
      await fetchStatus();
    } catch (e) {
      previewBusyRef.current = false;
      previewRef.current = !next;
      setPreview(!next);

      const msg = e?.response
        ? `프리뷰 변경 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "프리뷰 변경 실패";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }, [fetchStatus]);

  const applyMode = useCallback(
    async (nextMode) => {
      setMode(nextMode);
      setBusy(true);
      setError("");
      try {
        await api.post("/control/mode", null, { params: { mode: nextMode } });
        await fetchStatus();
      } catch (e) {
        const msg = e?.response
          ? `모드 변경 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || "모드 변경 실패";
        setError(msg);
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus]
  );

  const setLock = useCallback(
    async (nextLocked) => {
      setBusy(true);
      setError("");
      try {
        await api.post("/control/lock", null, { params: { enabled: !!nextLocked } });
        await fetchStatus();
      } catch (e) {
        const msg = e?.response
          ? `잠금 변경 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || "잠금 변경 실패";
        setError(msg);
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus]
  );

  // HUD 액션 전달
  useEffect(() => {
    onHudActions?.({ start, stop, applyMode, togglePreview, fetchStatus, setLock });
  }, [onHudActions, start, stop, applyMode, togglePreview, fetchStatus, setLock]);

  // HUD 표시 데이터 전달
  useEffect(() => {
    onHudState?.({ status, connected: derived.connected, modeOptions: MODE_OPTIONS });
  }, [onHudState, status, derived.connected]);

  const copyRaw = useCallback(async () => {
    try {
      const text = status ? JSON.stringify(status, null, 2) : "";
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 900);
    } catch {
      // noop
    }
  }, [status]);

  const topOk = !error;

  const canStart = !busy && !derived.enabled;
  const canStop = !busy && !!derived.enabled;

  return (
    <div className="min-h-screen relative overflow-hidden bg-[#070c16] text-slate-100">
      {/* background */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-40 -left-40 h-[520px] w-[520px] rounded-full bg-sky-500/10 blur-3xl" />
        <div className="absolute -bottom-52 -right-48 h-[560px] w-[560px] rounded-full bg-emerald-500/8 blur-3xl" />
        <div className="absolute inset-0 opacity-[0.08] bg-[linear-gradient(to_right,rgba(255,255,255,.10)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,.10)_1px,transparent_1px)] bg-[size:60px_60px]" />
      </div>

      {/* Topbar */}
      <div className="sticky top-0 z-20 border-b border-white/10 bg-gradient-to-r from-[#0b4aa2]/22 via-[#0b1220]/85 to-[#0b1220]/85 backdrop-blur">
        <div className="mx-auto max-w-[1200px] px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-2xl bg-gradient-to-b from-sky-400/20 to-sky-400/0 ring-1 ring-sky-400/20 grid place-items-center shadow-[0_0_24px_rgba(56,189,248,0.15)]">
              <span className="text-sky-200 font-bold text-sm">G</span>
            </div>
            <div className="text-base font-bold tracking-tight">GestureOSManager</div>
          </div>

          <div className="flex items-center gap-2">
            {topOk ? <Badge tone="green">정상</Badge> : <Badge tone="red">오류</Badge>}
            <Badge tone={derived.enabled ? "green" : "slate"}>{view.enabledText}</Badge>
            <Badge tone={derived.connected ? "blue" : "red"}>{view.connText}</Badge>
            <Badge tone={derived.locked ? "yellow" : "slate"}>{view.lockText}</Badge>
            <Badge tone={preview ? "blue" : "slate"}>{preview ? "프리뷰" : "노프리뷰"}</Badge>
            <Badge tone="slate">모드: {view.modeText}</Badge>

            {/* 기존(웹) HUD 토글 */}
            <button
              type="button"
              onClick={onToggleHud}
              className={cn(
                "ml-2 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ring-1 transition",
                hudOn
                  ? "bg-sky-500/15 text-sky-200 ring-sky-400/25 hover:bg-sky-500/25"
                  : "bg-slate-800/70 text-slate-200 ring-white/10 hover:bg-white/10"
              )}
              title="HUD 켬/끔"
            >
              <span className={cn("h-2 w-2 rounded-full", hudOn ? "bg-sky-300" : "bg-slate-500")} />
              HUD {hudOn ? "켬" : "끔"}
            </button>

            {/* OS HUD(파이썬 OverlayHUD) 토글 */}
            <button
              type="button"
              onClick={() => setOsHudVisible(!osHudOn)}
              disabled={osHudBusy}
              className={cn(
                "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed",
                osHudOn
                  ? "bg-emerald-500/15 text-emerald-200 ring-emerald-400/25 hover:bg-emerald-500/25"
                  : "bg-slate-800/70 text-slate-200 ring-white/10 hover:bg-white/10"
              )}
              title="윈도우 오버레이 HUD(파이썬)"
            >
              <span className={cn("h-2 w-2 rounded-full", osHudOn ? "bg-emerald-300" : "bg-slate-500")} />
              OS HUD {osHudOn ? "켬" : "끔"}
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="relative mx-auto max-w-[1200px] px-6 py-6 space-y-5">
        {error ? (
          <div className="rounded-2xl bg-rose-950/30 ring-1 ring-rose-900/60 px-5 py-4 text-sm text-rose-100 shadow-[0_18px_55px_rgba(244,63,94,0.08)]">
            {error}
          </div>
        ) : null}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* 좌 */}
          <div className="lg:col-span-5 space-y-5">
            <Card title="모드" accent="blue">
              <div className="space-y-3">
                <select
                  value={mode}
                  onChange={(e) => applyMode(e.target.value)}
                  disabled={busy}
                  className="w-full rounded-xl bg-slate-950/55 ring-1 ring-white/10 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-sky-500/45 disabled:opacity-50"
                >
                  {MODE_OPTIONS.map((m) => (
                    <option key={m} value={m}>
                      {MODE_LABEL[m] ?? m}
                    </option>
                  ))}
                </select>

                <div className="flex flex-wrap gap-2">
                  {MODE_OPTIONS.map((m) => {
                    const active = (derived.mode ?? mode) === m;
                    return (
                      <button
                        key={m}
                        onClick={() => applyMode(m)}
                        disabled={busy}
                        className={cn(
                          "px-3 py-1 rounded-full text-xs font-semibold ring-1 transition",
                          active
                            ? "bg-sky-500/18 text-sky-200 ring-sky-400/25 shadow-[0_0_20px_rgba(56,189,248,0.12)]"
                            : "bg-slate-900/35 text-slate-200 ring-white/10 hover:bg-white/5",
                          busy && "opacity-50 cursor-not-allowed"
                        )}
                      >
                        {MODE_LABEL[m] ?? m}
                      </button>
                    );
                  })}
                </div>
              </div>
            </Card>

            <Card
              title="빠른 동작"
              accent="green"
              right={busy ? <Badge tone="blue">처리 중</Badge> : <Badge tone="slate">대기</Badge>}
            >
              <div className="grid grid-cols-2 gap-3">
                <ActionTile tone="green" icon={<IconPlay />} title="시작" desc="Start" onClick={start} disabled={!canStart} />
                <ActionTile tone="red" icon={<IconStop />} title="정지" desc="Stop" onClick={stop} disabled={!canStop} />
              </div>

              <div className="mt-4 rounded-2xl bg-gradient-to-b from-white/6 to-white/0 ring-1 ring-white/10 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-slate-200">
                      <IconEye />
                    </span>
                    <div>
                      <div className="text-sm font-semibold">프리뷰</div>
                      <div className="text-xs text-slate-400">카메라/랜드마크 미리보기</div>
                    </div>
                  </div>
                  <Switch checked={preview} onChange={() => togglePreview()} disabled={busy} />
                </div>

                <div className="h-px bg-white/10" />

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-slate-200">
                      <IconLock />
                    </span>
                    <div>
                      <div className="text-sm font-semibold">잠금</div>
                      <div className="text-xs text-slate-400">제스처 입력 잠금/해제</div>
                    </div>
                  </div>
                  <Switch checked={derived.locked} onChange={(v) => setLock(!!v)} disabled={busy} />
                </div>
              </div>

              <Btn
                tone="slate"
                onClick={fetchStatus}
                disabled={busy}
                className="w-full mt-4 flex items-center justify-center gap-2 rounded-2xl py-3 bg-gradient-to-b from-white/8 to-white/0"
              >
                <IconRefresh spinning={busy} />
                새로고침
              </Btn>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <StatTile label="FPS" value={formatNum(derived.fps, 1)} tone="blue" />
                <StatTile label="현재 제스처" value={derived.gesture} tone="slate" />
              </div>
            </Card>

            {/* OS HUD Control Card */}
            <Card
              title="OS HUD(윈도우 오버레이) 위치/표시"
              accent="slate"
              right={osHudBusy ? <Badge tone="blue">처리 중</Badge> : <Badge tone="slate">컨트롤</Badge>}
            >
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold">오버레이 표시</div>
                    <div className="text-xs text-slate-400">파이썬 HUD(패널 + 레티클/말풍선)</div>
                  </div>
                  <Switch checked={osHudOn} onChange={setOsHudVisible} disabled={osHudBusy} />
                </div>

                <div className="h-px bg-white/10" />

                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs text-slate-400">이동 step(px)</div>
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={hudStep}
                    onChange={(e) => setHudStep(Math.max(1, Number(e.target.value) || 1))}
                    className="w-28 rounded-xl bg-slate-950/55 ring-1 ring-white/10 px-3 py-2 text-sm outline-none"
                    disabled={osHudBusy}
                  />
                </div>

                <div className="grid grid-cols-3 gap-2 w-[240px] mx-auto">
                  <div />
                  <Btn tone="slate" className="w-full px-0 py-2 rounded-xl" onClick={() => nudgeOsHud(0, -hudStep)} disabled={osHudBusy}>
                    ▲
                  </Btn>
                  <div />

                  <Btn tone="slate" className="w-full px-0 py-2 rounded-xl" onClick={() => nudgeOsHud(-hudStep, 0)} disabled={osHudBusy}>
                    ◀
                  </Btn>

                  <Btn tone="blue" className="w-full px-0 py-2 rounded-xl" onClick={resetOsHudPos} disabled={osHudBusy}>
                    Reset
                  </Btn>

                  <Btn tone="slate" className="w-full px-0 py-2 rounded-xl" onClick={() => nudgeOsHud(hudStep, 0)} disabled={osHudBusy}>
                    ▶
                  </Btn>

                  <div />
                  <Btn tone="slate" className="w-full px-0 py-2 rounded-xl" onClick={() => nudgeOsHud(0, hudStep)} disabled={osHudBusy}>
                    ▼
                  </Btn>
                  <div />
                </div>
              </div>
            </Card>
          </div>

          {/* 우 */}
          <div className="lg:col-span-7 space-y-5">
            <Card
              title="상태"
              accent="blue"
              right={loading ? <Badge tone="yellow">불러오는 중</Badge> : <Badge tone="slate">라이브</Badge>}
            >
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <StatTile label="연결" value={view.connText} tone={derived.connected ? "blue" : "red"} />
                <StatTile label="실행" value={view.enabledText} tone={derived.enabled ? "green" : "slate"} />
                <StatTile label="잠금" value={view.lockText} tone={derived.locked ? "yellow" : "slate"} />

                <StatTile label="이동" value={view.moveText} tone={derived.canMove ? "green" : "slate"} />
                <StatTile label="클릭" value={view.clickText} tone={derived.canClick ? "green" : "slate"} />
                <StatTile label="스크롤" value={view.scrollText} tone={derived.scrollActive ? "blue" : "slate"} />

                <StatTile label="트래킹" value={view.trackingText} tone={derived.tracking ? "green" : "slate"} />
                <StatTile label="포인터 X" value={derived.pointerX === null ? "-" : formatNum(derived.pointerX, 3)} tone="slate" />
                <StatTile label="포인터 Y" value={derived.pointerY === null ? "-" : formatNum(derived.pointerY, 3)} tone="slate" />
              </div>

              <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                <PointerMiniMap x={derived.pointerX} y={derived.pointerY} />
                <div className="rounded-xl bg-slate-950/45 ring-1 ring-white/10 p-3">
                  <div className="text-xs text-slate-400">요약</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge tone="slate">제스처: {derived.gesture}</Badge>
                    <Badge tone={preview ? "blue" : "slate"}>{preview ? "Preview ON" : "Preview OFF"}</Badge>
                    <Badge tone="slate">Mode: {view.modeText}</Badge>
                  </div>
                </div>
              </div>
            </Card>

            <Card
              title="Debug"
              accent="slate"
              right={
                <div className="flex items-center gap-2">
                  <Btn tone="slate" className="px-3 py-1.5 text-xs rounded-full" onClick={copyRaw} disabled={!status}>
                    {copied ? "Copied" : "Copy JSON"}
                  </Btn>
                  <Btn
                    tone="slate"
                    className="px-3 py-1.5 text-xs rounded-full"
                    onClick={() => setShowRaw((v) => !v)}
                    disabled={loading}
                  >
                    {showRaw ? "Hide Raw" : "Show Raw"}
                  </Btn>
                </div>
              }
            >
              {showRaw ? (
                <pre className="text-xs leading-relaxed overflow-auto max-h-96 rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-4">
                  {status ? JSON.stringify(status, null, 2) : loading ? "Loading..." : "No data"}
                </pre>
              ) : (
                <div className="h-2" />
              )}
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
