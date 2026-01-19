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
  const [info, setInfo] = useState(""); // ✅ 서버 호출 결과 메시지
  const [loading, setLoading] = useState(true);

  // capture controls (로컬)
  const [label, setLabel] = useState("OPEN_PALM");
  const [handId, setHandId] = useState("cursor");
  const [captureSec, setCaptureSec] = useState(2);
  const [capturing, setCapturing] = useState(false);
  const captureRef = useRef(null);

  // ✅ 서버 learner 작업 중 표시
  const [serverBusy, setServerBusy] = useState(false);

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

  const abortRef = useRef(null);
  const pollTimerRef = useRef(null);
  const unmountedRef = useRef(false);

  const canvasRef = useRef(null);

  const cursorLm = status?.cursorLandmarks ?? [];
  const otherLm = status?.otherLandmarks ?? [];

  // ✅ 서버 learner 상태 (StatusService가 내려주는 값)
  const learnEnabled = !!status?.learnEnabled;
  const learnCounts = status?.learnCounts || null;
  const learnCapture = status?.learnCapture || null;
  const learnLastPred = status?.learnLastPred || null;

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
  // ✅ 서버 learner API 연결 (여기가 “마지막 코드” 들어갈 자리)
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
      setInfo(data?.ok ? "서버 캡처 시작됨 ✅" : "서버 캡처 실패 ❌");
      // 캡처 상태는 status.learnCapture로 올라오니까 폴링으로 자동 반영됨
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
      setInfo(data?.ok ? "서버 Train 완료 ✅" : "서버 Train 실패 ❌");
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
      setInfo(data?.ok ? `learner ${next ? "ON" : "OFF"} ✅` : "enable 실패 ❌");
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
      setInfo(data?.ok ? "서버 learner reset ✅" : "reset 실패 ❌");
    } catch (e) {
      const msg = e?.response
        ? `reset 실패 (HTTP ${e.response.status})`
        : e?.message || "reset 실패";
      setError(msg);
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

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-2xl font-bold">Training Lab</div>
          <div className="opacity-70 text-sm mt-1">
            손 랜드마크를 눈으로 확인하고, 로컬/서버 학습까지 붙이는 테스트 페이지
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

            {info ? (
              <div className="mt-3 alert alert-success rounded-xl">
                <span className="text-sm">{info}</span>
              </div>
            ) : null}

            {error ? (
              <div className="mt-3 alert alert-error rounded-xl">
                <span className="text-sm">{error}</span>
              </div>
            ) : null}
          </div>
        </div>

        {/* RIGHT: Controls */}
        <div className={cn("rounded-2xl ring-1 ring-base-300/50 bg-base-200/70 shadow-xl overflow-hidden")}>
          <div className="px-5 py-4 border-b border-base-300/40">
            <div className="font-semibold">Controls</div>
            <div className="text-xs opacity-70 mt-1">
              로컬 수집 + 서버 learner(반자동 학습) 제어
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

            {/* ✅ 서버 learner */}
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
              </div>

              {serverCaptureText ? (
                <div className="mt-2 text-xs opacity-70">
                  {serverCaptureText}
                </div>
              ) : null}

              {/* 서버 카운트 */}
              <div className="mt-3">
                <div className="text-xs opacity-70 mb-1">server counts</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {HANDS.map((h) => (
                    <div key={h.id} className="rounded-xl ring-1 ring-base-300/30 bg-base-100/15 p-3">
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
                    (score {typeof learnLastPred.score === "number" ? learnLastPred.score.toFixed(3) : "-"})
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
                  <div key={h.id} className="rounded-xl ring-1 ring-base-300/40 bg-base-100/25 p-3">
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
          <li><b>Capture(server)</b>로 라벨 고르고 2초 수집</li>
          <li><b>Train</b> 눌러 모델 갱신</li>
          <li><b>Enable</b> 켜서 실제 인식에 적용</li>
          <li>오발동 나면 <b>Disable</b>로 끄고 다시 수집/학습</li>
        </ul>
      </div>
    </div>
  );
}
