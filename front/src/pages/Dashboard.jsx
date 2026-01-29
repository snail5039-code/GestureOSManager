// src/pages/Dashboard.jsx
import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { THEME } from "../theme/themeTokens";
import ProfileCard from "../components/ProfileCard";
import { useAuth } from "../auth/AuthProvider";
import DebugChat from "../components/DebugChat";
import { trainApi } from "../api/trainClient";

// ✅ WS import 추가
import { connectAgentWs, addAgentWsListener, closeAgentWs } from "../api/agentWs";

// ✅ Bridge import 추가
import { bridgeStart, openWebWithBridge } from "../api/accountClient";

const POLL_MS = 500;

const MODE_OPTIONS = ["MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "VKEY"];
const MODE_LABEL = {
  MOUSE: "마우스",
  KEYBOARD: "키보드",
  PRESENTATION: "프레젠테이션",
  DRAW: "그리기",
  VKEY: "가상키보드",
};

const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8080/api" : "/api";

const api = axios.create({
  baseURL: API_BASE,
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

async function detectCameraPresent() {
  try {
    if (!navigator.mediaDevices?.enumerateDevices) return null;
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.some((d) => d.kind === "videoinput");
  } catch {
    return null;
  }
}

/* =========================
   Icons (SVG)
========================= */
function IconPlay() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-90">
      <path d="M8 5v14l12-7-12-7Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}

function IconStop() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-90">
      <path d="M7 7h10v10H7V7Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}

function IconRefresh({ spinning }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className={cn("opacity-90", spinning && "animate-spin")}>
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
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-90">
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
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-90">
      <path d="M8 11V8a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <path d="M7 11h10v10H7V11Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
    </svg>
  );
}

function IconChevron() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-85">
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
   Theme-aware UI blocks (COMPACT)
========================= */
function Badge({ t, children, tone = "slate" }) {
  const map = {
    slate: cn(t.chip, t.text2, "ring-1"),
    blue: cn("bg-sky-500/12 ring-sky-400/25", t.text2, "ring-1"),
    green: cn("bg-emerald-500/12 ring-emerald-400/25", t.text2, "ring-1"),
    yellow: cn("bg-amber-500/14 ring-amber-400/25", t.text2, "ring-1"),
    red: cn("bg-rose-500/12 ring-rose-400/25", t.text2, "ring-1"),
  };
  return <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px]", map[tone] || map.slate)}>{children}</span>;
}

function Card({ t, title, right, children, accent = "slate", className, bodyClassName }) {
  const topLine = {
    slate: "from-slate-400/18 via-transparent to-transparent",
    blue: "from-sky-400/20 via-transparent to-transparent",
    green: "from-emerald-400/20 via-transparent to-transparent",
    red: "from-rose-400/20 via-transparent to-transparent",
    yellow: "from-amber-400/20 via-transparent to-transparent",
  };

  const isBright = t._isBright ?? false;
  const shadow = isBright ? "shadow-[0_10px_26px_rgba(15,23,42,0.08)]" : "shadow-[0_10px_34px_rgba(0,0,0,0.25)]";

  return (
    <div
      className={cn(
        "rounded-lg ring-1 overflow-hidden flex flex-col",
        t.panel,
        shadow,
        "transition-transform duration-200 hover:-translate-y-[1px]",
        className,
      )}
    >
      <div className={cn("h-px w-full bg-gradient-to-r", topLine[accent] || topLine.slate)} />
      <div className={cn("flex items-center justify-between px-3 py-2 border-b", isBright ? "border-slate-200" : "border-white/10")}>
        <div className={cn("text-[13px] font-semibold", t.text)}>{title}</div>
        {right}
      </div>
      <div className={cn("px-3 py-2.5", bodyClassName)}>{children}</div>
    </div>
  );
}

function Btn({ t, className, ...props }) {
  return (
    <button
      className={cn(
        "w-full rounded-lg py-2 text-[13px] font-semibold ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed",
        t.btn,
        className,
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
        "w-full rounded-lg p-2 ring-1 transition text-left disabled:opacity-50 disabled:cursor-not-allowed",
        isBright ? "shadow-[0_10px_26px_rgba(15,23,42,0.08)]" : "shadow-[0_10px_30px_rgba(0,0,0,0.25)]",
        map[tone] || map.slate,
        className,
      )}
      {...props}
    >
      <div className="flex items-center gap-2.5">
        <div className={cn("h-9 w-9 rounded-lg ring-1 grid place-items-center", chipMap[tone] || chipMap.slate)}>
          <div className={cn(t.text)}>{icon}</div>
        </div>

        <div className="min-w-0">
          <div className={cn("text-[13px] font-semibold leading-5", t.text)}>{title}</div>
          <div className={cn("text-[11px] mt-0.5 truncate", t.muted)}>{desc}</div>
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
        "relative inline-flex h-5 w-9 items-center rounded-full ring-1 transition disabled:opacity-50 disabled:cursor-not-allowed",
        checked ? "bg-sky-500/25 ring-sky-300/70" : isBright ? "bg-slate-200 ring-slate-300" : "bg-slate-800/70 ring-white/12",
      )}
      aria-checked={checked}
      role="switch"
    >
      <span className={cn("inline-block h-4 w-4 transform rounded-full bg-white transition", checked ? "translate-x-4" : "translate-x-1")} />
    </button>
  );
}

