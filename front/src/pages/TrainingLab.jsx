// src/pages/TrainingLab.jsx
import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../auth/AuthProvider";

const POLL_MS = 120;

// 학습/저장(서버 트레이닝) 가능 최소 샘플 수
const MIN_TRAIN_SAMPLES = 50;

const LABELS = ["OPEN_PALM", "FIST", "V_SIGN", "PINCH_INDEX", "OTHER"];
const LABEL_LABEL = {
  OPEN_PALM: "오픈 팜",
  FIST: "피스트",
  V_SIGN: "브이",
  PINCH_INDEX: "핀치",
  OTHER: "기타",
};

const HANDS = [
  { id: "cursor", label: "주 손(커서)" },
  { id: "other", label: "보조 손" },
];

const api = axios.create({
  baseURL: "/api",
  timeout: 8000,
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

  // grid
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
    cursorLabel || "주 손",
    18
  );
  drawOne(
    otherLm,
    "rgba(255,0,255,0.9)",
    "rgba(255,0,255,0.9)",
    otherLabel || "보조 손",
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

function StatusChip({ tone = "neutral", children, title }) {
  const base =
    "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] leading-none ring-1 select-none";
  const toneCls =
    tone === "ok"
      ? "bg-emerald-500/12 ring-emerald-400/25 text-base-content"
      : tone === "bad"
      ? "bg-rose-500/12 ring-rose-400/25 text-base-content"
      : tone === "warn"
      ? "bg-amber-500/12 ring-amber-400/25 text-base-content"
      : "bg-base-100/35 ring-base-300/50 text-base-content opacity-95";

  return (
    <span className={cn(base, toneCls)} title={title}>
      {children}
    </span>
  );
}

function StepDot({ done, label, hint }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span
        className={cn(
          "h-2.5 w-2.5 rounded-full ring-1",
          done
            ? "bg-emerald-400/80 ring-emerald-300/40"
            : "bg-base-100/40 ring-base-300/50"
        )}
      />
      <div className="min-w-0">
        <div className="text-[12px] font-semibold leading-none truncate">{label}</div>
        {hint ? (
          <div className="text-[11px] opacity-70 leading-none mt-0.5 truncate">
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function sanitizeProfileName(s) {
  const raw = String(s || "").trim();
  // 한글/영문/숫자/공백/_/- 허용 (서버에서 더 제한하면 여기 맞추면 됨)
  const cleaned = raw.replace(/[^\p{Script=Hangul}a-zA-Z0-9 _-]/gu, "");
  return cleaned.slice(0, 32).trim();
}

export default function TrainingLab({ theme = "dark" }) {
  const { user, isAuthed } = useAuth();

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

  // ✅ 수집 시작 전 준비(카운트다운)
  const [prepDelaySec, setPrepDelaySec] = useState(2);
  const [armLeftSec, setArmLeftSec] = useState(0);
  const armRef = useRef(null);
  const armTimerRef = useRef(null);

  // ✅ 서버 learner 작업 중 표시
  const [serverBusy, setServerBusy] = useState(false);

  // ✅ profile UI
  const [newProfile, setNewProfile] = useState("");
  const [renameTo, setRenameTo] = useState("");

  // ✅ DB profile list
  const [dbProfiles, setDbProfiles] = useState([]);

  // ✅ 로컬 카운트 실시간 표시용 state
  const [localSampleCount, setLocalSampleCount] = useState(0);
  const [capturedCountState, setCapturedCountState] = useState(0);

  // =========================
  // ✅ Auth / session scoping
  // =========================
  const memberIdRaw =
    user?.id ?? user?.memberId ?? user?.member_id ?? user?.email ?? null;

  const isGuest = !isAuthed || !memberIdRaw;

  const userHeaders = useMemo(() => {
    if (isGuest) return {};
    return { "X-User-Id": String(memberIdRaw) };
  }, [isGuest, memberIdRaw]);

  const displayProfile = useCallback((p) => {
    const s = String(p || "");
    if (s === "default") return "기본(default)";
    return s;
  }, []);

  const denyIfGuest = useCallback(
    (what = "이 작업") => {
      if (!isGuest) return false;
      setInfo(`게스트 모드에서는 ${what}을(를) 사용할 수 없어. 로그인 후 다시 시도해줘. (기본 프로필만 사용 가능)`);
      return true;
    },
    [isGuest]
  );

  // =========================
  // ✅ local dataset: user-scoped
  // =========================
  const datasetKey = useMemo(
    () => `trainingLab.dataset.v1.${isGuest ? "guest" : String(memberIdRaw).replace(/[^a-zA-Z0-9_-]/g, "_").toLowerCase()}`,
    [isGuest, memberIdRaw]
  );

  const datasetRef = useRef({
    meta: {
      app: "GestureOS TrainingLab",
      createdAt: new Date().toISOString(),
      schema: "v1",
    },
    samples: [],
  });
  const [datasetVersion, setDatasetVersion] = useState(0);

  useEffect(() => {
    // 계정 변경/로그아웃 시 로컬 캡처 중단
    setCapturing(false);
    captureRef.current = null;
    setCapturedCountState(0);

    try {
      const raw = localStorage.getItem(datasetKey);
      if (!raw) {
        datasetRef.current = {
          meta: {
            app: "GestureOS TrainingLab",
            createdAt: new Date().toISOString(),
            schema: "v1",
          },
          samples: [],
        };
        setDatasetVersion((v) => v + 1);
        return;
      }

      const parsed = JSON.parse(raw);
      if (parsed && Array.isArray(parsed.samples)) {
        datasetRef.current = parsed;
        setDatasetVersion((v) => v + 1);
      }
    } catch (_) {}
  }, [datasetKey]);

  useEffect(() => {
    try {
      localStorage.setItem(datasetKey, JSON.stringify(datasetRef.current));
    } catch (_) {}
  }, [datasetVersion, datasetKey]);

  useEffect(() => {
    setLocalSampleCount(datasetRef.current.samples.length);
  }, [datasetVersion]);

  // ✅ Toast auto-dismiss
  useEffect(() => {
    if (!info && !error) return;
    const t = setTimeout(() => {
      setInfo("");
      setError("");
    }, 2400);
    return () => clearTimeout(t);
  }, [info, error]);

  const abortRef = useRef(null);
  const pollTimerRef = useRef(null);
  const unmountedRef = useRef(false);
  const canvasRef = useRef(null);

  // 최신 status를 비동기 콜백에서도 안전하게 참조
  const statusRef = useRef(null);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const cursorLm = status?.cursorLandmarks ?? [];
  const otherLm = status?.otherLandmarks ?? [];

  // ✅ 서버 learner 상태
  const learnEnabled = !!status?.learnEnabled;
  const learnCounts = status?.learnCounts || null;
  const learnCapture = status?.learnCapture || null;
  const learnLastTrainTs = status?.learnLastTrainTs || 0;

  const learnProfile = status?.learnProfile || "default";
  const learnProfiles = Array.isArray(status?.learnProfiles)
    ? status.learnProfiles
    : ["default"];

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

  const selectedLmOk = handId === "cursor" ? derived.cursorLmOk : derived.otherLmOk;
  const selectedServerCount = getServerCount(learnCounts, handId, label);

  const isHandOkNow = (hand) => {
    const s = statusRef.current || status || {};
    const lm = hand === "cursor" ? s.cursorLandmarks ?? [] : s.otherLandmarks ?? [];
    return isValidLmArr(lm);
  };

  const waitForHandOk = async (hand, timeoutMs = 2500) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (isHandOkNow(hand)) return true;
      await new Promise((r) => setTimeout(r, 120));
    }
    return isHandOkNow(hand);
  };

  // 사용자 관점 진행 상태
  const stepProfile = !!learnProfile;
  const stepDetect = !!selectedLmOk;
  const stepCollect = selectedServerCount >= MIN_TRAIN_SAMPLES;
  const stepTrain = Number(learnLastTrainTs || 0) > 0;
  const stepApply = !!learnEnabled;

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

  // =========================
  // ✅ DB profiles fetch
  // =========================
  useEffect(() => {
    if (isGuest) {
      setDbProfiles([]);
      return;
    }
    let alive = true;
    (async () => {
      try {
        const { data } = await api.get("/train/profile/db/list", {
          headers: userHeaders,
        });
        const list = Array.isArray(data?.profiles) ? data.profiles : [];
        if (alive) setDbProfiles(list);
      } catch {
        if (alive) setDbProfiles([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, [isGuest, userHeaders]);

  const profileOptions = useMemo(() => {
    const set = new Set(["default", learnProfile, ...(learnProfiles || []), ...(dbProfiles || [])]);
    const all = Array.from(set).filter(Boolean);
    // default 맨 위
    const base = all.filter((x) => x === "default").map((x) => ({ value: x, label: displayProfile(x) }));
    const rest = all
      .filter((x) => x !== "default")
      .sort((a, b) => String(a).localeCompare(String(b)))
      .map((x) => ({ value: x, label: displayProfile(x) }));
    return [...base, ...rest];
  }, [learnProfile, learnProfiles, dbProfiles, displayProfile]);

  // =========================
  // ✅ status polling
  // =========================
  const fetchStatus = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const { data } = await api.get("/train/stats", {
        signal: controller.signal,
        headers: userHeaders,
      });
      setStatus(data);
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
  }, [userHeaders]);

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
      if (armTimerRef.current) clearInterval(armTimerRef.current);
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
      cursorLabel: `주 손 (${derived.gesture})`,
      otherLabel: `보조 손 (${derived.otherGesture})`,
    });
  }, [cursorLm, otherLm, theme, derived.gesture, derived.otherGesture]);

  // capture loop: 로컬 샘플 수집 (실시간 카운트)
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
        제스처: status?.gesture ?? null,
        otherGesture: status?.otherGesture ?? null,
        landmarks: lm.map((p) => ({ x: p.x, y: p.y, z: p.z })),
      });

      st.collected += 1;

      // ✅ UI 즉시 갱신
      setCapturedCountState(st.collected);
      setLocalSampleCount(datasetRef.current.samples.length);

      // 너무 잦은 렌더 싫으면 2~3장마다만 올려도 됨.
      setDatasetVersion((v) => v + 1);
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
    setCapturedCountState(0);
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
      제스처: status?.gesture ?? null,
      otherGesture: status?.otherGesture ?? null,
      landmarks: lm.map((p) => ({ x: p.x, y: p.y, z: p.z })),
    });
    setLocalSampleCount(datasetRef.current.samples.length);
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
    setCapturedCountState(0);
    setLocalSampleCount(0);
    setDatasetVersion((v) => v + 1);
  };

  const exportDataset = () => {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    downloadJson(`gestureos-training-${stamp}.json`, datasetRef.current);
  };

  // =========================
  // ✅ 서버 learner API
  // =========================
  const clearArming = useCallback(() => {
    if (armTimerRef.current) {
      clearInterval(armTimerRef.current);
      armTimerRef.current = null;
    }
    armRef.current = null;
    setArmLeftSec(0);
  }, []);

  const warnDefaultSharedOnce = useRef(false);
  const warnDefaultShared = () => {
    if (learnProfile !== "default") return;
    if (warnDefaultSharedOnce.current) return;
    warnDefaultSharedOnce.current = true;
    setInfo("기본(default) 프로필은 공용일 수 있어. 가능하면 새 프로필 만들어서 진행해.");
  };

  const serverCaptureNow = async (cfg) => {
    setError("");
    setInfo("");

    if (denyIfGuest("서버 샘플 수집")) return;

    const hand = cfg?.hand ?? handId;
    const lab = cfg?.label ?? label;
    const seconds = cfg?.seconds ?? (Number(captureSec) || 2);
    const hz = cfg?.hz ?? 15;

    warnDefaultShared();

    setServerBusy(true);
    try {
      const { data } = await api.post("/train/capture", null, {
        params: { hand, label: lab, seconds, hz },
        headers: userHeaders,
      });
      setInfo(data?.ok ? "서버 샘플 수집 시작" : "서버 샘플 수집 실패");
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `서버 샘플 수집 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "서버 샘플 수집 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const armServerCapture = () => {
    setError("");
    setInfo("");

    if (denyIfGuest("서버 샘플 수집")) return;

    const delay = Math.max(0, Math.min(10, Number(prepDelaySec) || 0));
    const cfg = {
      kind: "server",
      fireAt: Date.now() + delay * 1000,
      hand: handId,
      label,
      seconds: Number(captureSec) || 2,
      hz: 15,
    };

    if (delay <= 0.01) {
      serverCaptureNow(cfg);
      return;
    }

    clearArming();
    armRef.current = cfg;
    setArmLeftSec(Math.ceil(delay));

    armTimerRef.current = setInterval(() => {
      const leftMs = cfg.fireAt - Date.now();
      if (leftMs <= 0) {
        clearArming();
        (async () => {
          const okHand = await waitForHandOk(cfg.hand, 2500);
          if (!okHand) {
            setError("손이 아직 안 잡혀서 수집을 시작 못했어. 손을 올린 뒤 다시 눌러줘");
            return;
          }
          await serverCaptureNow(cfg);
        })();
      } else {
        setArmLeftSec(Math.ceil(leftMs / 1000));
      }
    }, 100);
  };

  const serverTrain = async () => {
    setError("");
    setInfo("");

    if (denyIfGuest("서버 학습")) return;

    warnDefaultShared();

    setServerBusy(true);
    try {
      const { data } = await api.post("/train/train", null, {
        headers: userHeaders,
      });
      setInfo(data?.ok ? "학습 완료" : "학습 실패");
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `서버 학습 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "서버 학습 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverToggleEnable = async () => {
    setError("");
    setInfo("");
    if (denyIfGuest("학습 적용")) return;

    setServerBusy(true);
    try {
      const next = !learnEnabled;
      const { data } = await api.post("/train/enable", null, {
        params: { 적용: next },
        headers: userHeaders,
      });
      setInfo(data?.ok ? (next ? "학습 적용: 켜짐" : "학습 적용: 꺼짐") : "적용 전환 실패");
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `적용 전환 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "적용 전환 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverReset = async () => {
    setError("");
    setInfo("");

    if (denyIfGuest("초기화")) return;

    if (learnProfile === "default") {
      setInfo("기본(default)은 공용일 수 있어서 초기화는 막아뒀어. 새 프로필로 진행해.");
      return;
    }

    setServerBusy(true);
    try {
      const { data } = await api.post("/train/reset", null, { headers: userHeaders });
      setInfo(data?.ok ? "초기화 완료" : "초기화 실패");
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `초기화 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "초기화 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverRollback = async () => {
    setError("");
    setInfo("");

    if (denyIfGuest("되돌리기")) return;

    if (learnProfile === "default") {
      setInfo("기본(default)은 공용일 수 있어서 되돌리기는 막아뒀어. 새 프로필로 진행해.");
      return;
    }

    setServerBusy(true);
    try {
      const { data } = await api.post("/train/rollback", null, { headers: userHeaders });
      setInfo(data?.ok ? "되돌리기 완료" : "되돌리기 실패");
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `되돌리기 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "되돌리기 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  // =========================
  // ✅ profile API
  // =========================
  const serverSetProfile = async (name) => {
    const target = isGuest ? "default" : String(name || "default");

    if (isGuest && target !== "default") {
      setInfo("게스트 모드에서는 기본(default)만 사용할 수 있어.");
      return;
    }

    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/set", null, {
        params: { name: target },
        headers: userHeaders,
      });
      setInfo(data?.ok ? `프로필 적용: ${displayProfile(target)}` : "프로필 적용 실패");
      await fetchStatus();
    } catch (e) {
      const msg = e?.response
        ? `프로필 적용 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "프로필 적용 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverCreateProfile = async () => {
    if (denyIfGuest("프로필 생성")) return;

    const name = sanitizeProfileName(newProfile);
    if (!name) {
      setError("프로필 이름이 비었거나 사용할 수 없는 문자야.");
      return;
    }

    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/create", null, {
        params: { name, copy: true },
        headers: userHeaders,
      });

      if (!data?.ok) {
        setError(`프로필 생성 실패${data ? `: ${JSON.stringify(data)}` : ""}`);
        return;
      }

      setInfo(`프로필 생성: ${displayProfile(name)}`);
      setNewProfile("");

      // 생성 후 바로 선택
      await serverSetProfile(name);

      // DB list 갱신
      try {
        const r = await api.get("/train/profile/db/list", { headers: userHeaders });
        setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
      } catch {}
    } catch (e) {
      const msg = e?.response
        ? `프로필 생성 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "프로필 생성 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverDeleteProfile = async () => {
    if (denyIfGuest("프로필 삭제")) return;
    if (learnProfile === "default") {
      setInfo("기본(default)은 삭제할 수 없어.");
      return;
    }

    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/delete", null, {
        params: { name: learnProfile },
        headers: userHeaders,
      });
      setInfo(data?.ok ? `프로필 삭제: ${displayProfile(learnProfile)}` : "프로필 삭제 실패");
      await fetchStatus();

      try {
        const r = await api.get("/train/profile/db/list", { headers: userHeaders });
        setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
      } catch {}
    } catch (e) {
      const msg = e?.response
        ? `프로필 삭제 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "프로필 삭제 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  const serverRenameProfile = async () => {
    if (denyIfGuest("프로필 이름 변경")) return;
    if (learnProfile === "default") {
      setInfo("기본(default)은 이름을 바꿀 수 없어.");
      return;
    }

    const to = sanitizeProfileName(renameTo);
    if (!to) {
      setError("새 이름이 비었거나 사용할 수 없는 문자야.");
      return;
    }

    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/rename", null, {
        params: { from: learnProfile, to },
        headers: userHeaders,
      });

      setInfo(data?.ok ? `이름 변경: ${displayProfile(learnProfile)} → ${displayProfile(to)}` : "이름 변경 실패");
      setRenameTo("");
      await fetchStatus();

      try {
        const r = await api.get("/train/profile/db/list", { headers: userHeaders });
        setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
      } catch {}
    } catch (e) {
      const msg = e?.response
        ? `이름 변경 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
        : e?.message || "이름 변경 실패";
      setError(msg);
    } finally {
      setServerBusy(false);
    }
  };

  // =========================
  // ✅ 로그인 유저: main 자동 생성/선택 (실패 시 에러 토스트 표시)
  // =========================
  const initMainProfileRef = useRef(false);
  useEffect(() => {
    if (isGuest || !derived.connected) {
      initMainProfileRef.current = false;
      return;
    }
    if (initMainProfileRef.current) return;
    initMainProfileRef.current = true;

    (async () => {
      try {
        const desired = "main";

        // create if missing
        const combined = new Set([...(learnProfiles || []), ...(dbProfiles || []), learnProfile]);
        if (!combined.has(desired)) {
          const r = await api.post("/train/profile/create", null, {
            params: { name: desired, copy: true },
            headers: userHeaders,
          });
          if (!r?.data?.ok) {
            setError(`자동 main 생성 실패: ${JSON.stringify(r?.data || {})}`);
            return;
          }
        }

        // set to main if currently default
        if (learnProfile === "default") {
          const s = await api.post("/train/profile/set", null, {
            params: { name: desired },
            headers: userHeaders,
          });
          if (!s?.data?.ok) {
            setError(`자동 main 선택 실패: ${JSON.stringify(s?.data || {})}`);
            return;
          }
        }

        await fetchStatus();
      } catch (e) {
        const msg = e?.response
          ? `자동 main 세팅 실패 (HTTP ${e.response.status})${e.response.data ? `: ${String(e.response.data)}` : ""}`
          : e?.message || "자동 main 세팅 실패";
        setError(msg);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGuest, derived.connected]);

  const serverCaptureText = useMemo(() => {
    if (!learnCapture) return null;
    const h = learnCapture.hand || "-";
    const l = learnCapture.label || "-";
    const c = learnCapture.collected ?? 0;
    const handText = h === "cursor" ? "주 손" : h === "other" ? "보조 손" : h;
    const labelText = LABEL_LABEL[l] ?? l;
    return `수집 중: ${handText} / ${labelText} / ${c}`;
  }, [learnCapture]);

  const pendingCaptureText = useMemo(() => {
    if (!armLeftSec) return null;
    const cfg = armRef.current;
    const h = cfg?.hand || handId;
    const l = cfg?.label || label;
    const handText = h === "cursor" ? "주 손" : h === "other" ? "보조 손" : h;
    const labelText = LABEL_LABEL[l] ?? l;
    return `준비 중: ${handText} / ${labelText} / ${armLeftSec}s`;
  }, [armLeftSec, handId, label]);

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
      {/* ✅ Toast */}
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
              <div className="font-semibold text-emerald-400">완료</div>
              <div className="opacity-80">{info}</div>
            </div>
            <button type="button" className="btn btn-ghost btn-xs rounded-xl" onClick={() => setInfo("")} aria-label="close" title="닫기">
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
              <div className="font-semibold text-rose-400">오류</div>
              <div className="opacity-80">{error}</div>
            </div>
            <button type="button" className="btn btn-ghost btn-xs rounded-xl" onClick={() => setError("")} aria-label="close" title="닫기">
              ✕
            </button>
          </div>
        ) : null}
      </div>

      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div className="space-y-2">
          <div className="flex items-baseline gap-3 flex-wrap">
            <div className="text-2xl font-bold">모션 인식 학습</div>

            <div className="flex items-center gap-2 flex-wrap">
              <StatusChip tone={isGuest ? "warn" : "ok"} title="로그인 상태">
                {isGuest ? "게스트" : "로그인됨"}
              </StatusChip>

              <StatusChip tone={derived.connected ? "ok" : "bad"} title="Agent WebSocket">
                {derived.connected ? "연결됨" : "연결 끊김"}
              </StatusChip>

              <StatusChip title="현재 모드">모드: {derived.mode}</StatusChip>

              <StatusChip title="학습 프로필">프로필: {displayProfile(learnProfile)}</StatusChip>

              <StatusChip tone={learnEnabled ? "ok" : "neutral"} title="학습 적용">
                학습 적용: {learnEnabled ? "켜짐" : "꺼짐"}
              </StatusChip>
            </div>
          </div>

          <details className="max-w-[720px]">
            <summary className="cursor-pointer text-xs opacity-70 select-none">사용 방법(간단)</summary>
            <div className="mt-2 text-xs opacity-75 leading-relaxed">
              1) <b>프로필</b> 선택 → 2) <b>샘플 수집</b> (준비시간 후 시작) → 3) <b>학습</b> → 4) <b>적용 켜기</b>.
              문제가 생기면 <b>되돌리기</b> 또는 <b>초기화</b>.
              {isGuest ? (
                <>
                  <br />
                  <span className="text-amber-300/90">게스트 모드: 서버 학습/프로필 저장은 제한되며 기본 프로필만 사용 가능</span>
                </>
              ) : null}
            </div>
          </details>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* LEFT: Preview */}
        <div className={cn("rounded-2xl ring-1 ring-base-300/50 bg-base-200/70 shadow-xl overflow-hidden")}>
          <div className="px-5 py-4 border-b border-base-300/40 flex items-center justify-between">
            <div className="font-semibold">랜드마크 미리보기</div>
            <div className="text-xs opacity-70">{loading ? "불러오는 중..." : derived.connected ? "연결됨" : "연결 끊김"}</div>
          </div>

          <div className="p-4">
            <div className="w-full aspect-video rounded-xl ring-1 ring-base-300/40 bg-base-100/30 overflow-hidden">
              <canvas ref={canvasRef} className="w-full h-full" />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
              <div className={cn("rounded-xl ring-1 ring-base-300/40 bg-base-100/25 p-3")}>
                <div className="text-xs opacity-70">주 손 랜드마크</div>
                <div className="mt-1 text-sm font-semibold">
                  {derived.cursorLmOk ? "정상 (21)" : Array.isArray(cursorLm) ? `미인식 (${cursorLm.length || 0})` : "-"}
                </div>
                <div className="text-xs opacity-70 mt-1">제스처: {derived.gesture}</div>
              </div>

              <div className={cn("rounded-xl ring-1 ring-base-300/40 bg-base-100/25 p-3")}>
                <div className="text-xs opacity-70">보조 손 랜드마크</div>
                <div className="mt-1 text-sm font-semibold">
                  {derived.otherLmOk ? "정상 (21)" : Array.isArray(otherLm) ? `미인식 (${otherLm.length || 0})` : "-"}
                </div>
                <div className="text-xs opacity-70 mt-1">제스처: {derived.otherGesture}</div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: Controls */}
        <div className={cn("rounded-2xl ring-1 ring-base-300/50 bg-base-200/70 shadow-xl overflow-hidden")}>
          <div className="px-5 py-4 border-b border-base-300/40 flex items-center justify-between gap-3 flex-wrap">
            <div className="font-semibold">설정</div>
            <div className="flex items-center gap-2 flex-wrap">
              <StatusChip tone={stepDetect ? "ok" : "warn"} title="선택한 손 랜드마크 상태">
                {stepDetect ? "손 인식됨" : "손 미인식"}
              </StatusChip>

              <StatusChip tone={stepCollect ? "ok" : "neutral"} title="학습에 필요한 샘플 상태">
                샘플: {stepCollect ? "충분" : "부족"}
              </StatusChip>

              {lastTrainText ? <StatusChip title="마지막 학습">최근 학습: {lastTrainText}</StatusChip> : null}
            </div>
          </div>

          <div className="p-5 space-y-4">
            {/* stepper */}
            <div className={cn("rounded-2xl ring-1 ring-base-300/40 bg-base-100/15 p-4")} title="프로필 → 수집 → 학습 → 적용 순서">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <StepDot done={stepProfile} label="1. 프로필" hint={displayProfile(learnProfile)} />
                <StepDot done={stepDetect} label="2. 인식" hint={stepDetect ? "정상" : "손이 안 잡힘"} />
                <StepDot done={stepCollect} label="3. 수집" hint={stepCollect ? "충분" : "부족"} />
                <StepDot done={stepTrain} label="4. 학습" hint={stepTrain ? "완료" : "미실행"} />
                <StepDot done={stepApply} label="5. 적용" hint={stepApply ? "적용됨" : "꺼짐"} />
              </div>

              <div className="mt-3 flex items-center justify-between gap-3 flex-wrap">
                <div className="text-xs opacity-70">
                  선택: <b>{handId === "cursor" ? "주 손" : "보조 손"}</b> · <b>{LABEL_LABEL[label] ?? label}</b> ·{" "}
                  {Number(captureSec) || 2}초
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                  {pendingCaptureText ? <StatusChip tone="warn" title="준비 중">{pendingCaptureText}</StatusChip> : null}
                  {serverCaptureText ? <StatusChip tone="warn" title="서버 수집 중">{serverCaptureText}</StatusChip> : null}

                  <button type="button" className={cn("btn btn-xs btn-ghost rounded-xl")} onClick={fetchStatus} title="상태 새로고침">
                    새로고침
                  </button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div>
                <div className="text-xs opacity-70 mb-1">라벨</div>
                <select className="select select-sm w-full rounded-xl" value={label} onChange={(e) => setLabel(e.target.value)}>
                  {LABELS.map((l) => (
                    <option key={l} value={l}>{LABEL_LABEL[l] ?? l}</option>
                  ))}
                </select>
              </div>

              <div>
                <div className="text-xs opacity-70 mb-1">손</div>
                <select className="select select-sm w-full rounded-xl" value={handId} onChange={(e) => setHandId(e.target.value)}>
                  {HANDS.map((h) => (
                    <option key={h.id} value={h.id}>{h.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <div className="text-xs opacity-70 mb-1">수집 시간(초)</div>
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

              <div>
                <div className="text-xs opacity-70 mb-1">준비 시간(초)</div>
                <input
                  className="input input-sm w-full rounded-xl"
                  type="number"
                  min={0}
                  max={10}
                  step={0.5}
                  value={prepDelaySec}
                  onChange={(e) => setPrepDelaySec(e.target.value)}
                />
              </div>
            </div>

            {/* 서버 learner + profile */}
            <div className="rounded-xl ring-1 ring-base-300/40 bg-base-100/20 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-semibold text-sm">서버 학습기</div>
                  <div className="text-xs opacity-70 mt-1">샘플 수집 → 학습 → 적용</div>
                </div>
                <div className="text-xs opacity-70">
                  적용:{" "}
                  <span className={cn("font-semibold", learnEnabled ? "text-success" : "opacity-70")}>
                    {learnEnabled ? "켜짐" : "꺼짐"}
                  </span>
                </div>
              </div>

              {/* profile controls */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
                <div>
                  <div className="text-xs opacity-70 mb-1">프로필</div>
                  <select
                    className="select select-sm w-full rounded-xl"
                    value={learnProfile}
                    disabled={serverBusy}
                    onChange={(e) => serverSetProfile(e.target.value)}
                  >
                    {profileOptions.map((p) => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <div className="text-xs opacity-70 mb-1">새 프로필</div>
                  <input
                    className="input input-sm w-full rounded-xl"
                    value={newProfile}
                    onChange={(e) => setNewProfile(e.target.value)}
                    placeholder="예: main, office, myhand"
                    disabled={serverBusy || isGuest}
                  />
                </div>

                <div className="flex items-end">
                  <button
                    className="btn btn-sm rounded-xl w-full"
                    onClick={serverCreateProfile}
                    disabled={serverBusy || isGuest || !sanitizeProfileName(newProfile)}
                    title={isGuest ? "게스트 모드에서는 프로필 생성 불가" : ""}
                  >
                    생성(복사)
                  </button>
                </div>
              </div>

              <details className="mt-3 rounded-xl ring-1 ring-base-300/40 bg-base-100/10 p-3">
                <summary className="cursor-pointer select-none text-sm font-semibold">고급: 이름 변경 / 삭제</summary>

                <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="md:col-span-2">
                    <div className="text-xs opacity-70 mb-1">이름 변경(현재 → 새 이름)</div>
                    <input
                      className="input input-sm w-full rounded-xl"
                      value={renameTo}
                      onChange={(e) => setRenameTo(e.target.value)}
                      placeholder={isGuest ? "게스트는 이름 변경 불가" : learnProfile === "default" ? "기본 프로필은 이름 변경 불가" : "새 이름"}
                      disabled={serverBusy || isGuest || learnProfile === "default"}
                    />
                  </div>
                  <div className="flex items-end gap-2">
                    <button
                      className="btn btn-sm rounded-xl w-full"
                      onClick={serverRenameProfile}
                      disabled={serverBusy || isGuest || learnProfile === "default" || !sanitizeProfileName(renameTo)}
                    >
                      이름 변경
                    </button>
                  </div>
                </div>

                <div className="mt-3">
                  <button
                    className="btn btn-sm btn-ghost rounded-xl"
                    onClick={() => {
                      if (isGuest) return;
                      if (learnProfile === "default") return;
                      if (window.confirm(`프로필 '${displayProfile(learnProfile)}' 를 삭제할까요?`)) serverDeleteProfile();
                    }}
                    disabled={serverBusy || isGuest || learnProfile === "default"}
                  >
                    현재 프로필 삭제
                  </button>
                </div>
              </details>

              <div className="flex items-center gap-2 flex-wrap mt-3">
                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", armLeftSec > 0 ? "btn-warning" : "btn-primary")}
                  onClick={() => {
                    if (armLeftSec > 0) clearArming();
                    else armServerCapture();
                  }}
                  disabled={serverBusy || !derived.connected || isGuest}
                  title={selectedLmOk ? "" : "손이 안 잡혀도 예약 수집 가능. 준비 시간 안에 손을 올려줘"}
                >
                  {armLeftSec > 0 ? `준비중 ${armLeftSec}s · 취소` : "샘플 수집"}
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl")}
                  onClick={serverTrain}
                  disabled={serverBusy || !derived.connected || !stepCollect || isGuest}
                  title={!stepCollect ? "샘플이 아직 부족해. 샘플 수집을 더 해줘" : ""}
                >
                  학습
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", learnEnabled ? "btn-warning" : "btn-success")}
                  onClick={serverToggleEnable}
                  disabled={serverBusy || !derived.connected || isGuest || (!learnEnabled && !stepTrain)}
                  title={!learnEnabled && !stepTrain ? "적용 전에 학습을 먼저 해줘" : ""}
                >
                  {learnEnabled ? "적용 끄기" : "적용 켜기"}
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm btn-ghost rounded-xl")}
                  onClick={() => {
                    if (isGuest) return;
                    if (learnProfile === "default") {
                      setInfo("기본(default)은 공용일 수 있어서 초기화는 막아뒀어. 새 프로필로 진행해.");
                      return;
                    }
                    if (window.confirm("서버 학습기를 초기화할까요? (프로필 모델이 리셋돼요)")) serverReset();
                  }}
                  disabled={serverBusy || !derived.connected || isGuest}
                >
                  초기화
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", "btn-outline")}
                  onClick={() => {
                    if (isGuest) return;
                    if (!canRollback) return;
                    if (learnProfile === "default") {
                      setInfo("기본(default)은 공용일 수 있어서 되돌리기는 막아뒀어. 새 프로필로 진행해.");
                      return;
                    }
                    if (window.confirm("직전 학습 상태로 되돌릴까요?")) serverRollback();
                  }}
                  disabled={serverBusy || !derived.connected || !canRollback || isGuest}
                  title={canRollback ? "바로 이전 학습 상태로 되돌리기" : "백업이 없어서 되돌리기 불가"}
                >
                  되돌리기
                </button>
              </div>

              {pendingCaptureText ? <div className="mt-2 text-xs opacity-70">{pendingCaptureText}</div> : null}
              {serverCaptureText ? <div className="mt-2 text-xs opacity-70">{serverCaptureText}</div> : null}
              {lastTrainText ? (
                <div className="mt-1 text-xs opacity-70">
                  최근 학습: <span className="font-semibold opacity-90">{lastTrainText}</span>
                </div>
              ) : null}

              {/* ✅ "서버 샘플 수 / 최근 예측" 섹션 제거 */}
            </div>

            {/* 로컬 데이터셋 */}
            <details className="rounded-xl ring-1 ring-base-300/40 bg-base-100/10 p-4">
              <summary className="cursor-pointer select-none text-sm font-semibold">로컬 샘플 관리</summary>

              <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="rounded-xl ring-1 ring-base-300/30 bg-base-100/15 p-3">
                  <div className="text-xs opacity-70">로컬 누적 샘플</div>
                  <div className="mt-1 text-sm font-semibold">{localSampleCount}</div>
                  {capturing ? (
                    <div className="text-xs opacity-70 mt-1">수집 중… (+{capturedCountState})</div>
                  ) : (
                    <div className="text-xs opacity-70 mt-1">대기</div>
                  )}
                </div>

                <div className="flex items-end gap-2">
                  <button className="btn btn-sm rounded-xl w-full" onClick={startCapture} disabled={!derived.connected}>
                    로컬 연속 수집
                  </button>
                </div>

                <div className="flex items-end gap-2">
                  <button className="btn btn-sm btn-ghost rounded-xl w-full" onClick={addSnapshot} disabled={!derived.connected}>
                    스냅샷 1장 추가
                  </button>
                </div>
              </div>

              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <button className="btn btn-sm btn-ghost rounded-xl" onClick={exportDataset}>
                  내보내기(JSON)
                </button>
                <button
                  className="btn btn-sm btn-ghost rounded-xl"
                  onClick={() => {
                    if (window.confirm("로컬 샘플을 전부 지울까?")) clearDataset();
                  }}
                >
                  로컬 초기화
                </button>
              </div>

              <details className="mt-3">
                <summary className="cursor-pointer select-none text-xs opacity-70">라벨별 로컬 카운트 보기</summary>
                <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
                  {HANDS.map((h) => (
                    <div key={h.id} className="rounded-xl ring-1 ring-base-300/30 bg-base-100/15 p-3">
                      <div className="text-xs opacity-70">{h.label}</div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                        {LABELS.map((l) => (
                          <div key={l} className="flex items-center justify-between">
                            <span className="opacity-80">{LABEL_LABEL[l] ?? l}</span>
                            <span className="font-semibold">{counts?.[h.id]?.[l] ?? 0}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            </details>
          </div>
        </div>
      </div>
    </div>
  );
}
