// src/pages/TrainingLab.jsx
import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../auth/AuthProvider";

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
        <div className="text-[12px] font-semibold leading-none truncate">
          {label}
        </div>
        {hint ? (
          <div className="text-[11px] opacity-70 leading-none mt-0.5 truncate">
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  );
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

  // ✅ 서버 learner 작업 중 표시
  const [serverBusy, setServerBusy] = useState(false);

  // ✅ profile UI
  const [newProfile, setNewProfile] = useState("");
  const [renameTo, setRenameTo] = useState("");

  // ✅ DB profile list
  const [dbProfiles, setDbProfiles] = useState([]);

  // =========================
  // ✅ Auth / session scoping
  // =========================
  const memberIdRaw =
    user?.id ?? user?.memberId ?? user?.member_id ?? user?.email ?? null;

  const memberKey = useMemo(() => {
    const raw = memberIdRaw ? String(memberIdRaw) : "guest";
    return raw.replace(/[^a-zA-Z0-9_-]/g, "_").toLowerCase();
  }, [memberIdRaw]);

  const isGuest = !isAuthed || !memberIdRaw;

  const userHeaders = useMemo(() => {
    if (isGuest) return {};
    return { "X-User-Id": String(memberIdRaw) };
  }, [isGuest, memberIdRaw]);

  // 프로필 파일/이름 충돌 방지용 네임스페이스 (서버/DB에도 그대로 저장됨)
  const NS = useMemo(() => (isGuest ? "" : `u${memberKey}__`), [isGuest, memberKey]);

  const stripNS = useCallback(
    (name) => {
      const n = String(name || "").trim();
      if (!NS) return n;
      return n.startsWith(NS) ? n.slice(NS.length) : n;
    },
    [NS]
  );

  const withNS = useCallback(
    (name) => {
      const n = stripNS(name);
      if (!n) return "";
      return `${NS}${n}`;
    },
    [NS, stripNS]
  );

  const displayProfile = useCallback(
    (p) => {
      const s = String(p || "");
      if (s === "default") return "default(기본)";
      if (!NS) return s;
      return s.startsWith(NS) ? s.slice(NS.length) : s; // 내꺼 아니면 원문 표시
    },
    [NS]
  );

  const denyIfGuest = useCallback(
    (what = "이 작업") => {
      if (!isGuest) return false;
      setInfo(`게스트 모드: ${what}은 로그인 후 가능합니다. (default만 사용 가능)`);
      return true;
    },
    [isGuest]
  );

  // =========================
  // ✅ local dataset: user-scoped
  // =========================
  const datasetKey = useMemo(
    () => `trainingLab.dataset.v1.${isGuest ? "guest" : memberKey}`,
    [isGuest, memberKey]
  );

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

  useEffect(() => {
    // 계정 변경/로그아웃 시 로컬 캡처 중단
    setCapturing(false);
    captureRef.current = null;

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

  const selectedLmOk =
    handId === "cursor" ? derived.cursorLmOk : derived.otherLmOk;
  const selectedServerCount = getServerCount(learnCounts, handId, label);

  // 사용자 관점 "진행 상태"
  const stepProfile = !!learnProfile;
  const stepDetect = !!selectedLmOk;
  const stepCollect = selectedServerCount >= 10; // learner 기본 min_samples=10
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
    // 게스트는 default만
    if (isGuest) return [{ value: "default", label: "default(기본)" }];

    const set = new Set([
      "default",
      learnProfile,
      ...(learnProfiles || []),
      ...(dbProfiles || []),
    ]);

    // 내 네임스페이스 + default만 노출 (현재 선택이 외부값이면 안전하게 추가 노출)
    const all = Array.from(set).filter(Boolean);

    const mine = all
      .filter((p) => p === "default" || String(p).startsWith(NS))
      .map((p) => ({ value: p, label: displayProfile(p) }));

    // 혹시 현재 프로필이 mine에 안 들어가면 포함
    if (
      learnProfile &&
      learnProfile !== "default" &&
      !mine.some((x) => x.value === learnProfile)
    ) {
      mine.push({ value: learnProfile, label: displayProfile(learnProfile) });
    }

    // label 기준 정렬 (default 맨 위)
    const base = mine.filter((x) => x.value === "default");
    const rest = mine
      .filter((x) => x.value !== "default")
      .sort((a, b) => a.label.localeCompare(b.label));

    return [...base, ...rest];
  }, [isGuest, learnProfile, learnProfiles, dbProfiles, NS, displayProfile]);

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
        ? `상태 조회 실패 (HTTP ${e.response.status})${
            e.response.data ? `: ${String(e.response.data)}` : ""
          }`
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

    if (denyIfGuest("서버 캡처")) return;
    if (learnProfile === "default") {
      setInfo("default는 공용 기본값이라 학습 저장은 새 프로필에서만 가능");
      return;
    }
    if (!String(learnProfile).startsWith(NS)) {
      setInfo("내 프로필에서만 캡처 가능");
      return;
    }

    setServerBusy(true);
    try {
      const { data } = await api.post("/train/capture", null, {
        params: {
          hand: handId,
          label,
          seconds: Number(captureSec) || 2,
          hz: 15,
        },
        headers: userHeaders,
      });
      setInfo(data?.ok ? "Server capture started" : "Server capture failed");
      await fetchStatus();
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

    if (denyIfGuest("서버 트레이닝")) return;
    if (learnProfile === "default") {
      setInfo("default는 공용 기본값이라 학습 저장은 새 프로필에서만 가능");
      return;
    }
    if (!String(learnProfile).startsWith(NS)) {
      setInfo("내 프로필에서만 트레이닝 가능");
      return;
    }

    setServerBusy(true);
    try {
      const { data } = await api.post("/train/train", null, {
        headers: userHeaders,
      });
      setInfo(data?.ok ? "Training completed" : "Training failed");
      await fetchStatus();
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
        headers: userHeaders,
      });
      setInfo(
        data?.ok ? (next ? "Learner enabled" : "Learner disabled") : "Enable failed"
      );
      await fetchStatus();
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

    if (denyIfGuest("Reset")) return;
    if (learnProfile === "default") {
      setInfo("default는 공용 기본값이라 Reset은 내 프로필에서만 가능");
      return;
    }
    if (!String(learnProfile).startsWith(NS)) {
      setInfo("내 프로필에서만 Reset 가능");
      return;
    }

    setServerBusy(true);
    try {
      const { data } = await api.post("/train/reset", null, {
        headers: userHeaders,
      });
      setInfo(data?.ok ? "Reset done" : "Reset failed");
      await fetchStatus();
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

    if (denyIfGuest("Rollback")) return;
    if (learnProfile === "default") {
      setInfo("default는 공용 기본값이라 Rollback은 내 프로필에서만 가능");
      return;
    }
    if (!String(learnProfile).startsWith(NS)) {
      setInfo("내 프로필에서만 Rollback 가능");
      return;
    }

    setServerBusy(true);
    try {
      const { data } = await api.post("/train/rollback", null, {
        headers: userHeaders,
      });
      setInfo(data?.ok ? "Rollback done" : "Rollback failed");
      await fetchStatus();
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
    const target = isGuest ? "default" : name;

    // 게스트는 default만
    if (isGuest && target !== "default") {
      setInfo("게스트 모드: default만 사용 가능");
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
      setInfo(data?.ok ? `Profile: ${displayProfile(target)}` : "Profile set failed");
      await fetchStatus();
      // profile 바꾸면 DB list도 한번 갱신
      if (!isGuest) {
        try {
          const r = await api.get("/train/profile/db/list", { headers: userHeaders });
          setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
        } catch {}
      }
    } catch (e) {
      setError(
        e?.response ? `profile set 실패 (HTTP ${e.response.status})` : e?.message || "profile set 실패"
      );
    } finally {
      setServerBusy(false);
    }
  };

  const serverCreateProfile = async () => {
    if (denyIfGuest("프로필 생성")) return;

    const name = String(newProfile || "").trim();
    if (!name) return;

    const serverName = withNS(name);
    if (!serverName) return;

    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/create", null, {
        params: { name: serverName, copy: true },
        headers: userHeaders,
      });
      setInfo(data?.ok ? `Profile created: ${displayProfile(serverName)}` : "Create failed");
      setNewProfile("");
      await fetchStatus();

      // DB list 갱신
      try {
        const r = await api.get("/train/profile/db/list", { headers: userHeaders });
        setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
      } catch {}
    } catch (e) {
      setError(e?.response ? `create 실패 (HTTP ${e.response.status})` : e?.message || "create 실패");
    } finally {
      setServerBusy(false);
    }
  };

  const serverDeleteProfile = async () => {
    if (denyIfGuest("프로필 삭제")) return;
    if (learnProfile === "default") return;
    if (!String(learnProfile).startsWith(NS)) {
      setInfo("내 프로필만 삭제 가능");
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
      setInfo(data?.ok ? `Profile deleted: ${displayProfile(learnProfile)}` : "Delete failed");
      await fetchStatus();

      // DB list 갱신
      try {
        const r = await api.get("/train/profile/db/list", { headers: userHeaders });
        setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
      } catch {}
    } catch (e) {
      setError(e?.response ? `delete 실패 (HTTP ${e.response.status})` : e?.message || "delete 실패");
    } finally {
      setServerBusy(false);
    }
  };

  const serverRenameProfile = async () => {
    if (denyIfGuest("프로필 이름 변경")) return;

    const to = String(renameTo || "").trim();
    if (!to || learnProfile === "default") return;

    if (!String(learnProfile).startsWith(NS)) {
      setInfo("내 프로필만 rename 가능");
      return;
    }

    const serverTo = withNS(to);
    if (!serverTo) return;

    setError("");
    setInfo("");
    setServerBusy(true);
    try {
      const { data } = await api.post("/train/profile/rename", null, {
        params: { from: learnProfile, to: serverTo },
        headers: userHeaders,
      });
      setInfo(
        data?.ok
          ? `Renamed: ${displayProfile(learnProfile)} → ${displayProfile(serverTo)}`
          : "Rename failed"
      );
      setRenameTo("");
      await fetchStatus();

      // DB list 갱신
      try {
        const r = await api.get("/train/profile/db/list", { headers: userHeaders });
        setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
      } catch {}
    } catch (e) {
      setError(e?.response ? `rename 실패 (HTTP ${e.response.status})` : e?.message || "rename 실패");
    } finally {
      setServerBusy(false);
    }
  };

  // =========================
  // ✅ Guest/login profile automation
  // =========================
  const forcingDefaultRef = useRef(false);
  useEffect(() => {
    if (!derived.connected) return;
    if (!isGuest) {
      forcingDefaultRef.current = false;
      return;
    }
    if (learnProfile === "default") return;
    if (forcingDefaultRef.current) return;

    forcingDefaultRef.current = true;
    (async () => {
      try {
        await serverSetProfile("default");
      } finally {
        forcingDefaultRef.current = false;
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGuest, derived.connected, learnProfile]);

  // 로그인 유저는 main 자동 생성 + 선택 (1회)
  const initMainProfileRef = useRef(null);
  useEffect(() => {
    if (isGuest || !derived.connected) {
      initMainProfileRef.current = null;
      return;
    }
    if (initMainProfileRef.current === memberKey) return;
    initMainProfileRef.current = memberKey;

    const desired = withNS("main");

    (async () => {
      try {
        const combined = new Set([
          ...(learnProfiles || []),
          ...(dbProfiles || []),
          learnProfile,
        ]);

        if (!combined.has(desired)) {
          await api.post("/train/profile/create", null, {
            params: { name: desired, copy: true },
            headers: userHeaders,
          });
        }

        if (learnProfile === "default" || !String(learnProfile).startsWith(NS)) {
          await api.post("/train/profile/set", null, {
            params: { name: desired },
            headers: userHeaders,
          });
        }

        await fetchStatus();
      } catch {
        // 실패해도 폴링으로 상태는 계속 갱신됨
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGuest, derived.connected, memberKey]);

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
      {/* ✅ Premium Toast */}
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
        <div className="space-y-2">
          <div className="flex items-baseline gap-3 flex-wrap">
            <div className="text-2xl font-bold">Training Lab</div>
            <div className="flex items-center gap-2 flex-wrap">
              <StatusChip tone={isGuest ? "warn" : "ok"} title="로그인 상태">
                {isGuest ? "GUEST (default only)" : `USER: ${memberKey}`}
              </StatusChip>

              <StatusChip tone={derived.connected ? "ok" : "bad"} title="Agent WebSocket">
                {derived.connected ? "CONNECTED" : "DISCONNECTED"}
              </StatusChip>
              <StatusChip title="현재 모드">MODE: {derived.mode}</StatusChip>
              <StatusChip title="학습 프로필">PROFILE: {displayProfile(learnProfile)}</StatusChip>
              <StatusChip tone={learnEnabled ? "ok" : "neutral"} title="Learner 적용 여부">
                LEARN: {learnEnabled ? "ON" : "OFF"}
              </StatusChip>
              {derived.fps !== null ? (
                <StatusChip title="FPS">FPS {derived.fps.toFixed(1)}</StatusChip>
              ) : null}
            </div>
          </div>

          <details className="max-w-[720px]">
            <summary className="cursor-pointer text-xs opacity-70 select-none">
              사용 방법(간단)
            </summary>
            <div className="mt-2 text-xs opacity-75 leading-relaxed">
              1) <b>Profile</b> 선택 → 2) <b>Capture(server)</b>로 샘플 수집(손이 잡힌 상태에서)
              → 3) <b>Train</b> → 4) <b>Enable</b>로 적용. 문제가 생기면 <b>Rollback</b> 또는 <b>Reset</b>.
              {isGuest ? (
                <>
                  <br />
                  <span className="text-amber-300/90">
                    게스트 모드: 서버 학습/프로필 저장은 제한되고 default만 사용 가능
                  </span>
                </>
              ) : null}
            </div>
          </details>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            className={cn("btn btn-sm", "rounded-xl")}
            onClick={exportDataset}
            disabled={!datasetRef.current.samples.length}
            title="브라우저 로컬에 쌓인 샘플을 JSON으로 내보내기"
          >
            Export (JSON)
          </button>
          <button
            type="button"
            className={cn("btn btn-sm", "btn-ghost", "rounded-xl")}
            onClick={() => {
              if (!datasetRef.current.samples.length) return;
              if (window.confirm("로컬 샘플을 전부 지울까요?")) clearDataset();
            }}
            disabled={!datasetRef.current.samples.length}
            title="브라우저 로컬 샘플 삭제"
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
                  {derived.cursorLmOk
                    ? "OK (21)"
                    : Array.isArray(cursorLm)
                    ? `Not ready (${cursorLm.length || 0})`
                    : "-"}
                </div>
                <div className="text-xs opacity-70 mt-1">gesture: {derived.gesture}</div>
              </div>
              <div className={cn("rounded-xl ring-1 ring-base-300/40 bg-base-100/25 p-3")}>
                <div className="text-xs opacity-70">Other landmarks</div>
                <div className="mt-1 text-sm font-semibold">
                  {derived.otherLmOk
                    ? "OK (21)"
                    : Array.isArray(otherLm)
                    ? `Not ready (${otherLm.length || 0})`
                    : "-"}
                </div>
                <div className="text-xs opacity-70 mt-1">gesture: {derived.otherGesture}</div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: Controls */}
        <div className={cn("rounded-2xl ring-1 ring-base-300/50 bg-base-200/70 shadow-xl overflow-hidden")}>
          <div className="px-5 py-4 border-b border-base-300/40 flex items-center justify-between gap-3 flex-wrap">
            <div className="font-semibold">Controls</div>
            <div className="flex items-center gap-2 flex-wrap">
              <StatusChip tone={stepDetect ? "ok" : "warn"} title="선택한 손 랜드마크 상태">
                {stepDetect ? "HAND OK" : "HAND NOT READY"}
              </StatusChip>
              <StatusChip tone={stepCollect ? "ok" : "neutral"} title="선택 라벨 서버 샘플 수">
                SAMPLES {selectedServerCount}/10
              </StatusChip>
              {lastTrainText ? (
                <StatusChip title="마지막 학습">LAST TRAIN {lastTrainText}</StatusChip>
              ) : null}
            </div>
          </div>

          <div className="p-5 space-y-4">
            {/* quick stepper */}
            <div className={cn("rounded-2xl ring-1 ring-base-300/40 bg-base-100/15 p-4")} title="프로필 → 수집 → 학습 → 적용 순서">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <StepDot done={stepProfile} label="1. Profile" hint={displayProfile(learnProfile)} />
                <StepDot done={stepDetect} label="2. Detect" hint={stepDetect ? "OK" : "손이 안잡힘"} />
                <StepDot done={stepCollect} label="3. Capture" hint={`${selectedServerCount}/10`} />
                <StepDot done={stepTrain} label="4. Train" hint={stepTrain ? "완료" : "미실행"} />
                <StepDot done={stepApply} label="5. Enable" hint={stepApply ? "적용됨" : "OFF"} />
              </div>
              <div className="mt-3 flex items-center justify-between gap-3 flex-wrap">
                <div className="text-xs opacity-70">
                  선택: <b>{handId === "cursor" ? "Cursor" : "Other"}</b> · <b>{label}</b> · {Number(captureSec) || 2}s
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  {serverCaptureText ? (
                    <StatusChip tone="warn" title="서버 캡처 중">{serverCaptureText}</StatusChip>
                  ) : null}
                  <button type="button" className={cn("btn btn-xs btn-ghost rounded-xl")} onClick={fetchStatus} title="상태 새로고침">
                    Refresh
                  </button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <div className="text-xs opacity-70 mb-1">Label</div>
                <select className="select select-sm w-full rounded-xl" value={label} onChange={(e) => setLabel(e.target.value)}>
                  {LABELS.map((l) => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </div>

              <div>
                <div className="text-xs opacity-70 mb-1">Hand</div>
                <select className="select select-sm w-full rounded-xl" value={handId} onChange={(e) => setHandId(e.target.value)}>
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
            <details className="rounded-xl ring-1 ring-base-300/40 bg-base-100/20 p-4">
              <summary className="cursor-pointer select-none flex items-center justify-between gap-2">
                <span className="font-semibold text-sm">Local dataset (optional)</span>
                <span className="text-xs opacity-70">
                  samples: <b className="opacity-90">{datasetRef.current.samples.length}</b>
                </span>
              </summary>

              <div className="mt-3">
                <div className="text-xs opacity-70">
                  브라우저에 샘플 저장 → Export(JSON) 용(서버 학습에는 직접 안 씀)
                </div>

                <div className="flex items-center gap-2 flex-wrap mt-3">
                  <button
                    type="button"
                    className={cn("btn btn-sm rounded-xl", capturing ? "btn-disabled" : "btn-primary")}
                    onClick={startCapture}
                    disabled={capturing || !selectedLmOk}
                    title={!selectedLmOk ? "손 랜드마크가 잡혀야 수집돼" : ""}
                  >
                    {capturing ? `Capturing... (${capturedCount})` : "Capture (local)"}
                  </button>

                  <button
                    type="button"
                    className={cn("btn btn-sm rounded-xl")}
                    onClick={addSnapshot}
                    disabled={!selectedLmOk}
                    title={!selectedLmOk ? "손 랜드마크가 잡혀야 저장돼" : ""}
                  >
                    Add snapshot
                  </button>
                </div>
              </div>
            </details>

            {/* 서버 learner + profile */}
            <div className="rounded-xl ring-1 ring-base-300/40 bg-base-100/20 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-semibold text-sm">Server learner</div>
                  <div className="text-xs opacity-70 mt-1">샘플 수집 → 학습 → 적용(Enable)</div>
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
                      <option key={p.value} value={p.value}>{p.label}</option>
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
                    disabled={serverBusy || isGuest}
                  />
                </div>

                <div className="flex items-end">
                  <button
                    className="btn btn-sm rounded-xl w-full"
                    onClick={serverCreateProfile}
                    disabled={serverBusy || isGuest || !newProfile.trim()}
                    title={isGuest ? "게스트 모드에서는 프로필 생성 불가" : ""}
                  >
                    Create(copy)
                  </button>
                </div>
              </div>

              <details className="mt-3 rounded-xl ring-1 ring-base-300/40 bg-base-100/10 p-3">
                <summary className="cursor-pointer select-none text-sm font-semibold">고급: Rename / Delete</summary>

                <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="md:col-span-2">
                    <div className="text-xs opacity-70 mb-1">Rename (current → new)</div>
                    <input
                      className="input input-sm w-full rounded-xl"
                      value={renameTo}
                      onChange={(e) => setRenameTo(e.target.value)}
                      placeholder={
                        isGuest ? "게스트는 rename 불가" : learnProfile === "default" ? "default는 rename 불가" : "new name"
                      }
                      disabled={
                        serverBusy ||
                        isGuest ||
                        learnProfile === "default" ||
                        !String(learnProfile).startsWith(NS)
                      }
                    />
                  </div>
                  <div className="flex items-end gap-2">
                    <button
                      className="btn btn-sm rounded-xl w-full"
                      onClick={serverRenameProfile}
                      disabled={
                        serverBusy ||
                        isGuest ||
                        learnProfile === "default" ||
                        !String(learnProfile).startsWith(NS) ||
                        !renameTo.trim()
                      }
                    >
                      Rename
                    </button>
                  </div>
                </div>

                <div className="mt-3">
                  <button
                    className="btn btn-sm btn-ghost rounded-xl"
                    onClick={() => {
                      if (isGuest) return;
                      if (learnProfile === "default") return;
                      if (!String(learnProfile).startsWith(NS)) return;
                      if (window.confirm(`프로필 '${displayProfile(learnProfile)}' 를 삭제할까요?`)) serverDeleteProfile();
                    }}
                    disabled={
                      serverBusy ||
                      isGuest ||
                      learnProfile === "default" ||
                      !String(learnProfile).startsWith(NS)
                    }
                  >
                    Delete current profile
                  </button>
                </div>
              </details>

              <div className="flex items-center gap-2 flex-wrap mt-3">
                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", "btn-primary")}
                  onClick={serverCapture}
                  disabled={
                    serverBusy ||
                    !derived.connected ||
                    !selectedLmOk ||
                    isGuest ||
                    learnProfile === "default" ||
                    !String(learnProfile).startsWith(NS)
                  }
                >
                  Capture (server)
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl")}
                  onClick={serverTrain}
                  disabled={
                    serverBusy ||
                    !derived.connected ||
                    !stepCollect ||
                    isGuest ||
                    learnProfile === "default" ||
                    !String(learnProfile).startsWith(NS)
                  }
                  title={!stepCollect ? `샘플이 부족함: ${selectedServerCount}/10` : ""}
                >
                  Train
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", learnEnabled ? "btn-warning" : "btn-success")}
                  onClick={serverToggleEnable}
                  disabled={serverBusy || !derived.connected || (!learnEnabled && !stepTrain)}
                  title={!learnEnabled && !stepTrain ? "Enable 전에 Train을 한 번 해줘" : ""}
                >
                  {learnEnabled ? "Disable" : "Enable"}
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm btn-ghost rounded-xl")}
                  onClick={() => {
                    if (isGuest) return;
                    if (window.confirm("서버 learner를 초기화할까요? (프로필 모델이 리셋돼요)")) serverReset();
                  }}
                  disabled={
                    serverBusy ||
                    !derived.connected ||
                    isGuest ||
                    learnProfile === "default" ||
                    !String(learnProfile).startsWith(NS)
                  }
                >
                  Reset
                </button>

                <button
                  type="button"
                  className={cn("btn btn-sm rounded-xl", "btn-outline")}
                  onClick={() => {
                    if (isGuest) return;
                    if (!canRollback) return;
                    if (window.confirm("직전 학습 상태로 롤백할까요?")) serverRollback();
                  }}
                  disabled={
                    serverBusy ||
                    !derived.connected ||
                    !canRollback ||
                    isGuest ||
                    learnProfile === "default" ||
                    !String(learnProfile).startsWith(NS)
                  }
                  title={
                    canRollback ? "바로 이전 학습 상태로 되돌리기" : "백업이 없어서 롤백 불가"
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

              <details className="mt-3 rounded-xl ring-1 ring-base-300/40 bg-base-100/10 p-3">
                <summary className="cursor-pointer select-none text-sm font-semibold">
                  Counts (server) / lastPred
                </summary>
                <div className="mt-3">
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
              </details>
            </div>

            <details className="mt-1 rounded-xl ring-1 ring-base-300/40 bg-base-100/10 p-3">
              <summary className="cursor-pointer select-none text-sm font-semibold">
                Local dataset counts
              </summary>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
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
            </details>

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
    </div>
  );
}
