// src/pages/Dashboard.jsx
import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { THEME } from "../theme/themeTokens";

const POLL_MS = 500;

const MODE_OPTIONS = ["MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "VKEY"];

const MODE_LABEL = {
  MOUSE: "마우스",
  KEYBOARD: "키보드",
  PRESENTATION: "프레젠테이션",
  DRAW: "그리기",
  VKEY: "가상키보드",
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
      <path d="M8 11V8a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <path d="M7 11h10v10H7V11Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}
function IconChevron() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="opacity-85">
      <path d="m9 6 6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* =========================
   Theme-aware UI blocks
========================= */
function Badge({ t, children, tone = "slate" }) {
  const map = {
    slate: cn(t.chip, t.text2, "ring-1"),
    blue: cn("bg-sky-500/12 ring-sky-400/25", t.text2, "ring-1"),
    green: cn("bg-emerald-500/12 ring-emerald-400/25", t.text2, "ring-1"),
    yellow: cn("bg-amber-500/14 ring-amber-400/25", t.text2, "ring-1"),
    red: cn("bg-rose-500/12 ring-rose-400/25", t.text2, "ring-1"),
  };
  return <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs", map[tone] || map.slate)}>{children}</span>;
}

function Card({ t, title, right, children, accent = "slate" }) {
  const topLine = {
    slate: "from-slate-400/18 via-transparent to-transparent",
    blue: "from-sky-400/20 via-transparent to-transparent",
    green: "from-emerald-400/20 via-transparent to-transparent",
    red: "from-rose-400/20 via-transparent to-transparent",
    yellow: "from-amber-400/20 via-transparent to-transparent",
  };

  const isBright = t._isBright ?? false;
  const shadow = isBright
    ? "shadow-[0_10px_30px_rgba(15,23,42,0.08)]"
    : "shadow-[0_12px_40px_rgba(0,0,0,0.25)]";

  return (
    <div className={cn("rounded-2xl ring-1 overflow-hidden", t.panel, shadow, "transition-transform duration-200 hover:-translate-y-[1px]")}>
      <div className={cn("h-px w-full bg-gradient-to-r", topLine[accent] || topLine.slate)} />
      <div className={cn("flex items-center justify-between px-5 py-4 border-b", isBright ? "border-slate-200" : "border-white/10")}>
        <div className={cn("text-sm font-semibold", t.text)}>{title}</div>
        {right}
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

function Btn({ t, className, ...props }) {
  return (
    <button
      className={cn(
        "w-full rounded-2xl py-3 text-sm font-semibold ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed",
        t.btn,
        className
      )}
      {...props}
    />
  );
}

function ActionTile({ t, tone = "slate", icon, title, desc, className, ...props }) {
  const isBright = t._isBright ?? false;

  const map = {
    slate: cn(isBright ? "bg-white" : "bg-white/5", isBright ? "ring-slate-200" : "ring-white/12"),
    green: cn("bg-emerald-500/8", isBright ? "ring-emerald-300/70" : "ring-emerald-400/25"),
    red: cn("bg-rose-500/8", isBright ? "ring-rose-300/70" : "ring-rose-400/25"),
    blue: cn("bg-sky-500/8", isBright ? "ring-sky-300/70" : "ring-sky-400/25"),
  };

  const chipMap = {
    slate: cn(t.chip),
    green: cn("bg-emerald-500/10", isBright ? "ring-emerald-300/70" : "ring-emerald-400/25"),
    red: cn("bg-rose-500/10", isBright ? "ring-rose-300/70" : "ring-rose-400/25"),
    blue: cn("bg-sky-500/10", isBright ? "ring-sky-300/70" : "ring-sky-400/25"),
  };

  return (
    <button
      className={cn(
        "w-full rounded-2xl p-4 ring-1 transition text-left disabled:opacity-50 disabled:cursor-not-allowed",
        isBright ? "shadow-[0_10px_30px_rgba(15,23,42,0.08)]" : "shadow-[0_10px_35px_rgba(0,0,0,0.25)]",
        map[tone] || map.slate,
        className
      )}
      {...props}
    >
      <div className="flex items-center gap-3">
        <div className={cn("h-11 w-11 rounded-2xl ring-1 grid place-items-center", chipMap[tone] || chipMap.slate)}>
          <div className={cn(t.text)}>{icon}</div>
        </div>

        <div className="min-w-0">
          <div className={cn("text-sm font-semibold", t.text)}>{title}</div>
          <div className={cn("text-xs mt-0.5 truncate", t.muted)}>{desc}</div>
        </div>

        <div className={cn("ml-auto", t.muted2)}>
          <IconChevron />
        </div>
      </div>
    </button>
  );
}

function Switch({ t, checked, onChange, disabled }) {
  const isBright = t._isBright ?? false;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 items-center rounded-full ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed",
        checked
          ? "bg-sky-500/25 ring-sky-300/70"
          : isBright
          ? "bg-slate-200 ring-slate-300"
          : "bg-slate-800/70 ring-white/12"
      )}
      aria-checked={checked}
      role="switch"
    >
      <span className={cn("inline-block h-5 w-5 transform rounded-full bg-white transition", checked ? "translate-x-5" : "translate-x-1")} />
    </button>
  );
}

