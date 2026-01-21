// src/pages/TrainingLab.jsx
import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const POLL_MS = 120;

const LABELS = ["OPEN_PALM", "FIST", "V_SIGN", "PINCH_INDEX", "OTHER"];
const HANDS = [
  { id: "cursor", label: "Cursor(주 손)" },
  { id: "other", label: "Other(보조 손)" },
];

const api = axios.create({
  baseURL: "/api",
  timeout: 5000,
  headers: { Accept: "application/json" },
});

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

// MediaPipe Hands connections (subset of standard edges)
const HAND_EDGES = [
  [0, 1],[1, 2],[2, 3],[3, 4],
  [0, 5],[5, 6],[6, 7],[7, 8],
  [5, 9],[9,10],[10,11],[11,12],
  [9,13],[13,14],[14,15],[15,16],
  [13,17],[17,18],[18,19],[19,20],
  [0,17],
];

function isValidLmArr(arr) {
  return (
    Array.isArray(arr) &&
    arr.length === 21 &&
    arr.every((p) => p && typeof p.x === "number" && typeof p.y === "number")
  );
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function drawHands(canvas, opts) {
  const { cursorLm, otherLm, theme, cursorLabel, otherLabel } = opts;
  const el = canvas;
  if (!el) return;

  const rect = el.getBoundingClientRect();
  const w = Math.max(10, Math.floor(rect.width));
  const h = Math.max(10, Math.floor(rect.height));
  const dpr = window.devicePixelRatio || 1;

  if (el.width !== Math.floor(w * dpr) || el.height !== Math.floor(h * dpr)) {
    el.width = Math.floor(w * dpr);
    el.height = Math.floor(h * dpr);
  }

  const ctx = el.getContext("2d");
  if (!ctx) return;

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  // subtle grid for orientation
  ctx.save();
  ctx.globalAlpha = 0.25;
  ctx.lineWidth = 1;
  ctx.strokeStyle =
    theme === "light" ? "rgba(0,0,0,0.35)" : "rgba(255,255,255,0.25)";
  const step = 40;
  for (let x = step; x < w; x += step) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  for (let y = step; y < h; y += step) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  ctx.restore();

  const drawOne = (lm, stroke, fill, tag, yText) => {
    if (!isValidLmArr(lm)) return;

    ctx.save();
    ctx.lineWidth = 2;
    ctx.strokeStyle = stroke;
    ctx.globalAlpha = 0.95;

    for (const [a, b] of HAND_EDGES) {
      const pa = lm[a];
      const pb = lm[b];
      ctx.beginPath();
      ctx.moveTo(pa.x * w, pa.y * h);
      ctx.lineTo(pb.x * w, pb.y * h);
      ctx.stroke();
    }

    ctx.fillStyle = fill;
    for (let i = 0; i < lm.length; i++) {
      const p = lm[i];
      const x = p.x * w;
      const y = p.y * h;
      const r = i === 8 || i === 4 ? 5 : 3; // index tip & thumb tip 강조
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalAlpha = 1;
    ctx.font = "12px ui-sans-serif, system-ui, -apple-system";
    ctx.fillStyle =
      theme === "light" ? "rgba(0,0,0,0.75)" : "rgba(255,255,255,0.85)";
    ctx.fillText(tag, 10, yText);

    ctx.restore();
  };

  drawOne(
    cursorLm,
    "rgba(0,255,255,0.9)",
    "rgba(0,255,255,0.9)",
    cursorLabel || "CURSOR",
    18
  );
  drawOne(
    otherLm,
    "rgba(255,0,255,0.9)",
    "rgba(255,0,255,0.9)",
    otherLabel || "OTHER",
    36
  );
}

function getServerCount(learnCounts, hand, label) {
  if (!learnCounts) return 0;
  const h = learnCounts[hand];
  if (!h) return 0;
  const v = h[label];
  return typeof v === "number" ? v : 0;
}

export default function TrainingLab({ theme = "dark" }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);

  // capture controls (로컬)
  const [label, setLabel] = useState("OPEN_PALM");
  const [handId, setHandId] = useState("cursor");
  const [captureSec, setCaptureSec] = useState(2);
  const [capturing, setCapturing] = useState(false);
  const captureRef = useRef(null);

  // ✅ 서버 learner 작업 중 표시
  const [serverBusy, setServerBusy] = useState(false);

  // ✅ profile UI
  const [newProfile, setNewProfile] = useState("");
  const [renameTo, setRenameTo] = useState("");

  // dataset stored in ref to avoid rerender per frame
  const datasetRef = useRef({
    meta: {
      app: "GestureOS TrainingLab",
      createdAt: new Date().toISOString(),
      schema: "v1",
    },
    samples: [],
  });
  const [datasetVersion, setDatasetVersion] = useState(0);

  // persist dataset locally so it doesn't disappear on refresh
  useEffect(() => {
    try {
      const raw = localStorage.getItem("trainingLab.dataset.v1");
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed && Array.isArray(parsed.samples)) {
        datasetRef.current = parsed;
        setDatasetVersion((v) => v + 1);
      }
    } catch (_) {}
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(
        "trainingLab.dataset.v1",
        JSON.stringify(datasetRef.current)
      );
    } catch (_) {}
  }, [datasetVersion]);

  // ✅ Premium toast auto-dismiss
  useEffect(() => {
    if (!info && !error) return;
    const t = setTimeout(() => {
      setInfo("");
      setError("");
    }, 2200);
    return () => clearTimeout(t);
  }, [info, error]);

  const abortRef = useRef(null);
  const pollTimerRef = useRef(null);
  const unmountedRef = useRef(false);

  const canvasRef = useRef(null);

  const cursorLm = status?.cursorLandmarks ?? [];
  const otherLm = status?.otherLandmarks ?? [];

  // ✅ 서버 learner 상태 (AgentStatus에 들어있는 값)
  const learnEnabled = !!status?.learnEnabled;
  const learnCounts = status?.learnCounts || null;
  const learnCapture = status?.learnCapture || null;
  const learnLastPred = status?.learnLastPred || null;
  const learnLastTrainTs = status?.learnLastTrainTs || 0;

  // ✅ profile (hands_agent STATUS에 실어보내는 값)
  const learnProfile = status?.learnProfile || "default";
  const learnProfiles = Array.isArray(status?.learnProfiles)
    ? status.learnProfiles
    : ["default"];

  const profileOptions = useMemo(() => {
    const set = new Set([learnProfile, ...learnProfiles]);
    return Array.from(set);
  }, [learnProfile, learnProfiles]);

  // (선택) Python/DTO에 learnHasBackup이 없으면 그냥 항상 true로 취급
  const learnHasBackup =
    typeof status?.learnHasBackup === "boolean" ? status.learnHasBackup : null;
  const canRollback = learnHasBackup === null ? true : !!learnHasBackup;

  const derived = useMemo(() => {
    const s = status || {};
    return {
      connected: !!s.connected,
      mode: s.mode || "-",
      gesture: s.gesture || "NONE",
      otherGesture: s.otherGesture || "NONE",
      fps: typeof s.fps === "number" ? s.fps : null,
      cursorLmOk: isValidLmArr(cursorLm),
      otherLmOk: isValidLmArr(otherLm),
    };
  }, [status, cursorLm, otherLm]);

  const counts = useMemo(() => {
    const out = {};
    for (const h of HANDS) {
      out[h.id] = {};
      for (const l of LABELS) out[h.id][l] = 0;
    }
    for (const s of datasetRef.current.samples) {
      if (out?.[s.hand]?.[s.label] !== undefined) out[s.hand][s.label] += 1;
    }
    return out;
  }, [datasetVersion]);

  // ✅ Training 페이지는 /train/stats를 폴링해야 learner/profile 정보가 안정적으로 옴
  const fetchStatus = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const { data } = await api.get("/train/stats", {
        signal: controller.signal,
      });
      setStatus(data);
      setError("");
    } catch (e) {
      if (e?.name === "CanceledError" || e?.name === "AbortError") return;
      const msg = e?.response
        ? `상태 조회 실패 (HTTP ${e.response.status})${
            e.response.data ? `: ${String(e.response.data)}` : ""
          }`
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

  // draw whenever landmarks change
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    drawHands(canvas, {
      cursorLm,
      otherLm,
      theme,
      cursorLabel: `CURSOR (${derived.gesture})`,
      otherLabel: `OTHER (${derived.otherGesture})`,
    });
  }, [cursorLm, otherLm, theme, derived.gesture, derived.otherGesture]);

  // capture loop: on each status update, append sample if capturing (로컬)
  useEffect(() => {
    if (!capturing) return;

    const st = captureRef.current;
    if (!st) return;

    const now = Date.now();
    const elapsed = now - st.startedAt;
    const limit = Math.max(0.5, Number(st.seconds) || 2) * 1000;

    const lm = st.hand === "cursor" ? cursorLm : otherLm;
    if (isValidLmArr(lm)) {
      datasetRef.current.samples.push({
        ts: new Date().toISOString(),
        hand: st.hand,
        label: st.label,
        mode: status?.mode ?? null,
        gesture: status?.gesture ?? null,
        otherGesture: status?.otherGesture ?? null,
        landmarks: lm.map((p) => ({ x: p.x, y: p.y, z: p.z })),
      });
      st.collected += 1;
      if (st.collected % 3 === 0) setDatasetVersion((v) => v + 1);
    }

    if (elapsed >= limit) {
      setCapturing(false);
      captureRef.current = null;
      setDatasetVersion((v) => v + 1);
    }
  }, [status, cursorLm, otherLm, capturing]);

  const startCapture = () => {
    const sec = Math.max(0.5, Math.min(10, Number(captureSec) || 2));
    captureRef.current = {
      startedAt: Date.now(),
      seconds: sec,
      label,
      hand: handId,
      collected: 0,
    };
    setCapturing(true);
  };

  const addSnapshot = () => {
    const lm = handId === "cursor" ? cursorLm : otherLm;
    if (!isValidLmArr(lm)) {
      setError("랜드마크가 아직 안 잡혔어 (21개 포인트 필요)");
      return;
    }
    datasetRef.current.samples.push({
      ts: new Date().toISOString(),
      hand: handId,
      label,
      mode: status?.mode ?? null,
      gesture: status?.gesture ?? null,
      otherGesture: status?.otherGesture ?? null,
      landmarks: lm.map((p) => ({ x: p.x, y: p.y, z: p.z })),
    });
    setDatasetVersion((v) => v + 1);
  };

  const clearDataset = () => {
    datasetRef.current = {
      meta: {
        app: "GestureOS TrainingLab",
        createdAt: new Date().toISOString(),
        schema: "v1",
      },
      samples: [],
    };
    setDatasetVersion((v) => v + 1);
  };

  const exportDataset = () => {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    downloadJson(`gestureos-training-${stamp}.json`, datasetRef.current);
  };

  const capturedCount = captureRef.current?.collected ?? 0;

  // =========================
  // ✅ 서버 learner API
  // =========================
  const serverCapture = async () => {
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/capture", null, {
        params: {
          hand: handId,
          label,
          seconds: Number(captureSec) || 2,
          hz: 15,
        },
      });
      setInfo(data?.ok ? "Server capture started" : "Server capture failed");
    } catch (e) {
      const msg = e?.response
        ? `서버 캡처 실패 (HTTP ${e.response.status})`
        : e?.message || "서버 캡처 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverTrain = async () => {
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/train");
      setInfo(data?.ok ? "Training completed" : "Training failed");
    } catch (e) {
      const msg = e?.response
        ? `서버 Train 실패 (HTTP ${e.response.status})`
        : e?.message || "서버 Train 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverToggleEnable = async () => {
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const next = !learnEnabled;
      const { data } = await api.post("/train/enable", null, {
        params: { enabled: next },
      });
      setInfo(data?.ok ? (next ? "Learner enabled" : "Learner disabled") : "Enable failed");
    } catch (e) {
      const msg = e?.response
        ? `enable 실패 (HTTP ${e.response.status})`
        : e?.message || "enable 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverReset = async () => {
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/reset");
      setInfo(data?.ok ? "Reset done" : "Reset failed");
    } catch (e) {
      const msg = e?.response
        ? `reset 실패 (HTTP ${e.response.status})`
        : e?.message || "reset 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverRollback = async () => {
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/rollback");
      setInfo(data?.ok ? "Rollback done" : "Rollback failed");
    } catch (e) {
      const msg = e?.response
        ? `롤백 실패 (HTTP ${e.response.status})`
        : e?.message || "롤백 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  // =========================
  // ✅ profile API
  // =========================
  const serverSetProfile = async (name) => {
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/set", null, {
        params: { name },
      });
      setInfo(data?.ok ? `Profile: ${name}` : "Profile set failed");
    } catch (e) {
      setError(
        e?.response ? `profile set 실패 (HTTP ${e.response.status})` : e?.message || "profile set 실패"
      );
    } finally {
      setServerBusy(false);
    }
  };

  const serverCreateProfile = async () => {
    const name = String(newProfile || "").trim();
    if (!name) return;
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/create", null, {
        params: { name, copy: true },
      });
      setInfo(data?.ok ? `Profile created: ${name}` : "Create failed");
      setNewProfile("");
    } catch (e) {
      setError(e?.response ? `create 실패 (HTTP ${e.response.status})` : e?.message || "create 실패");
    } finally {
      setServerBusy(false);
    }
  };

  const serverDeleteProfile = async () => {
    if (learnProfile === "default") return;
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/delete", null, {
        params: { name: learnProfile },
      });
      setInfo(data?.ok ? `Profile deleted: ${learnProfile}` : "Delete failed");
    } catch (e) {
      setError(e?.response ? `delete 실패 (HTTP ${e.response.status})` : e?.message || "delete 실패");
    } finally {
      setServerBusy(false);
    }
  };

  const serverRenameProfile = async () => {
    const to = String(renameTo || "").trim();
    if (!to || learnProfile === "default") return;
    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/rename", null, {
        params: { from: learnProfile, to },
      });
      setInfo(data?.ok ? `Renamed: ${learnProfile} → ${to}` : "Rename failed");
      setRenameTo("");
    } catch (e) {
      setError(e?.response ? `rename 실패 (HTTP ${e.response.status})` : e?.message || "rename 실패");
    } finally {
      setServerBusy(false);
    }
  };

  const serverCaptureText = useMemo(() => {
    if (!learnCapture) return null;
    const h = learnCapture.hand || "-";
    const l = learnCapture.label || "-";
    const c = learnCapture.collected ?? 0;
    return `capturing: ${h} / ${l} / ${c}`;
  }, [learnCapture]);

  const lastTrainText = useMemo(() => {
    const ts = Number(learnLastTrainTs || 0);
    if (!ts) return null;
    try {
      const d = new Date(ts * 1000);
      return d.toLocaleString();
    } catch {
      return String(ts);
    }
  }, [learnLastTrainTs]);

  return (
    <div className="p-6 space-y-6 relative">
      {/* ✅ Premium Toast (replaces ugly banner) */}
      <div className="toast toast-top toast-end z-50">
        {info ? (
          <div className="flex items-start gap-3 rounded-2xl px-4 py-3 shadow-xl backdrop-blur-md bg-base-100/80 ring-1 ring-emerald-400/20">
            <svg className="h-5 w-5 mt-0.5 shrink-0 text-emerald-400" viewBox="0 0 24 24" fill="none">
              <path
                d="M20 6L9 17l-5-5"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <div className="text-sm leading-snug min-w-[220px]">
              <div className="font-semibold text-emerald-400">Done</div>
              <div className="opacity-80">{info}</div>
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-xs rounded-xl"
              onClick={() => setInfo("")}
              aria-label="close"
              title="close"
            >
              ✕
            </button>
          </div>
        ) : null}

        {error ? (
          <div className="flex items-start gap-3 rounded-2xl px-4 py-3 shadow-xl backdrop-blur-md bg-base-100/80 ring-1 ring-rose-400/20">
            <svg className="h-5 w-5 mt-0.5 shrink-0 text-rose-400" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 9v4m0 4h.01M10.29 3.86l-7.2 12.47A2 2 0 004.82 19h14.36a2 2 0 001.73-2.67l-7.2-12.47a2 2 0 00-3.46 0z"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <div className="text-sm leading-snug min-w-[220px]">
              <div className="font-semibold text-rose-400">Error</div>
              <div className="opacity-80">{error}</div>
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-xs rounded-xl"
              onClick={() => setError("")}
              aria-label="close"
              title="close"
            >
              ✕
            </button>
          </div>
        ) : null}
      </div>

      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-2xl font-bold">Training Lab</div>
          <div className="opacity-70 text-sm mt-1">
            손 랜드마크 프리뷰 + 서버 학습(프로토타입 learner) + 프로필 관리
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            className={cn("btn btn-sm", "rounded-xl")}
            onClick={exportDataset}
            disabled={!datasetRef.current.samples.length}
          >
            Export JSON
          </button>
          <button
            type="button"
            className={cn("btn btn-sm", "btn-ghost", "rounded-xl")}
            onClick={clearDataset}
            disabled={!datasetRef.current.samples.length}
          >
            Clear
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* LEFT: Preview */}
        <div className={cn("rounded-2xl ring-1 ring-base-300/50 bg-base-200/70 shadow-xl overflow-hidden")}>
          <div className="px-5 py-4 border-b border-base-300/40 flex items-center justify-between">
            <div className="font-semibold">Landmarks Preview</div>
            <div className="text-xs opacity-70">
              {loading ? "loading..." : derived.connected ? "connected" : "disconnected"}
              {derived.fps !== null ? ` · ${derived.fps.toFixed(1)} fps` : ""}
            </div>
          </div>

          <div className="p-4">
            <div className="w-full aspect-video rounded-xl ring-1 ring-base-300/40 bg-base-100/30 overflow-hidden">
              <canvas ref={canvasRef} className="w-full h-full" />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
              <div className={cn("rounded-xl ring-1 ring-base-300/40 bg-base-100/25 p-3")}>
                <div className="text-xs opacity-70">Cursor landmarks</div>
                <div className="mt-1 text-sm font-semibold">
                  {derived.cursorLmOk ? "OK (21)" : Array.isArray(cursorLm) ? `Not ready (${cursorLm.length || 0})` : "-"}
                </div>
                <div className="text-xs opacity-70 mt-1">gesture: {derived.gesture}</div>
              </div>
              <div className={cn("rounded-xl ring-1 ring-base-300/40 bg-base-100/25 p-3")}>
                <div className="text-xs opacity-70">Other landmarks</div>
                <div className="mt-1 text-sm font-semibold">
                  {derived.otherLmOk ? "OK (21)" : Array.isArray(otherLm) ? `Not ready (${otherLm.length || 0})` : "-"}
                </div>
                <div className="text-xs opacity-70 mt-1">gesture: {derived.otherGesture}</div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: Controls */}
        <div className={cn("rounded-2xl ring-1 ring-base-300/50 bg-base-200/70 shadow-xl overflow-hidden")}>
          <div className="px-5 py-4 border-b border-base-300/40">
            <div className="font-semibold">Controls</div>
            <div className="text-xs opacity-70 mt-1">
              로컬 수집 + 서버 learner(반자동 학습) + 프로필 + 롤백
            </div>
          </div>

          <div className="p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <div className="text-xs opacity-70 mb-1">Label</div>
                <select
                  className="select select-sm w-full rounded-xl"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                >
                  {LABELS.map((l) => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </div>

              <div>
                <div className="text-xs opacity-70 mb-1">Hand</div>
                <select
                  className="select select-sm w-full rounded-xl"
                  value={handId}
                  onChange={(e) => setHandId(e.target.value)}
                >
                  {HANDS.map((h) => (
                    <option key={h.id} value={h.id}>{h.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <div className="text-xs opacity-70 mb-1">Seconds</div>
                <input
                  className="input input-sm w-full rounded-xl"
                  type="number"
                  min={0.5}
                  max={10}
                  step={0.5}
                  value={captureSec}
                  onChange={(e) => setCaptureSec(e.target.value)}
                />
              </div>
            </div>

            {/* 로컬 캡처 */}
            <div className="rounded-xl ring-1 ring-base-300/40 bg-base-100/20 p-4">
              <div className="font-semibold text-sm">Local dataset</div>
              <div className="text-xs opacity-70 mt-1">
                브라우저에 샘플 저장(Export JSON 용)
              </div>

              <div className="flex items-center gap-2 flex-wrap mt-3">
                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", capturing ? "btn-disabled" : "btn-primary")}
                  onClick={startCapture}
                  disabled={capturing}
                >
                  {capturing ? `Capturing... (${capturedCount})` : "Capture (local)"}
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl")}
                  onClick={addSnapshot}
                >
                  Add snapshot
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm btn-ghost rounded-xl")}
                  onClick={() => fetchStatus()}
                >
                  Refresh now
                </button>
              </div>

              <div className="mt-3 text-xs opacity-70">
                total samples:{" "}
                <span className="font-semibold opacity-90">
                  {datasetRef.current.samples.length}
                </span>
              </div>
            </div>

            {/* ✅ 서버 learner + profile + rollback */}
            <div className="rounded-xl ring-1 ring-base-300/40 bg-base-100/20 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-semibold text-sm">Server learner</div>
                  <div className="text-xs opacity-70 mt-1">
                    /api/train/* 로 Python learner 제어
                  </div>
                </div>

                <div className="text-xs opacity-70">
                  enabled:{" "}
                  <span className={cn("font-semibold", learnEnabled ? "text-success" : "opacity-70")}>
                    {learnEnabled ? "ON" : "OFF"}
                  </span>
                </div>
              </div>

              {/* profile controls */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
                <div>
                  <div className="text-xs opacity-70 mb-1">Profile</div>
                  <select
                    className="select select-sm w-full rounded-xl"
                    value={learnProfile}
                    disabled={serverBusy}
                    onChange={(e) => serverSetProfile(e.target.value)}
                  >
                    {profileOptions.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <div className="text-xs opacity-70 mb-1">New profile</div>
                  <input
                    className="input input-sm w-full rounded-xl"
                    value={newProfile}
                    onChange={(e) => setNewProfile(e.target.value)}
                    placeholder="e.g. mouse, ppt, myhand"
                    disabled={serverBusy}
                  />
                </div>

                <div className="flex items-end gap-2">
                  <button
                    className="btn btn-sm rounded-xl"
                    onClick={serverCreateProfile}
                    disabled={serverBusy || !newProfile.trim()}
                  >
                    Create(copy)
                  </button>
                  <button
                    className="btn btn-sm btn-ghost rounded-xl"
                    onClick={serverDeleteProfile}
                    disabled={serverBusy || learnProfile === "default"}
                  >
                    Delete
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
                <div className="md:col-span-2">
                  <div className="text-xs opacity-70 mb-1">Rename (current → new)</div>
                  <input
                    className="input input-sm w-full rounded-xl"
                    value={renameTo}
                    onChange={(e) => setRenameTo(e.target.value)}
                    placeholder={learnProfile === "default" ? "default는 rename 불가" : "new name"}
                    disabled={serverBusy || learnProfile === "default"}
                  />
                </div>
                <div className="flex items-end">
                  <button
                    className="btn btn-sm rounded-xl w-full"
                    onClick={serverRenameProfile}
                    disabled={serverBusy || learnProfile === "default" || !renameTo.trim()}
                  >
                    Rename
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap mt-3">
                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", "btn-primary")}
                  onClick={serverCapture}
                  disabled={serverBusy || !derived.connected}
                >
                  Capture (server)
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl")}
                  onClick={serverTrain}
                  disabled={serverBusy || !derived.connected}
                >
                  Train
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", learnEnabled ? "btn-warning" : "btn-success")}
                  onClick={serverToggleEnable}
                  disabled={serverBusy || !derived.connected}
                >
                  {learnEnabled ? "Disable" : "Enable"}
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm btn-ghost rounded-xl")}
                  onClick={serverReset}
                  disabled={serverBusy || !derived.connected}
                >
                  Reset
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", "btn-outline")}
                  onClick={serverRollback}
                  disabled={serverBusy || !derived.connected || !canRollback}
                  title={
                    canRollback
                      ? "바로 이전 학습 상태로 되돌리기"
                      : "백업이 없어서 롤백 불가"
                  }
                >
                  Rollback
                </button>
              </div>

              {serverCaptureText ? (
                <div className="mt-2 text-xs opacity-70">{serverCaptureText}</div>
              ) : null}

              {lastTrainText ? (
                <div className="mt-1 text-xs opacity-70">
                  lastTrain: <span className="font-semibold opacity-90">{lastTrainText}</span>
                </div>
              ) : null}

              {/* 서버 카운트 */}
              <div className="mt-3">
                <div className="text-xs opacity-70 mb-1">server counts</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {HANDS.map((h) => (
                    <div
                      key={h.id}
                      className="rounded-xl ring-1 ring-base-300/30 bg-base-100/15 p-3"
                    >
                      <div className="text-xs opacity-70">{h.label}</div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                        {LABELS.map((l) => (
                          <div key={l} className="flex items-center justify-between">
                            <span className="opacity-80">{l}</span>
                            <span className="font-semibold">
                              {getServerCount(learnCounts, h.id, l)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                {learnLastPred ? (
                  <div className="mt-3 text-xs opacity-70">
                    lastPred:{" "}
                    <span className="font-semibold opacity-90">
                      {String(learnLastPred.label ?? "null")}
                    </span>{" "}
                    (score{" "}
                    {typeof learnLastPred.score === "number"
                      ? Number(learnLastPred.score).toFixed(3)
                      : "-"}
                    )
                    {" · rule "}
                    <span className="opacity-90">{String(learnLastPred.rule ?? "-")}</span>
                  </div>
                ) : null}
              </div>
            </div>

            {/* 로컬 데이터 카운트 */}
            <div className="divider my-2" />

            <div>
              <div className="font-semibold text-sm mb-2">Local dataset counts</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {HANDS.map((h) => (
                  <div
                    key={h.id}
                    className="rounded-xl ring-1 ring-base-300/40 bg-base-100/25 p-3"
                  >
                    <div className="text-xs opacity-70">{h.label}</div>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {LABELS.map((l) => (
                        <div key={l} className="flex items-center justify-between text-sm">
                          <span className="opacity-80">{l}</span>
                          <span className="font-semibold">{counts?.[h.id]?.[l] ?? 0}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <details className="mt-2">
              <summary className="cursor-pointer text-sm font-semibold">
                Raw status (debug)
              </summary>
              <pre className="mt-2 text-xs overflow-auto max-h-64 rounded-xl ring-1 ring-base-300/40 bg-base-100/20 p-3">
                {JSON.stringify(status, null, 2)}
              </pre>
            </details>
          </div>
        </div>
      </div>

      <div className="rounded-2xl ring-1 ring-base-300/50 bg-base-200/60 p-5">
        <div className="font-semibold">사용 순서 추천</div>
        <ul className="list-disc pl-5 mt-2 text-sm opacity-80 space-y-1">
          <li><b>Profile</b> 고르고</li>
          <li><b>Capture(server)</b>로 라벨 고르고 2초 수집</li>
          <li><b>Train</b> 눌러 모델 갱신</li>
          <li><b>Enable</b> 켜서 실제 인식에 적용</li>
          <li>망하면 <b>Rollback</b> (직전 상태 복구) / <b>Reset</b> (전체 초기화)</li>
        </ul>
      </div>
    </div>
  );
}
