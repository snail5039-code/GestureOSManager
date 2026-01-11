import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const POLL_MS = 500;
const MODE_OPTIONS = ["MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "DEFAULT"];

const api = axios.create({
  baseURL: "/api",
  timeout: 5000,
  headers: { Accept: "application/json" },
});

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function Badge({ children, tone = "slate" }) {
  const map = {
    slate: "bg-slate-800/80 text-slate-200 ring-slate-700/60",
    blue: "bg-sky-900/40 text-sky-200 ring-sky-800/60",
    green: "bg-emerald-900/35 text-emerald-200 ring-emerald-800/60",
    yellow: "bg-amber-900/35 text-amber-200 ring-amber-800/60",
    red: "bg-rose-900/35 text-rose-200 ring-rose-800/60",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs ring-1",
        map[tone] || map.slate
      )}
    >
      {children}
    </span>
  );
}

function Card({ title, right, children }) {
  return (
    <div className="rounded-2xl bg-slate-950/40 ring-1 ring-white/10 shadow-sm">
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
        <div className="text-sm font-semibold text-slate-100">{title}</div>
        {right}
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

function Btn({ tone = "slate", className, ...props }) {
  const map = {
    slate: "bg-slate-800 hover:bg-slate-700 text-slate-100",
    blue: "bg-sky-600/90 hover:bg-sky-600 text-white",
    green: "bg-emerald-600/90 hover:bg-emerald-600 text-white",
    red: "bg-rose-600/90 hover:bg-rose-600 text-white",
  };
  return (
    <button
      className={cn(
        "rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed",
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

function IconGrid() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      className="text-sky-200"
    >
      <path
        d="M4 8.5h4v4H4v-4Zm6 0h4v4h-4v-4Zm6 0h4v4h-4v-4ZM4 14.5h4v4H4v-4Zm6 0h10v4H10v-4Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

export default function Dashboard({
  hudOn,
  onToggleHud,
  onHudState,
  onHudActions,
} = {}) {
  const [status, setStatus] = useState(null);
  const [mode, setMode] = useState("MOUSE");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [preview, setPreview] = useState(false);
  const abortRef = useRef(null);

  const derived = useMemo(() => {
    const s = status || {};
    return {
      connected: !!s.connected,
      enabled: !!s.enabled,
      locked: !!s.locked,
      gesture: s.gesture ?? s.lastGesture ?? "NONE",
      fps: s.fps ?? s.agentFps ?? null,
      scrollActive: !!s.scrollActive,
      canMove: s.canMove ?? null,
      canClick: s.canClick ?? null,
      mode: s.mode ?? mode,
      type: s.type ?? "STATUS",
    };
  }, [status, mode]);

  const fetchStatus = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const { data } = await api.get("/control/status", {
        signal: controller.signal,
      });

      console.log("[STATUS]", data);

      setStatus(data);
      setMode((prev) => data?.mode ?? prev);
      setLastUpdated(new Date());
      setError("");
    } catch (e) {
      if (e?.name === "CanceledError" || e?.name === "AbortError") return;

      const msg = e?.response
        ? `STATUS HTTP ${e.response.status}${e.response.data ? `: ${String(e.response.data)}` : ""
        }`
        : e?.message || "STATUS fetch failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const postJson = useCallback(
    async (url, body) => {
      setBusy(true);
      setError("");
      try {
        await api.post(url, body ?? {});
        await fetchStatus();
      } catch (e) {
        const msg = e?.response
          ? `${url} HTTP ${e.response.status}${e.response.data ? `: ${String(e.response.data)}` : ""
          }`
          : e?.message || "POST failed";
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
    const next = !preview;
    setBusy(true);
    setError("");
    try {
      await api.post("/control/preview", null, { params: { enabled: next } });
      setPreview(next);
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `/control/preview HTTP ${e.response.status}${e.response.data ? `: ${String(e.response.data)}` : ""
        }`
        : e?.message || "PREVIEW failed";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }, [preview, fetchStatus]);

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
          ? `/control/mode HTTP ${e.response.status}${e.response.data ? `: ${String(e.response.data)}` : ""
          }`
          : e?.message || "MODE failed";
        setError(msg);
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus]
  );

  // ✅ Lock: "권장"은 setLock(nextLocked) 형태 (HUD에서 next를 넘겨줌)
  const setLock = useCallback(
    async (nextLocked) => {
      setBusy(true);
      setError("");
      try {
        // 백엔드가 이 엔드포인트를 아직 안 만들면 404가 뜸 (지금 너 상황)
        await api.post("/control/lock", null, {
          params: { enabled: !!nextLocked },
        });
        await fetchStatus();
      } catch (e) {
        const msg = e?.response
          ? `/control/lock HTTP ${e.response.status}${e.response.data ? `: ${String(e.response.data)}` : ""
          }`
          : e?.message || "LOCK failed";
        setError(msg);
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus]
  );

  // ✅ 대안: 토글 방식도 같이 제공(필요시 사용)
  const lockToggle = useCallback(
    () => setLock(!derived.locked),
    [setLock, derived.locked]
  );

  // ✅ App(HUD)에 “액션” 전달
  useEffect(() => {
    onHudActions?.({
      start,
      stop,
      applyMode,
      togglePreview,
      fetchStatus,
      setLock,
      lockToggle,
    });
  }, [
    onHudActions,
    start,
    stop,
    applyMode,
    togglePreview,
    fetchStatus,
    setLock,
    lockToggle,
  ]);

  // ✅ App(HUD)에 “표시 데이터” 전달
  useEffect(() => {
    onHudState?.({
      status, // raw 그대로
      connected: derived.connected,
      modeOptions: MODE_OPTIONS,
    });
  }, [onHudState, status, derived.connected]);

  // 최초 폴링
  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, POLL_MS);
    return () => {
      clearInterval(t);
      if (abortRef.current) abortRef.current.abort();
    };
  }, [fetchStatus]);

  return (
    <div className="min-h-screen bg-[#0b1220] text-slate-100">
      {/* Topbar */}
      <div className="sticky top-0 z-20 border-b border-white/10 bg-gradient-to-r from-[#0b4aa2]/40 via-[#0b1220]/80 to-[#0b1220]/80 backdrop-blur">
        <div className="mx-auto max-w-[1200px] px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-sky-500/20 ring-1 ring-sky-400/30 grid place-items-center">
              <IconGrid />
            </div>
            <div>
              <div className="text-base font-bold tracking-tight">
                Gesture Agent Manager
              </div>
              <div className="text-xs text-slate-300/80">
                REST polling {POLL_MS}ms ·{" "}
                {lastUpdated
                  ? `Last: ${lastUpdated.toLocaleTimeString()}`
                  : "—"}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {error ? (
              <Badge tone="red">ERROR</Badge>
            ) : (
              <Badge tone="green">OK</Badge>
            )}
            <Badge tone={derived.enabled ? "green" : "slate"}>
              {derived.enabled ? "ENABLED" : "DISABLED"}
            </Badge>
            <Badge tone={derived.locked ? "yellow" : "slate"}>
              {derived.locked ? "LOCKED" : "UNLOCKED"}
            </Badge>
            <Badge tone={preview ? "blue" : "slate"}>
              {preview ? "PREVIEW" : "NO PREVIEW"}
            </Badge>
            <button
              type="button"
              onClick={onToggleHud}
              className={cn(
                "ml-2 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ring-1 transition",
                hudOn
                  ? "bg-sky-500/15 text-sky-200 ring-sky-400/25 hover:bg-sky-500/25"
                  : "bg-slate-800/70 text-slate-200 ring-white/10 hover:bg-white/10"
              )}
              title="HUD On/Off"
            >
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  hudOn ? "bg-sky-300" : "bg-slate-500"
                )}
              />
              HUD {hudOn ? "ON" : "OFF"}
            </button>
            <div className="ml-2 h-9 w-9 rounded-full bg-slate-800/80 ring-1 ring-white/10 grid place-items-center text-xs font-semibold">
              P
            </div>
          </div>
        </div>
      </div>

      {/* Main Layout */}
      <div className="mx-auto max-w-[1200px] px-6 py-6 grid grid-cols-12 gap-5">
        {/* Sidebar */}
        <aside className="col-span-12 lg:col-span-3 space-y-5">
          <div className="rounded-2xl bg-slate-950/35 ring-1 ring-white/10 overflow-hidden">
            <div className="px-5 py-4 border-b border-white/10">
              <div className="text-sm font-semibold">Navigation</div>
              <div className="text-xs text-slate-400 mt-1">Manager Shell</div>
            </div>

            <nav className="p-2">
              {[
                { k: "dashboard", label: "Dashboard", active: true },
                { k: "profiles", label: "Profiles", active: false },
                { k: "settings", label: "Settings", active: false },
              ].map((it) => (
                <div
                  key={it.k}
                  className={cn(
                    "flex items-center justify-between rounded-xl px-4 py-3 text-sm cursor-default",
                    it.active
                      ? "bg-sky-500/15 ring-1 ring-sky-400/20"
                      : "hover:bg-white/5"
                  )}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={cn(
                        "h-2.5 w-2.5 rounded-full",
                        it.active ? "bg-sky-300" : "bg-slate-600"
                      )}
                    />
                    <span className="text-slate-100">{it.label}</span>
                  </div>
                  {it.active ? <Badge tone="blue">ACTIVE</Badge> : null}
                </div>
              ))}
            </nav>

            <div className="px-5 py-4 border-t border-white/10">
              <div className="text-xs text-slate-400">
                다음 단계에서 react-router로 실제 라우팅 붙이면 됨.
              </div>
            </div>
          </div>

          {/* Quick Actions */}
          <Card
            title="Quick Actions"
            right={
              busy ? (
                <Badge tone="blue">BUSY</Badge>
              ) : (
                <Badge tone="slate">READY</Badge>
              )
            }
          >
            <div className="flex flex-wrap gap-2">
              <Btn tone="green" onClick={start} disabled={busy}>
                Start
              </Btn>
              <Btn tone="red" onClick={stop} disabled={busy}>
                Stop
              </Btn>
              <Btn tone="slate" onClick={fetchStatus} disabled={busy}>
                Refresh
              </Btn>
              <Btn tone="blue" onClick={togglePreview} disabled={busy}>
                {preview ? "Preview OFF" : "Preview ON"}
              </Btn>

              {/* ✅ Lock 토글(백엔드 구현 필요) */}
              <Btn tone="slate" onClick={lockToggle} disabled={busy}>
                Lock 토글
              </Btn>
            </div>

            {error ? (
              <div className="mt-3 text-xs text-rose-200 bg-rose-950/40 ring-1 ring-rose-900/60 rounded-xl p-3">
                {error}
              </div>
            ) : null}

            <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-3">
                <div className="text-slate-400">fps</div>
                <div className="mt-1 font-semibold">
                  {formatNum(derived.fps, 1)}
                </div>
              </div>
              <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-3">
                <div className="text-slate-400">gesture</div>
                <div className="mt-1 font-semibold">{derived.gesture}</div>
              </div>
            </div>

            <div className="mt-4 text-xs text-slate-400">
              Start/Stop:{" "}
              <span className="text-slate-200">POST /api/control/start</span>,{" "}
              <span className="text-slate-200">POST /api/control/stop</span>
            </div>
          </Card>
        </aside>

        {/* Main Content */}
        <main className="col-span-12 lg:col-span-9 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <Card title="Mode">
              <div className="flex items-center gap-3">
                <select
                  value={mode}
                  onChange={(e) => applyMode(e.target.value)}
                  disabled={busy}
                  className="w-full rounded-xl bg-slate-950/60 ring-1 ring-white/10 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-sky-500/50 disabled:opacity-50"
                >
                  {MODE_OPTIONS.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <Badge tone="slate">current: {derived.mode}</Badge>
                <Badge tone="slate">type: {derived.type}</Badge>
              </div>

              <div className="mt-4 text-xs text-slate-400">
                Mode 변경:{" "}
                <span className="text-slate-200">POST /api/control/mode</span>{" "}
                {"{ mode }"}
              </div>
            </Card>

            <Card
              title="Connection"
              right={
                loading ? (
                  <Badge tone="yellow">LOADING</Badge>
                ) : (
                  <Badge tone="slate">LIVE</Badge>
                )
              }
            >
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-3">
                  <div className="text-xs text-slate-400">connected</div>
                  <div className="mt-1 font-semibold">
                    {String(derived.connected)}
                  </div>
                </div>
                <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-3">
                  <div className="text-xs text-slate-400">fps</div>
                  <div className="mt-1 font-semibold">
                    {formatNum(derived.fps, 1)}
                  </div>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Badge tone={error ? "red" : "green"}>
                  {error ? "DEGRADED" : "HEALTHY"}
                </Badge>
                <Badge tone={derived.scrollActive ? "blue" : "slate"}>
                  scrollActive: {String(derived.scrollActive)}
                </Badge>
              </div>

              <div className="mt-4 text-xs text-slate-400">
                connected/fps는 백엔드 필드명에 따라 표시(없으면 기본값).
              </div>
            </Card>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <Card title="Agent State">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-3">
                  <div className="text-xs text-slate-400">enabled</div>
                  <div className="mt-1 font-semibold">
                    {String(derived.enabled)}
                  </div>
                </div>
                <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-3">
                  <div className="text-xs text-slate-400">locked</div>
                  <div className="mt-1 font-semibold">
                    {String(derived.locked)}
                  </div>
                </div>
                <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-3">
                  <div className="text-xs text-slate-400">canMove</div>
                  <div className="mt-1 font-semibold">
                    {derived.canMove === null ? "-" : String(derived.canMove)}
                  </div>
                </div>
                <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-3">
                  <div className="text-xs text-slate-400">canClick</div>
                  <div className="mt-1 font-semibold">
                    {derived.canClick === null ? "-" : String(derived.canClick)}
                  </div>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Badge tone="slate">gesture: {derived.gesture}</Badge>
                <Badge tone={derived.enabled ? "green" : "slate"}>
                  enabled: {String(derived.enabled)}
                </Badge>
                <Badge tone={derived.locked ? "yellow" : "slate"}>
                  locked: {String(derived.locked)}
                </Badge>
              </div>
            </Card>

            <Card title="Containers (Docker-style list)">
              <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 overflow-hidden">
                <div className="grid grid-cols-12 px-4 py-3 text-xs text-slate-300 border-b border-white/10">
                  <div className="col-span-6">NAME</div>
                  <div className="col-span-3">STATUS</div>
                  <div className="col-span-3 text-right">METRIC</div>
                </div>

                <div className="grid grid-cols-12 px-4 py-3 text-sm items-center">
                  <div className="col-span-6 flex items-center gap-3">
                    <span
                      className={cn(
                        "h-2.5 w-2.5 rounded-full",
                        derived.enabled ? "bg-emerald-400" : "bg-slate-600"
                      )}
                    />
                    <div>
                      <div className="font-semibold">gesture-agent</div>
                      <div className="text-xs text-slate-400">
                        mode: {derived.mode}
                      </div>
                    </div>
                  </div>

                  <div className="col-span-3 flex items-center gap-2">
                    <Badge tone={derived.enabled ? "green" : "slate"}>
                      {derived.enabled ? "running" : "stopped"}
                    </Badge>
                    <Badge tone={derived.locked ? "yellow" : "slate"}>
                      {derived.locked ? "locked" : "unlocked"}
                    </Badge>
                  </div>

                  <div className="col-span-3 text-right">
                    <div className="text-xs text-slate-400">fps</div>
                    <div className="font-semibold">
                      {formatNum(derived.fps, 1)}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-12 px-4 py-3 text-sm items-center border-t border-white/10">
                  <div className="col-span-6 flex items-center gap-3">
                    <span
                      className={cn(
                        "h-2.5 w-2.5 rounded-full",
                        derived.scrollActive ? "bg-sky-300" : "bg-slate-600"
                      )}
                    />
                    <div>
                      <div className="font-semibold">scroll-module</div>
                      <div className="text-xs text-slate-400">
                        gesture: FIST (assist hand)
                      </div>
                    </div>
                  </div>

                  <div className="col-span-3">
                    <Badge tone={derived.scrollActive ? "blue" : "slate"}>
                      {derived.scrollActive ? "active" : "idle"}
                    </Badge>
                  </div>

                  <div className="col-span-3 text-right">
                    <div className="text-xs text-slate-400">gesture</div>
                    <div className="font-semibold">{derived.gesture}</div>
                  </div>
                </div>
              </div>

              <div className="mt-4 text-xs text-slate-400">
                발표용 “도커 리스트 느낌” 더미 UI. 실제 컨테이너가 아니라 상태
                기반 표시.
              </div>
            </Card>
          </div>

          <Card
            title="Raw Status JSON"
            right={
              loading ? (
                <Badge tone="yellow">LOADING</Badge>
              ) : (
                <Badge tone="slate">LIVE</Badge>
              )
            }
          >
            <pre className="text-xs leading-relaxed overflow-auto max-h-80 rounded-xl bg-slate-950/50 ring-1 ring-white/10 p-4">
              {status
                ? JSON.stringify(status, null, 2)
                : loading
                  ? "Loading..."
                  : "No data"}
            </pre>
          </Card>
        </main>
      </div>
    </div>
  );
}
