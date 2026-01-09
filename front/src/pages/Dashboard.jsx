import axios from "axios";
import { useEffect, useMemo, useRef, useState } from "react";

/**
 * ===========================================
 * Dashboard.jsx
 * - Spring REST Polling 기반으로 Agent 상태를 받아와서 화면에 표시
 * - Start/Stop, Mode 변경, Preview 토글까지 제어 가능
 * - 여기에 "HUD(항상 떠있는 상태판)" + "모드 선택 오버레이"를 추가한 버전
 * ===========================================
 */

const POLL_MS = 500;

// 백엔드 mode 값과 맞추세요
const MODE_OPTIONS = ["MOUSE", "PRESENTATION", "DRAW", "DEFAULT"];

// axios 인스턴스 (vite proxy: /api -> http://localhost:8080)
const api = axios.create({
  baseURL: "/api",
  timeout: 5000,
  headers: { Accept: "application/json" },
});

/** tailwind class join helper */
function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

/**
 * 작은 배지 UI
 * - 화면에서 상태(OK/ERROR, ENABLED 등) 표시용
 */
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

/**
 * 카드 UI (제목 + 우측 컴포넌트 + 내용)
 */
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

/**
 * 버튼 UI
 */
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

/**
 * ===========================================
 * HUD용 작은 Pill UI (항상 떠있는 상태판에서 사용)
 * ===========================================
 */
function Pill({ label, value, tone = "slate" }) {
  const toneMap = {
    slate: "bg-slate-800/70 text-slate-100 border-slate-600/40",
    green: "bg-emerald-700/70 text-emerald-50 border-emerald-400/30",
    red: "bg-rose-700/70 text-rose-50 border-rose-400/30",
    amber: "bg-amber-700/70 text-amber-50 border-amber-400/30",
    blue: "bg-sky-700/70 text-sky-50 border-sky-400/30",
    purple: "bg-violet-700/70 text-violet-50 border-violet-400/30",
  };

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs",
        toneMap[tone] ?? toneMap.slate
      )}
    >
      <span className="opacity-80">{label}</span>
      <span className="font-semibold">{String(value ?? "-")}</span>
    </div>
  );
}

/**
 * ===========================================
 * Mode 선택 오버레이 (중앙 팝업)
 * - open=true일 때만 표시
 * - 바깥(딤) 클릭하거나 ESC로 닫기
 * - 모드 버튼 클릭 시 onPick(mode) 호출
 * ===========================================
 */