function StatTile({ t, label, value, tone = "slate" }) {
  const isBright = t._isBright ?? false;

  const ring =
    tone === "green"
      ? isBright
        ? "ring-emerald-300/70"
        : "ring-emerald-400/25"
      : tone === "blue"
        ? isBright
          ? "ring-sky-300/70"
          : "ring-sky-400/25"
        : tone === "yellow"
          ? isBright
            ? "ring-amber-300/70"
            : "ring-amber-400/25"
          : tone === "red"
            ? isBright
              ? "ring-rose-300/70"
              : "ring-rose-400/25"
            : isBright
              ? "ring-slate-200"
              : "ring-white/12";

  return (
    <div className={cn("rounded-md ring-1 px-2.5 py-1.5 overflow-hidden", t.panelSoft, ring)}>
      <div className={cn("text-[10px] leading-4", t.muted)}>{label}</div>
      <div className={cn("mt-0.5 font-semibold text-[12px] leading-4", t.text)}>{value}</div>
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
    <div className={cn("rounded-lg ring-1 p-2.5 overflow-hidden", t.panelSoft, isBright ? "ring-slate-200" : "ring-white/12")}>
      <div className="flex items-center justify-between">
        <div className={cn("text-[11px]", t.muted)}>포인터</div>
        <div className={cn("text-[11px] tabular-nums", t.muted)}>
          {cx === null ? "-" : cx.toFixed(3)} / {cy === null ? "-" : cy.toFixed(3)}
        </div>
      </div>

      <div
        className={cn(
          "mt-2.5 relative h-16 rounded-md ring-1 overflow-hidden",
          forceWhiteMap ? "bg-white ring-violet-200" : isBright ? "bg-white ring-slate-200" : "bg-slate-900/35 ring-white/12",
        )}
      >
        <div className="absolute inset-0 opacity-[0.18]">
          <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(15,23,42,.08)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,.08)_1px,transparent_1px)] bg-[size:16px_16px]" />
        </div>

        <div className={cn("absolute h-2 w-2 rounded-full", t.dot)} style={{ left: `${left}%`, top: `${top}%`, transform: "translate(-50%,-50%)" }} />
      </div>
    </div>
  );
}