function StatTile({ t, label, value, tone = "slate" }) {
  const isBright = t._isBright ?? false;

  const ring =
    tone === "green"
      ? isBright ? "ring-emerald-300/70" : "ring-emerald-400/25"
      : tone === "blue"
      ? isBright ? "ring-sky-300/70" : "ring-sky-400/25"
      : tone === "yellow"
      ? isBright ? "ring-amber-300/70" : "ring-amber-400/25"
      : tone === "red"
      ? isBright ? "ring-rose-300/70" : "ring-rose-400/25"
      : isBright ? "ring-slate-200" : "ring-white/12";

  return (
    <div className={cn("rounded-xl ring-1 p-3 overflow-hidden", t.panelSoft, ring)}>
      <div className={cn("mt-1 text-xs", t.muted)}>{label}</div>
      <div className={cn("mt-1 font-semibold text-sm", t.text)}>{value}</div>
    </div>
  );
}

function PointerMiniMap({ t, theme, x, y }) {
  const cx = clamp01(x);
  const cy = clamp01(y);

  const left = cx === null ? 50 : cx * 100;
  const top = cy === null ? 50 : cy * 100;

  const isBright = t._isBright ?? false;
  const forceWhiteMap = theme === "rose" || theme === "kuromi";

  return (
    <div className={cn("rounded-xl ring-1 p-3 overflow-hidden", t.panelSoft, isBright ? "ring-slate-200" : "ring-white/12")}>
      <div className="flex items-center justify-between">
        <div className={cn("text-xs", t.muted)}>포인터</div>
        <div className={cn("text-xs tabular-nums", t.muted)}>
          {cx === null ? "-" : cx.toFixed(3)} / {cy === null ? "-" : cy.toFixed(3)}
        </div>
      </div>

      <div
        className={cn(
          "mt-3 relative h-20 rounded-lg ring-1 overflow-hidden",
          forceWhiteMap
            ? "bg-white ring-violet-200"
            : isBright
            ? "bg-white ring-slate-200"
            : "bg-slate-900/35 ring-white/12"
        )}
      >
        <div className="absolute inset-0 opacity-[0.18]">
          <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(15,23,42,.08)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,.08)_1px,transparent_1px)] bg-[size:16px_16px]" />
        </div>

        <div
          className={cn("absolute h-2.5 w-2.5 rounded-full", t.dot)}
          style={{ left: `${left}%`, top: `${top}%`, transform: "translate(-50%,-50%)" }}
        />
      </div>
    </div>
  );
}