function ModeOverlay({ open, currentMode, modes, onPick, onClose }) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[9999]">
      {/* 반투명 배경(딤) */}
      <div
        className="absolute inset-0 bg-black/55 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* 중앙 모달 */}
      <div className="absolute inset-0 flex items-center justify-center p-4">
        <div className="w-full max-w-xl rounded-2xl border border-white/10 bg-slate-900/85 p-5 shadow-2xl">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-lg font-semibold text-slate-100">
                Mode 선택
              </div>
              <div className="text-sm text-slate-300">
                현재 모드:{" "}
                <span className="font-semibold">
                  {String(currentMode).toUpperCase()}
                </span>
              </div>
            </div>

            <button
              onClick={onClose}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 hover:bg-white/10"
            >
              닫기 (ESC)
            </button>
          </div>

          {/* 모드 버튼 그리드 */}
          <div className="mt-4 grid grid-cols-2 gap-3">
            {modes.map((m) => {
              const active =
                String(currentMode).toUpperCase() === String(m).toUpperCase();
              return (
                <button
                  key={m}
                  onClick={() => onPick(m)}
                  className={cn(
                    "rounded-2xl border p-4 text-left transition",
                    active
                      ? "border-sky-400/40 bg-sky-500/15 text-sky-50"
                      : "border-white/10 bg-white/5 text-slate-100 hover:bg-white/10"
                  )}
                >
                  <div className="text-base font-semibold">{m}</div>
                  <div className="mt-1 text-xs text-slate-300">
                    {m === "MOUSE" && "커서/클릭/드래그/스크롤"}
                    {m === "PRESENTATION" && "발표 제어(다음/이전 등)용"}
                    {m === "DRAW" && "그리기/펜 입력용"}
                    {m === "DEFAULT" && "기본(비활성/대기)"}
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mt-4 text-xs text-slate-400">
            이 오버레이는 현재는 버튼으로 열지만, 나중에 제스처로 열도록 확장
            가능.
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  /**
   * ===========================================
   * 상태(state) 영역
   * ===========================================
   */
  const [status, setStatus] = useState(null); // 서버에서 내려오는 raw status JSON
  const [mode, setMode] = useState("MOUSE"); // select UI용 mode state (서버에서 내려오면 동기화)
  const [loading, setLoading] = useState(true); // 최초 로딩 표시
  const [busy, setBusy] = useState(false); // POST 중 버튼 비활성 처리
  const [error, setError] = useState(""); // 에러 메시지
  const [lastUpdated, setLastUpdated] = useState(null); // 마지막 상태 갱신 시간
  const [preview, setPreview] = useState(false); // Preview 토글 상태(UI에서 즉시 반영)
  const abortRef = useRef(null); // 폴링 중복 요청 취소용

  const [hudVisible, setHudVisible] = useState(true);
  const [hudBusy, setHudBusy] = useState(false);

  // ✅ HUD/오버레이 추가: 모드 선택 팝업 열림 상태
  const [modeOverlayOpen, setModeOverlayOpen] = useState(false);

  /**
   * ===========================================
   * status(raw)에서 UI가 쓰기 좋은 형태로 derived(파생값) 만들기
   * - 백엔드 필드명이 바뀌거나 일부가 없을 때도 최대한 표시되게 안전 처리
   * ===========================================
   */
  const derived = useMemo(() => {
    const s = status || {};
    return {
      connected: !!s.connected, // 백엔드가 필드 제공 안 하면 false
      enabled: !!s.enabled,
      locked: !!s.locked,
      gesture: s.gesture ?? s.lastGesture ?? "NONE",
      fps: s.fps ?? s.agentFps ?? null,
      scrollActive: !!s.scrollActive,
      canMove: s.canMove ?? null,
      canClick: s.canClick ?? null,
      mode: s.mode ?? mode, // 서버 mode 우선, 없으면 로컬 mode
      type: s.type ?? "STATUS",
    };
  }, [status, mode]);

  /**
   * ===========================================
   * GET /api/control/status
   * - 500ms마다 폴링해서 서버 상태 가져오기
   * ===========================================
   */
  async function fetchStatus() {
    // 이전 요청이 있으면 취소 (폴링 중첩 방지)
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const { data } = await api.get("/control/status", {
        signal: controller.signal,
      });

      setStatus(data);
      // 서버에서 내려온 mode로 select UI도 맞춰줌
      setMode((prev) => data?.mode ?? prev);
      setLastUpdated(new Date());
      setError("");
    } catch (e) {
      // axios 취소(Abort) 케이스는 무시
      if (e?.name === "CanceledError" || e?.name === "AbortError") return;

      // 오류 메시지 포맷
      const msg = e?.response
        ? `STATUS HTTP ${e.response.status}${
            e.response.data ? `: ${String(e.response.data)}` : ""
          }`
        : e?.message || "STATUS fetch failed";

      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  /**
   * ===========================================
   * POST helper
   * - POST 후 fetchStatus()로 화면 상태 동기화
   * ===========================================
   */
  async function postJson(url, body) {
    setBusy(true);
    setError("");
    try {
      await api.post(url, body ?? {});
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `${url} HTTP ${e.response.status}${
            e.response.data ? `: ${String(e.response.data)}` : ""
          }`
        : e?.message || "POST failed";

      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  /**
   * ===========================================
   * Preview 토글
   * - POST /api/control/preview?enabled=true|false
   * ===========================================
   */
  const togglePreview = async () => {
    const next = !preview;
    setBusy(true);
    setError("");
    try {
      await api.post("/control/preview", null, { params: { enabled: next } });
      setPreview(next); // UI 즉시 반영
      await fetchStatus(); // 서버 상태 재조회(선택)
    } catch (e) {
      const msg = e?.response
        ? `/control/preview HTTP ${e.response.status}${
            e.response.data ? `: ${String(e.response.data)}` : ""
          }`
        : e?.message || "PREVIEW failed";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  /**
   * ===========================================
   * Start/Stop
   * - POST /api/control/start
   * - POST /api/control/stop
   * ===========================================
   */
  const start = () => postJson("/control/start");
  const stop = () => postJson("/control/stop");

  /**
   * ===========================================
   * Mode 변경
   * - POST /api/control/mode?mode=MOUSE
   * - select 변경 또는 오버레이에서 모드 클릭 시 실행
   * ===========================================
   */
  const applyMode = async (nextMode) => {
    setMode(nextMode); // UI 먼저 반영(체감 빠르게)
    setBusy(true);
    setError("");
    try {
      await api.post("/control/mode", null, { params: { mode: nextMode } });
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `/control/mode HTTP ${e.response.status}${
            e.response.data ? `: ${String(e.response.data)}` : ""
          }`
        : e?.message || "MODE failed";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };
  async function setHudVisibleApi(next) {
    setHudBusy(true);
    setError("");
    try {
      await api.post("/hud/show", null, { params: { enabled: next } });
      setHudVisible(next);
    } catch (e) {
      const msg = e?.response
        ? `/hud/show HTTP ${e.response.status}${
            e.response.data ? `: ${String(e.response.data)}` : ""
          }`
        : e?.message || "HUD show/hide failed";
      setError(msg);
    } finally {
      setHudBusy(false);
    }
  }

  async function exitHudApi() {
    setHudBusy(true);
    setError("");
    try {
      await api.post("/hud/exit");
      // 종료했으니 UI도 "안 보임"으로 간주
      setHudVisible(false);
    } catch (e) {
      const msg = e?.response
        ? `/hud/exit HTTP ${e.response.status}${
            e.response.data ? `: ${String(e.response.data)}` : ""
          }`
        : e?.message || "HUD exit failed";
      setError(msg);
    } finally {
      setHudBusy(false);
    }
  }

  /**
   * ===========================================
   * 최초 마운트 시:
   * - fetchStatus 1회
   * - 이후 500ms마다 폴링
   * ===========================================
   */
  useEffect(() => {
    fetchStatus();
    const t = setInterval(fetchStatus, POLL_MS);
    return () => {
      clearInterval(t);
      if (abortRef.current) abortRef.current.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * ===========================================
   * ESC 키로 모드 오버레이 닫기
   * - 화면 어디서든 ESC 누르면 닫히도록 window에 바인딩
   * ===========================================
   */
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") setModeOverlayOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /**
   * ===========================================
   * 렌더 영역
   * ===========================================
   */
  return (
    <div className="min-h-screen bg-[#0b1220] text-slate-100">
      {/* ===============================
          Topbar (Docker Desktop 느낌)
         =============================== */}
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

          {/* 상단 상태 배지들 */}
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
            <div className="ml-2 h-9 w-9 rounded-full bg-slate-800/80 ring-1 ring-white/10 grid place-items-center text-xs font-semibold">
              P
            </div>
          </div>
        </div>
      </div>

      {/* ===============================
          Main Layout
         =============================== */}
      <div className="mx-auto max-w-[1200px] px-6 py-6 grid grid-cols-12 gap-5">
        {/* ===============================
            Sidebar
           =============================== */}
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
              <Btn
                tone="blue"
                onClick={() => setHudVisibleApi(!hudVisible)}
                disabled={busy || hudBusy}
              >
                {hudVisible ? "HUD Hide" : "HUD Show"}
              </Btn>

              <Btn
                tone="red"
                onClick={exitHudApi}
                disabled={busy || hudBusy}
                className="ml-1"
              >
                HUD Exit
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

        {/* ===============================
            Main Content
           =============================== */}
        <main className="col-span-12 lg:col-span-9 space-y-5">
          {/* Row 1 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Mode 카드 (기존 select 방식) */}
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

            {/* Connection 카드 */}
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
                connected/fps는 백엔드가 내려주는 필드명에 따라 표시(없으면
                기본값).
              </div>
            </Card>
          </div>

          {/* Row 2 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Agent State 카드 */}
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

            {/* Docker-style list */}
            <Card title="Containers (Docker-style list)">
              <div className="rounded-xl bg-slate-950/50 ring-1 ring-white/10 overflow-hidden">
                <div className="grid grid-cols-12 px-4 py-3 text-xs text-slate-300 border-b border-white/10">
                  <div className="col-span-6">NAME</div>
                  <div className="col-span-3">STATUS</div>
                  <div className="col-span-3 text-right">METRIC</div>
                </div>

                {/* Agent row */}
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

                {/* Scroll row */}
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
                발표용으로 “도커 리스트 느낌” 내기 위한 더미 UI. 실제 컨테이너가
                아니라 상태 기반 표시임.
              </div>
            </Card>
          </div>

          {/* Raw JSON */}
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

      {/* ======================================================
          ✅ [추가] Floating HUD (항상 우상단에 떠있는 상태판)
          - 기존 UI를 건드리지 않고 overlay처럼 얹는 형태
          - 실제 데모할 때 "왜 안 움직임?" 같은 질문에 즉시 답 가능
         ====================================================== */}
      <div className="fixed right-4 top-4 z-[9998] w-[360px] rounded-2xl border border-white/10 bg-slate-900/70 p-4 text-slate-100 shadow-xl backdrop-blur-md">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold">HUD</div>
            <div className="mt-1 text-xs text-slate-300">
              상태 요약(항상 표시)
            </div>
          </div>

          {/* Polling 기반이라 WS가 아니라 HTTP 상태를 표시 */}
          <div className="flex gap-2">
            <Pill
              label="HTTP"
              value={error ? "DEGRADED" : "OK"}
              tone={error ? "red" : "green"}
            />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Pill
            label="Enabled"
            value={derived.enabled ? "ON" : "OFF"}
            tone={derived.enabled ? "green" : "red"}
          />
          <Pill
            label="Locked"
            value={derived.locked ? "ON" : "OFF"}
            tone={derived.locked ? "amber" : "green"}
          />
          <Pill
            label="Mode"
            value={String(derived.mode).toUpperCase()}
            tone="blue"
          />
          <Pill label="Gesture" value={derived.gesture} tone="purple" />
          <Pill label="FPS" value={formatNum(derived.fps, 1)} tone="slate" />
          <Pill
            label="Move"
            value={
              derived.canMove === null ? "-" : derived.canMove ? "YES" : "NO"
            }
            tone={derived.canMove ? "green" : "slate"}
          />
          <Pill
            label="Click"
            value={
              derived.canClick === null ? "-" : derived.canClick ? "YES" : "NO"
            }
            tone={derived.canClick ? "green" : "slate"}
          />
          <Pill
            label="Scroll"
            value={derived.scrollActive ? "ON" : "OFF"}
            tone={derived.scrollActive ? "green" : "slate"}
          />
        </div>

        {/* HUD 내 빠른 버튼들 */}
        <div className="mt-4 grid grid-cols-2 gap-2">
          {/* enabled 토글: 현재는 start/stop으로 연결 */}
          <button
            onClick={() => (derived.enabled ? stop() : start())}
            disabled={busy}
            className={cn(
              "rounded-xl border px-3 py-2 text-sm transition disabled:opacity-50",
              derived.enabled
                ? "border-rose-400/30 bg-rose-500/15 hover:bg-rose-500/25"
                : "border-emerald-400/30 bg-emerald-500/15 hover:bg-emerald-500/25"
            )}
          >
            {derived.enabled ? "Disable" : "Enable"}
          </button>

          <button
            onClick={togglePreview}
            disabled={busy}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
          >
            {preview ? "Preview OFF" : "Preview ON"}
          </button>

          {/* ✅ 오버레이 열기 */}
          <button
            onClick={() => setModeOverlayOpen(true)}
            disabled={busy}
            className="rounded-xl border border-sky-400/25 bg-sky-500/10 px-3 py-2 text-sm hover:bg-sky-500/20 disabled:opacity-50"
          >
            Mode 변경
          </button>

          <button
            onClick={fetchStatus}
            disabled={busy}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
          >
            Refresh
          </button>
        </div>

        {error ? (
          <div className="mt-3 text-xs text-rose-200 bg-rose-950/40 ring-1 ring-rose-900/60 rounded-xl p-3">
            {error}
          </div>
        ) : null}
      </div>

      {/* ======================================================
          ✅ [추가] ModeOverlay (중앙 팝업)
          - HUD의 "Mode 변경" 버튼 누르면 열림
          - 모드 클릭 시 applyMode(mode) 호출 -> 백엔드에 POST /control/mode
         ====================================================== */}
      <ModeOverlay
        open={modeOverlayOpen}
        currentMode={mode}
        modes={MODE_OPTIONS}
        onClose={() => setModeOverlayOpen(false)}
        onPick={(m) => {
          applyMode(m); // 기존 mode 변경 로직 재사용
          setModeOverlayOpen(false); // 오버레이 닫기
        }}
      />
    </div>
  );
}