/* =========================
   Dashboard
========================= */
export default function Dashboard({ onHudState, onHudActions, theme = "dark", onChangeScreen } = {}) {
  const { user, isAuthed } = useAuth();

  const openWebAuthed = useCallback(async () => {
    try {
      const accessToken =
        localStorage.getItem("accessToken") ||
        localStorage.getItem("gos_accessToken") ||
        localStorage.getItem("token") ||
        null;

      const data = await bridgeStart(accessToken);
      const code = data?.code;

      if (!code) {
        window.open("http://localhost:5174", "_blank", "noreferrer");
        return;
      }

      openWebWithBridge({ code, webOrigin: "http://localhost:5174" });
    } catch {
      window.open("http://localhost:5174", "_blank", "noreferrer");
    }
  }, []);

  const chatResetKey = useMemo(() => {
    const ident = user?.id ?? user?.memberId ?? user?.member_id ?? user?.email ?? "anon";
    return `${isAuthed ? "A" : "G"}:${String(ident)}`;
  }, [isAuthed, user?.id, user?.memberId, user?.member_id, user?.email]);

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

  const [cameraPresent, setCameraPresent] = useState(null);
  const [modal, setModal] = useState({ open: false, title: "", message: "" });

  const closeModal = useCallback(() => setModal((m) => ({ ...m, open: false })), []);
  const openModal = useCallback((title, message) => setModal({ open: true, title, message }), []);

  useEffect(() => {
    if (!modal.open) return;
    const onKey = (e) => e.key === "Escape" && closeModal();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modal.open, closeModal]);

  useEffect(() => {
    let alive = true;
    (async () => {
      const ok = await detectCameraPresent();
      if (alive) setCameraPresent(ok);
    })();
    return () => {
      alive = false;
    };
  }, []);

  // ✅ X-User-Id는 서버에서 Long으로 파싱됨 → 숫자만 허용
  const memberId = useMemo(() => {
    const raw = user?.id ?? user?.memberId ?? user?.member_id ?? null;
    if (raw === null || raw === undefined) return null;
    const s = String(raw).trim();
    if (!/^\d+$/.test(s)) return null;
    return s;
  }, [user]);

  // ✅ train 전용 headers
  const userHeaders = useMemo(() => {
    if (!isAuthed || !memberId) return {};
    return { "X-User-Id": String(memberId) };
  }, [isAuthed, memberId]);

  const autoProfileDoneRef = useRef(false);

  useEffect(() => {
    const connected = !!status?.connected;
    if (!connected) return;
    if (!isAuthed || !memberId) return;
    if (autoProfileDoneRef.current) return;

    const cur = String(status?.learnProfile || "default").toLowerCase();
    const system = new Set(["default", "mouse", "keyboard", "ppt", "draw", "vkey", "rush"]);
    if (!system.has(cur)) {
      autoProfileDoneRef.current = true;
      return;
    }

    const target = `u${String(memberId)}__main`;

    (async () => {
      try {
        await trainApi.post("/train/profile/set", null, {
          params: { name: target },
          headers: userHeaders,
        });
      } catch {
        // ignore
      } finally {
        autoProfileDoneRef.current = true;
      }
    })();
  }, [status?.connected, status?.learnProfile, isAuthed, memberId, userHeaders, status]);

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
      tracking:
        typeof s.tracking === "boolean"
          ? s.tracking
          : typeof s.isTracking === "boolean"
            ? s.isTracking
            : null,
      controlGain: typeof s.controlGain === "number" ? s.controlGain : null,
      // ✅ Dashboard는 여기 값이 /train/stats로부터 들어와야 동기화됨
      learnProfile: s.learnProfile ?? "default",
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

  // ✅ 핵심: control/status + train/stats 둘 다 가져와서 status에 합친다
  const fetchStatus = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const [ctrlRes, trainRes] = await Promise.all([
        api.get("/control/status", { signal: controller.signal }),
        isAuthed && memberId
          ? trainApi.get("/train/stats", { signal: controller.signal, headers: userHeaders })
          : Promise.resolve({ data: null }),
      ]);

      const ctrl = ctrlRes?.data ?? null;
      const tr = trainRes?.data ?? null;

      setStatus((prev) => {
        const base = ctrl || prev || {};
        if (!tr) return base;

        return {
          ...base,
          // learner 영역은 train/stats가 정답
          learnProfile: tr.learnProfile ?? base.learnProfile,
          learnEnabled: tr.learnEnabled ?? base.learnEnabled,
          learnCounts: tr.learnCounts ?? base.learnCounts,
          learnCapture: tr.learnCapture ?? base.learnCapture,
          learnLastTrainTs: tr.learnLastTrainTs ?? base.learnLastTrainTs,
          learnHasBackup: tr.learnHasBackup ?? base.learnHasBackup,
          learnProfiles: tr.learnProfiles ?? base.learnProfiles,
        };
      });

      setMode((prev) => ctrl?.mode ?? prev);

      if (typeof ctrl?.preview === "boolean") {
        setPreview(ctrl.preview);
        previewRef.current = ctrl.preview;
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
  }, [isAuthed, memberId, userHeaders]);

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
    [fetchStatus],
  );

  const start = useCallback(
    async (ctx = { source: "ui" }) => {
      const ok = await detectCameraPresent();
      setCameraPresent(ok);

      if (ok === false) {
        openModal("카메라 미연결", "카메라를 연결하세요.");
        if (ctx?.source !== "chat") {
          window.__GOS_CHAT_LOG__?.("system", "카메라 연결 후 사용 가능");
        }
        return { ok: false, reason: "camera", message: "카메라 연결 후 사용 가능." };
      }

      setBusy(true);
      setError("");
      try {
        await api.post("/control/start", {});
        await fetchStatus();
        return { ok: true };
      } catch (e) {
        const msg = e?.response
          ? `요청 실패: /control/start (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || "요청 실패";
        setError(msg);
        return { ok: false, reason: "http", message: msg };
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus, openModal],
  );

  const stop = useCallback(() => postJson("/control/stop"), [postJson]);

  const togglePreview = useCallback(
    async (want, ctx = { source: "ui" }) => {
      if (previewBusyRef.current) return { ok: false, reason: "busy" };

      const cur = !!previewRef.current;
      const next = typeof want === "boolean" ? want : !cur;

      if (typeof want === "boolean" && next === cur) {
        return { ok: true, message: next ? "Preview는 이미 ON이야." : "Preview는 이미 OFF야." };
      }

      if (next) {
        const ok = await detectCameraPresent();
        setCameraPresent(ok);

        if (ok === false) {
          openModal("카메라 미연결", "카메라를 연결하세요.");
          if (ctx?.source !== "chat") {
            window.__GOS_CHAT_LOG__?.("system", "카메라 연결 후 Preview 사용 가능");
          }
          return { ok: false, reason: "camera", message: "카메라 연결 후 Preview 사용 가능." };
        }
      }

      previewBusyRef.current = true;
      previewRef.current = next;
      setPreview(next);

      setBusy(true);
      setError("");
      try {
        await api.post("/control/preview", null, { params: { enabled: next } });
        await fetchStatus();
        previewBusyRef.current = false;
        return { ok: true };
      } catch (e) {
        previewBusyRef.current = false;
        previewRef.current = !next;
        setPreview(!next);

        const msg = e?.response
          ? `프리뷰 변경 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || "프리뷰 변경 실패";
        setError(msg);
        return { ok: false, reason: "http", message: msg };
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus, openModal],
  );

  const applyMode = useCallback(
    async (nextMode, ctx = { source: "ui" }) => {
      setMode(nextMode);
      setBusy(true);
      setError("");
      try {
        if (!derived.enabled) {
          const ok = await detectCameraPresent();
          setCameraPresent(ok);

          if (ok === false) {
            openModal("카메라 미연결", "카메라를 연결하세요.");
            if (ctx?.source !== "chat") {
              window.__GOS_CHAT_LOG__?.("system", "카메라 연결 후 모드 변경 가능");
            }
            return { ok: false, reason: "camera", message: "카메라 연결 후 모드 변경 가능." };
          }

          await api.post("/control/start");
        }

        await api.post("/control/mode", null, { params: { mode: nextMode } });
        await fetchStatus();
        return { ok: true };
      } catch (e) {
        const msg = e?.response
          ? `모드 변경 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || "모드 변경 실패";
        setError(msg);
        return { ok: false, reason: "http", message: msg };
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus, derived.enabled, openModal],
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
    [fetchStatus],
  );

  const setGain = useCallback(
    async (gain) => {
      const g = Math.max(0.2, Math.min(4.0, Number(gain)));

      setBusy(true);
      setError("");
      try {
        await api.post("/control/gain", null, { params: { gain: g } });
        localStorage.setItem("gos_control_gain", String(g));
        await fetchStatus();
        return { ok: true, gain: g };
      } catch (e) {
        const msg = e?.response
          ? `감도 변경 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || "감도 변경 실패";
        setError(msg);
        return { ok: false, reason: "http", message: msg };
      } finally {
        setBusy(false);
      }
    },
    [fetchStatus],
  );

  useEffect(() => {
    onHudActions?.({ start, stop, applyMode, togglePreview, fetchStatus, setLock, setGain });
  }, [onHudActions, start, stop, applyMode, togglePreview, fetchStatus, setLock, setGain]);

  useEffect(() => {
    onHudState?.({
      status,
      connected: derived.connected,
      locked: derived.locked,
      mode: derived.mode,
      modeText: view.modeText,
      modeOptions: MODE_OPTIONS,
      cameraPresent,
    });
  }, [onHudState, status, derived.connected, derived.locked, derived.mode, view.modeText, cameraPresent]);

  // ✅ WS에서 최신 상태를 보기 위한 ref들 (재연결 방지)
  const enabledRef = useRef(false);
  const busyRef = useRef(false);
  const startRef = useRef(start);
  const stopRef = useRef(stop);

  useEffect(() => {
    enabledRef.current = !!derived.enabled;
  }, [derived.enabled]);

  useEffect(() => {
    busyRef.current = !!busy;
  }, [busy]);

  useEffect(() => {
    startRef.current = start;
  }, [start]);

  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);

  // ✅ WS: 제스처 Start/Stop 이벤트 수신 (mount 1회)
  useEffect(() => {
    const ws = connectAgentWs();

    const unsubscribe = addAgentWsListener((msg) => {
      if (!msg || typeof msg !== "object") return;

      if (msg.type === "EVENT") {
        const name = String(msg.name || "");

        if (name === "APP_START") {
          if (!enabledRef.current && !busyRef.current) {
            startRef.current?.({ source: "gesture" });
          }
        } else if (name === "APP_STOP") {
          if (enabledRef.current && !busyRef.current) {
            stopRef.current?.();
          }
        }
      }
    });

    return () => {
      unsubscribe?.();
      try {
        ws?.close?.();
      } catch {}
      try {
        closeAgentWs?.();
      } catch {}
    };
  }, []);

  const canStart = !busy && !derived.enabled;
  const canStop = !busy && !!derived.enabled;
  const isBright = theme === "light" || theme === "rose";

  return (
    <div className={cn("w-full min-w-0 relative", t.page)}>
      <div className="relative w-full min-w-0 px-3 pt-0 pb-7 md:px-4 md:pt-3 md:pb-7 flex flex-col gap-3">
        {error ? (
          <div
            className={cn(
              "rounded-lg ring-1 px-4 py-3 text-[13px]",
              isBright ? "bg-rose-50 ring-rose-200 text-slate-900" : "bg-rose-950/30 ring-rose-900/60 text-rose-100",
            )}
          >
            {error}
          </div>
        ) : null}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 items-start">
          <div className="lg:col-span-5 flex flex-col gap-3">
            <ProfileCard
              t={t}
              theme={theme}
              currentProfile={derived.learnProfile}
              onOpenTraining={() => onChangeScreen && onChangeScreen("train")}
              onOpenWeb={openWebAuthed}
            />

            <Card t={t} title="모드" accent="blue">
              <div className="space-y-2.5">
                <select
                  value={mode}
                  onChange={(e) => applyMode(e.target.value)}
                  disabled={busy}
                  className={cn(
                    "w-full rounded-lg ring-1 px-3 py-1.5 text-[13px] outline-none focus:ring-2 disabled:opacity-50",
                    t.input,
                    isBright ? "focus:ring-sky-400/40" : "focus:ring-sky-500/45",
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
              right={
                busy ? (
                  <Badge t={t} tone="blue">
                    처리 중
                  </Badge>
                ) : (
                  <Badge t={t} tone="slate">
                    대기
                  </Badge>
                )
              }
            >
              <div className="grid grid-cols-2 gap-2.5">
                <ActionTile t={t} tone="green" icon={<IconPlay />} title="시작" desc="Start" onClick={() => start({ source: "ui" })} disabled={!canStart} />
                <ActionTile t={t} tone="red" icon={<IconStop />} title="정지" desc="Stop" onClick={stop} disabled={!canStop} />
              </div>

              <div className={cn("mt-2.5 rounded-lg ring-1 p-2.5 space-y-2.5", t.panelSoft)}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className={cn(t.text2)}>
                      <IconEye />
                    </span>
                    <div>
                      <div className={cn("text-[13px] font-semibold leading-5", t.text)}>프리뷰</div>
                      <div className={cn("text-[11px]", t.muted)}>카메라/랜드마크 미리보기</div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <Switch t={t} checked={preview} onChange={() => togglePreview()} disabled={busy} />
                  </div>
                </div>

                <div className={cn("h-px", t.divider)} />

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className={cn(t.text2)}>
                      <IconLock />
                    </span>
                    <div>
                      <div className={cn("text-[13px] font-semibold leading-5", t.text)}>잠금</div>
                      <div className={cn("text-[11px]", t.muted)}>제스처 입력 잠금/해제</div>
                    </div>
                  </div>
                  <Switch t={t} checked={derived.locked} onChange={(v) => setLock(!!v)} disabled={busy} />
                </div>
              </div>

              <Btn t={t} onClick={fetchStatus} disabled={busy} className="mt-2.5 flex items-center justify-center gap-2">
                <IconRefresh spinning={busy} />
                새로고침
              </Btn>

              <div className="mt-2.5 grid grid-cols-2 gap-2">
                <StatTile t={t} label="FPS" value={formatNum(derived.fps, 1)} tone="blue" />
                <StatTile t={t} label="현재 제스처" value={derived.gesture} tone="slate" />
              </div>
            </Card>
          </div>

          <div className="lg:col-span-7 grid gap-3 grid-rows-[auto_auto]">
            <Card
              t={t}
              title="상태"
              accent="blue"
              right={
                loading ? (
                  <Badge t={t} tone="yellow">
                    불러오는 중
                  </Badge>
                ) : (
                  <Badge t={t} tone="slate">
                    라이브
                  </Badge>
                )
              }
            >
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
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

              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2.5">
                <PointerMiniMap t={t} theme={theme} x={derived.pointerX} y={derived.pointerY} />
                <div className={cn("rounded-lg ring-1 p-2.5", t.panelSoft)}>
                  <div className={cn("text-[11px]", t.muted)}>요약</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge t={t} tone="slate">
                      제스처: {derived.gesture}
                    </Badge>
                    <Badge t={t} tone={preview ? "blue" : "slate"}>
                      {preview ? "Preview ON" : "Preview OFF"}
                    </Badge>
                    <Badge t={t} tone="slate">
                      Mode: {view.modeText}
                    </Badge>
                  </div>
                </div>
              </div>
            </Card>

            <Card t={t} title="명령 채팅창" accent="slate">
              <div className="h-[min(38vh,280px)] flex flex-col">
                {showRaw ? (
                  <pre className={cn("text-[11px] leading-relaxed overflow-auto flex-1 rounded-lg ring-1 p-3", t.panelSolid || t.panel2 || t.panel, t.input)}>
                    {status ? JSON.stringify(status, null, 2) : loading ? "Loading..." : "No data"}
                  </pre>
                ) : (
                  <DebugChat
                    key={chatResetKey}
                    resetKey={chatResetKey}
                    t={t}
                    busy={busy}
                    preview={preview}
                    derived={derived}
                    view={view}
                    cameraPresent={cameraPresent}
                    actions={{
                      start: (ctx) => start(ctx ?? { source: "ui" }),
                      stop,
                      applyMode,
                      togglePreview,
                      fetchStatus,
                      setLock,
                      setGain,
                    }}
                  />
                )}
              </div>
            </Card>
          </div>
        </div>
      </div>

      {modal.open
        ? createPortal(
            <div
              className="fixed inset-0 z-[100000] flex items-center justify-center"
              style={{ WebkitAppRegion: "no-drag" }}
              onMouseDown={(e) => {
                if (e.target === e.currentTarget) closeModal();
              }}
            >
              <div className="absolute inset-0 bg-black/45 backdrop-blur-[2px]" />

              <div className={cn("relative w-[min(500px,92vw)] rounded-lg ring-1 p-4 shadow-2xl", t.panel)}>
                <div className="min-w-0">
                  <div className={cn("text-[15px] font-semibold", t.text)}>{modal.title}</div>
                  <div className={cn("mt-2 text-[13px]", t.muted)}>{modal.message}</div>
                </div>

                <div className="mt-4 flex justify-end gap-2">
                  <button type="button" onClick={closeModal} className={cn("px-4 py-2 rounded-lg text-[13px] font-semibold ring-1 transition", t.btn)}>
                    확인
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