/* =========================
   Dashboard
========================= */
export default function Dashboard({ onHudState, onHudActions, theme = "dark" } = {}) {
  const [status, setStatus] = useState(null);
  const [mode, setMode] = useState("MOUSE");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const t = THEME[theme] || THEME.dark;

  const [preview, setPreview] = useState(false);
  const previewRef = useRef(false);
  const previewBusyRef = useRef(false);

  const abortRef = useRef(null);
  const pollTimerRef = useRef(null);
  const unmountedRef = useRef(false);

  const [showRaw, setShowRaw] = useState(false);
  const [copied, setCopied] = useState(false);

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
      tracking: typeof s.tracking === "boolean" ? s.tracking : (typeof s.isTracking === "boolean" ? s.isTracking : null),
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
        if (!derived.enabled) {
          await api.post("/control/start");
        }
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
    [fetchStatus, derived.enabled]
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

  useEffect(() => {
    onHudActions?.({ start, stop, applyMode, togglePreview, fetchStatus, setLock });
  }, [onHudActions, start, stop, applyMode, togglePreview, fetchStatus, setLock]);

  // ✅ TitleBar에서 쓰게: 연결/잠금/모드까지 올려줌
  useEffect(() => {
    onHudState?.({
      status,
      connected: derived.connected,
      locked: derived.locked,
      mode: derived.mode,
      modeText: view.modeText,
      modeOptions: MODE_OPTIONS,
    });
  }, [onHudState, status, derived.connected, derived.locked, derived.mode, view.modeText]);

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

  const canStart = !busy && !derived.enabled;
  const canStop = !busy && !!derived.enabled;

  const isBright = theme === "light" || theme === "rose";

  return (
    <div className={cn("w-full h-full min-h-0 relative", t.page)}>

      {/* ✅ 기존 sticky Topbar(조잡한 상태바) 삭제됨 */}

      {/* Content */}
      <div className="relative w-full max-w-none px-6 py-6 space-y-5">
        {error ? (
          <div
            className={cn(
              "rounded-2xl ring-1 px-5 py-4 text-sm",
              isBright ? "bg-rose-50 ring-rose-200 text-slate-900" : "bg-rose-950/30 ring-rose-900/60 text-rose-100"
            )}
          >
            {error}
          </div>
        ) : null}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* left */}
          <div className="lg:col-span-5 space-y-5">
            <Card t={t} title="모드" accent="blue">
              <div className="space-y-3">
                <select
                  value={mode}
                  onChange={(e) => applyMode(e.target.value)}
                  disabled={busy}
                  className={cn(
                    "w-full rounded-xl ring-1 px-3 py-2 text-sm outline-none focus:ring-2 disabled:opacity-50",
                    t.input,
                    isBright ? "focus:ring-sky-400/40" : "focus:ring-sky-500/45"
                  )}
                >
                  {MODE_OPTIONS.map((m) => (
                    <option key={m} value={m}>
                      {MODE_LABEL[m] ?? m}
                    </option>
                  ))}
                </select>
              </div>
            </Card>

            <Card
              t={t}
              title="빠른 동작"
              accent="green"
              right={busy ? <Badge t={t} tone="blue">처리 중</Badge> : <Badge t={t} tone="slate">대기</Badge>}
            >
              <div className="grid grid-cols-2 gap-3">
                <ActionTile t={t} tone="green" icon={<IconPlay />} title="시작" desc="Start" onClick={start} disabled={!canStart} />
                <ActionTile t={t} tone="red" icon={<IconStop />} title="정지" desc="Stop" onClick={stop} disabled={!canStop} />
              </div>

              <div className={cn("mt-4 rounded-2xl ring-1 p-4 space-y-3", t.panelSoft)}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={cn(t.text2)}><IconEye /></span>
                    <div>
                      <div className={cn("text-sm font-semibold", t.text)}>프리뷰</div>
                      <div className={cn("text-xs", t.muted)}>카메라/랜드마크 미리보기</div>
                    </div>
                  </div>
                  <Switch t={t} checked={preview} onChange={() => togglePreview()} disabled={busy} />
                </div>

                <div className={cn("h-px", t.divider)} />

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={cn(t.text2)}><IconLock /></span>
                    <div>
                      <div className={cn("text-sm font-semibold", t.text)}>잠금</div>
                      <div className={cn("text-xs", t.muted)}>제스처 입력 잠금/해제</div>
                    </div>
                  </div>
                  <Switch t={t} checked={derived.locked} onChange={(v) => setLock(!!v)} disabled={busy} />
                </div>
              </div>

              <Btn t={t} onClick={fetchStatus} disabled={busy} className="mt-4 flex items-center justify-center gap-2">
                <IconRefresh spinning={busy} />
                새로고침
              </Btn>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <StatTile t={t} label="FPS" value={formatNum(derived.fps, 1)} tone="blue" />
                <StatTile t={t} label="현재 제스처" value={derived.gesture} tone="slate" />
              </div>
            </Card>
          </div>

          {/* right */}
          <div className="lg:col-span-7 space-y-5">
            <Card
              t={t}
              title="상태"
              accent="blue"
              right={loading ? <Badge t={t} tone="yellow">불러오는 중</Badge> : <Badge t={t} tone="slate">라이브</Badge>}
            >
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <StatTile t={t} label="연결" value={view.connText} tone={derived.connected ? "blue" : "red"} />
                <StatTile t={t} label="실행" value={view.enabledText} tone={derived.enabled ? "green" : "slate"} />
                <StatTile t={t} label="잠금" value={view.lockText} tone={derived.locked ? "yellow" : "slate"} />

                <StatTile t={t} label="이동" value={view.moveText} tone={derived.canMove ? "green" : "slate"} />
                <StatTile t={t} label="클릭" value={view.clickText} tone={derived.canClick ? "green" : "slate"} />
                <StatTile t={t} label="스크롤" value={view.scrollText} tone={derived.scrollActive ? "blue" : "slate"} />

                <StatTile t={t} label="트래킹" value={view.trackingText} tone={derived.tracking ? "green" : "slate"} />
                <StatTile t={t} label="포인터 X" value={derived.pointerX === null ? "-" : formatNum(derived.pointerX, 3)} tone="slate" />
                <StatTile t={t} label="포인터 Y" value={derived.pointerY === null ? "-" : formatNum(derived.pointerY, 3)} tone="slate" />
              </div>

              <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                <PointerMiniMap t={t} theme={theme} x={derived.pointerX} y={derived.pointerY} />
                <div className={cn("rounded-xl ring-1 p-3", t.panelSoft)}>
                  <div className={cn("text-xs", t.muted)}>요약</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge t={t} tone="slate">제스처: {derived.gesture}</Badge>
                    <Badge t={t} tone={preview ? "blue" : "slate"}>{preview ? "Preview ON" : "Preview OFF"}</Badge>
                    <Badge t={t} tone="slate">Mode: {view.modeText}</Badge>
                  </div>
                </div>
              </div>
            </Card>

            <Card
              t={t}
              title="Debug"
              accent="slate"
              right={
                <div className="flex items-center gap-2">
                  <button
                    className={cn("px-3 py-1.5 text-xs rounded-full ring-1 transition disabled:opacity-50", t.btn)}
                    onClick={copyRaw}
                    disabled={!status}
                    type="button"
                  >
                    {copied ? "Copied" : "Copy JSON"}
                  </button>
                  <button
                    className={cn("px-3 py-1.5 text-xs rounded-full ring-1 transition disabled:opacity-50", t.btn)}
                    onClick={() => setShowRaw((v) => !v)}
                    disabled={loading}
                    type="button"
                  >
                    {showRaw ? "Hide Raw" : "Show Raw"}
                  </button>
                </div>
              }
            >
              {showRaw ? (
                <pre className={cn("text-xs leading-relaxed overflow-auto max-h-96 rounded-xl ring-1 p-4", t.panelSolid || t.panel2 || t.panel, t.input)}>
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
