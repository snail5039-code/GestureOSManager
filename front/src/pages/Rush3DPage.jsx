// src/pages/Rush3DPage.jsx
// -----------------------------------------------------------------------------
// Rush 3D - 통합 버전(전체 코드)
// - RUSH 입력 방식(손=HAND / 스틱=COLOR) 로비에서 선택 가능
// - 서버에는 mode=RUSH만 전송 (서버 enum에 RUSH_HAND/RUSH_COLOR 없어서 400 방지)
// - Start Game 누르면 자동으로:
//    1) /api/control/mode?mode=RUSH
//    2) /api/control/start
//   후 게임 시작
// - Apply Now 버튼도 동일하게 즉시 적용(게임 시작 X)
// - 로비 UI가 아래 잘리던 문제: 중앙정렬(items-center) → 상단정렬(items-start + pt)로 올림
// -----------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { THEME } from "../theme/themeTokens";

/* =============================================================================
   유틸
============================================================================= */
function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

/** seed+index로 0~1 결정적 난수 (매번 같은 패턴) */
function hash01(n) {
  let x = n | 0;
  x ^= x >>> 16;
  x = Math.imul(x, 0x7feb352d);
  x ^= x >>> 15;
  x = Math.imul(x, 0x846ca68b);
  x ^= x >>> 16;
  return (x >>> 0) / 4294967296;
}

/** 2D 선분 vs AABB 교차 정보(Liang–Barsky) */
function segRectIntersectInfo(a, b, minX, maxX, minY, maxY) {
  let t0 = 0,
    t1 = 1;
  const dx = b.x - a.x;
  const dy = b.y - a.y;

  const clip = (p, q) => {
    if (p === 0) return q >= 0;
    const r = q / p;
    if (p < 0) {
      if (r > t1) return false;
      if (r > t0) t0 = r;
    } else {
      if (r < t0) return false;
      if (r < t1) t1 = r;
    }
    return true;
  };

  if (!clip(-dx, a.x - minX)) return null;
  if (!clip(dx, maxX - a.x)) return null;
  if (!clip(-dy, a.y - minY)) return null;
  if (!clip(dy, maxY - a.y)) return null;
  if (t0 > t1) return null;

  const tMid = (t0 + t1) * 0.5;
  return {
    tEnter: t0,
    tExit: t1,
    tMid,
    ix: a.x + dx * tMid,
    iy: a.y + dy * tMid,
  };
}

/* =============================================================================
   status → 양손 읽기(스마트 정규화)
============================================================================= */
function readTwoHandsFromStatus(status) {
  if (!status) return null;
  const enabled = status.enabled == null ? true : !!status.enabled;

  const lx =
    status.leftPointerX ??
    status.pointerLeftX ??
    status.handLeftX ??
    status.leftX ??
    status?.left?.x ??
    status?.handLeft?.x ??
    null;

  const ly =
    status.leftPointerY ??
    status.pointerLeftY ??
    status.handLeftY ??
    status.leftY ??
    status?.left?.y ??
    status?.handLeft?.y ??
    null;

  const lTracking =
    status.leftTracking ??
    status.isLeftTracking ??
    status.leftHandTracking ??
    status.leftHandPresent ??
    status?.left?.tracking ??
    status?.handLeft?.tracking ??
    null;

  const rx =
    status.rightPointerX ??
    status.pointerRightX ??
    status.handRightX ??
    status.rightX ??
    status?.right?.x ??
    status?.handRight?.x ??
    null;

  const ry =
    status.rightPointerY ??
    status.pointerRightY ??
    status.handRightY ??
    status.rightY ??
    status?.right?.y ??
    status?.handRight?.y ??
    null;

  const rTracking =
    status.rightTracking ??
    status.isRightTracking ??
    status.rightHandTracking ??
    status.rightHandPresent ??
    status?.right?.tracking ??
    status?.handRight?.tracking ??
    null;

  const sx =
    status.pointerX ?? status.cursorX ?? status.x ?? status?.pointer?.x ?? null;
  const sy =
    status.pointerY ?? status.cursorY ?? status.y ?? status?.pointer?.y ?? null;

  const sTracking =
    status.isTracking ??
    status.tracking ??
    status.handTracking ??
    status.handPresent ??
    null;

  const hasLeft = lx != null && ly != null;
  const hasRight = rx != null && ry != null;
  const hasSingle = sx != null && sy != null;

  if (!hasLeft && !hasRight && !hasSingle) return null;

  const norm = (v, axis) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return null;

    if (n >= 0 && n <= 1) return n; // already normalized
    if (n >= -1.1 && n <= 1.1) return clamp((n + 1) * 0.5, 0, 1); // NDC

    const w =
      status.screenW ??
      status.width ??
      status.videoW ??
      window.innerWidth ??
      1920;
    const h =
      status.screenH ??
      status.height ??
      status.videoH ??
      window.innerHeight ??
      1080;

    const denom = axis === "x" ? Number(w) : Number(h);
    if (!Number.isFinite(denom) || denom <= 0) return clamp(n, 0, 1);

    return clamp(n / denom, 0, 1); // pixels -> normalized
  };

  const lg =
    status.leftGesture ??
    status.leftHandGesture ??
    status?.left?.gesture ??
    status?.handLeft?.gesture ??
    null;

  const rg =
    status.rightGesture ??
    status.rightHandGesture ??
    status?.right?.gesture ??
    status?.handRight?.gesture ??
    null;

  const left = hasLeft
    ? {
        nx: norm(lx, "x"),
        ny: norm(ly, "y"),
        tracking: (lTracking == null ? true : !!lTracking) && enabled,
        gesture: lg ?? "NONE",
      }
    : null;

  const right = hasRight
    ? {
        nx: norm(rx, "x"),
        ny: norm(ry, "y"),
        tracking: (rTracking == null ? true : !!rTracking) && enabled,
        gesture: rg ?? "NONE",
      }
    : null;

  const single = hasSingle
    ? {
        nx: norm(sx, "x"),
        ny: norm(sy, "y"),
        tracking: (sTracking == null ? true : !!sTracking) && enabled,
        gesture: "NONE",
      }
    : null;

  const safeLeft = left && left.nx != null && left.ny != null ? left : null;
  const safeRight =
    right && right.nx != null && right.ny != null ? right : null;
  const safeSingle =
    single && single.nx != null && single.ny != null ? single : null;

  if (!safeLeft && !safeRight && !safeSingle) return null;
  return { left: safeLeft, right: safeRight, single: safeSingle };
}

/* =============================================================================
   NDC → 트랙 로컬 z평면 교차 (할당 최소화)
============================================================================= */
function ndcToTrackLocalOnZPlane_NoAlloc({
  ndcX,
  ndcY,
  camera,
  trackObj,
  raycaster,
  invWorldRef,
  normalMatRef,
  originLRef,
  dirLRef,
  localZPlane,
  outLocal,
}) {
  if (!trackObj) return false;

  raycaster.setFromCamera({ x: ndcX, y: ndcY }, camera);

  invWorldRef.copy(trackObj.matrixWorld).invert();
  originLRef.copy(raycaster.ray.origin).applyMatrix4(invWorldRef);

  normalMatRef.getNormalMatrix(invWorldRef);
  dirLRef.copy(raycaster.ray.direction).applyMatrix3(normalMatRef).normalize();

  const dz = dirLRef.z;
  if (Math.abs(dz) < 1e-6) return false;

  const t = (localZPlane - originLRef.z) / dz;
  if (t <= 0) return false;

  outLocal.copy(originLRef).addScaledVector(dirLRef, t);
  return true;
}

/* =============================================================================
   One Euro Filter
============================================================================= */
function alphaFromCutoff(cutoff, dtSec) {
  const tau = 1 / (2 * Math.PI * cutoff);
  return 1 / (1 + tau / Math.max(dtSec, 1e-4));
}
function lowpass(prev, next, a) {
  return a * next + (1 - a) * prev;
}

/* =============================================================================
   ✅ 현재 daisyUI theme(data-theme) 구독 훅
============================================================================= */
function useDaisyThemeKey() {
  const read = () =>
    document?.documentElement?.getAttribute("data-theme") || "dark";
  const [themeKey, setThemeKey] = useState(read);

  useEffect(() => {
    const el = document.documentElement;
    const obs = new MutationObserver(() => setThemeKey(read()));
    obs.observe(el, { attributes: true, attributeFilter: ["data-theme"] });

    const onStorage = (e) => {
      if (e.key === "theme") setThemeKey(read());
    };
    window.addEventListener("storage", onStorage);

    return () => {
      obs.disconnect();
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return themeKey;
}

/* =============================================================================
   RushScene
============================================================================= */
function RushScene({
  statusRef,
  onHUD,
  onJudge,
  songTimeRef,
  bpm = 120,
  beatOffsetSec = 0.65,
  seed = 1,
  playing = false,
  resetNonce = 0,
  onSliceSfx,
  allowMouseFallback = false,
  themeColors,
  inputMode = "HAND", // ✅ "HAND" | "COLOR"
}) {
  const { camera, pointer } = useThree();

  // 트랙/노트 파라미터
  const LANE_X = [-2.1, 2.1];

  const HIT_Z = 5.2;
  const HIT_TOP_Y = 0.95;
  const HIT_BOT_Y = 0.45;
  const HIT_W = Math.abs(LANE_X[1] - LANE_X[0]) + 1.2;

  const CURSOR_Z = HIT_Z + 0.25;
  const SPAWN_Z = -23;
  const NOTE_SPEED = 13.0;
  const PASS_Z = HIT_Z + 10;

  const TRAVEL_TIME = (HIT_Z - SPAWN_Z) / NOTE_SPEED;

  // 판정/슬래시 파라미터
  const HIT_Z_WINDOW = 1.6;
  const SLASH_SPEED = 1.4;

  const ATTEMPT_X_TOL = 1.25;
  const ATTEMPT_Y_PAD = 0.55;
  const ATTEMPT_Z_WIN = 2.2;

  // 풀 크기
  const NOTE_COUNT = 26;
  const SHARD_COUNT = 40;
  const SPARK_COUNT = 120;

  // refs
  const trackRef = useRef(null);
  const raycasterRef = useRef(new THREE.Raycaster());

  // 할당 줄이기용
  const tmpMat = useRef(new THREE.Matrix4());
  const tmpQuat = useRef(new THREE.Quaternion());
  const tmpPos = useRef(new THREE.Vector3());
  const tmpScale = useRef(new THREE.Vector3());

  const invWorld = useRef(new THREE.Matrix4());
  const normalMat = useRef(new THREE.Matrix3());
  const originL = useRef(new THREE.Vector3());
  const dirL = useRef(new THREE.Vector3());
  const hitLocal = useRef(new THREE.Vector3());

  const tmpAxisX = useRef(new THREE.Vector3(1, 0, 0));
  const tmpAxisY = useRef(new THREE.Vector3(0, 1, 0));

  const nextStepIdx = useRef(0);
  const lastSongTime = useRef(0);
  const lastLaneRef = useRef(0);

  const lastStatusTs = useRef(0);
  const lastSingleLaneRef = useRef(1);

  // 커서
  const cursorL = useRef({
    x: 0,
    y: 1.2,
    tx: 0,
    ty: 1.2,
    tracking: false,
    gesture: "NONE",
    vx: 0,
    vy: 0,
    _lastT: null,
    _lastTx: 0,
    _lastTy: 0,
    _lastTrackMs: 0,
    _sampleUpdated: false,
    _sampleT: 0,
    _sampleX: 0,
    _sampleY: 0,
    _euroInited: false,
    _euroLastT: 0,
    _euroLastX: 0,
    _euroLastY: 0,
    _euroX: 0,
    _euroY: 0,
    _euroDx: 0,
    _euroDy: 0,
  });

  const cursorR = useRef({
    x: 0,
    y: 1.2,
    tx: 0,
    ty: 1.2,
    tracking: false,
    gesture: "NONE",
    vx: 0,
    vy: 0,
    _lastT: null,
    _lastTx: 0,
    _lastTy: 0,
    _lastTrackMs: 0,
    _sampleUpdated: false,
    _sampleT: 0,
    _sampleX: 0,
    _sampleY: 0,
    _euroInited: false,
    _euroLastT: 0,
    _euroLastX: 0,
    _euroLastY: 0,
    _euroX: 0,
    _euroY: 0,
    _euroDx: 0,
    _euroDy: 0,
  });

  const cursorMeshL = useRef(null);
  const cursorMeshR = useRef(null);

  const prevL = useRef({ x: 0, y: 0, tMs: 0, has: false });
  const prevR = useRef({ x: 0, y: 0, tMs: 0, has: false });

  // 점수/콤보
  const comboRef = useRef(0);
  const maxComboRef = useRef(0);
  const scoreRef = useRef(0);

  // 판정 통계
  const statRef = useRef({ perfect: 0, good: 0, miss: 0, swingMiss: 0 });

  // 노트/파편/스파크 풀
  const notes = useRef(
    Array.from({ length: NOTE_COUNT }, () => ({
      alive: false,
      judged: false,
      lane: 0,
      z: SPAWN_Z,
      baseSize: 0.78,
    })),
  );
  const noteWriteIdx = useRef(0);

  const shards = useRef(
    Array.from({ length: SHARD_COUNT }, () => ({
      alive: false,
      life: 0,
      pos: new THREE.Vector3(),
      vel: new THREE.Vector3(),
      rot: new THREE.Euler(),
      rotVel: new THREE.Vector3(),
      scale: new THREE.Vector3(1, 1, 1),
      color: new THREE.Color(),
    })),
  );

  const sparks = useRef(
    Array.from({ length: SPARK_COUNT }, () => ({
      alive: false,
      life: 0,
      pos: new THREE.Vector3(),
      vel: new THREE.Vector3(),
    })),
  );
  const sparkPositions = useRef(new Float32Array(SPARK_COUNT * 3));

  const notesMesh = useRef(null);
  const glowMesh = useRef(null);
  const shardMesh = useRef(null);
  const sparksGeomRef = useRef(null);
  const sparksMatRef = useRef(null);

  const hudRef = useRef({ lastT: 0 });

  // 테마 색상
  const colLeft = useMemo(
    () => new THREE.Color(themeColors?.left || "#7dd3fc"),
    [themeColors?.left],
  );
  const colRight = useMemo(
    () => new THREE.Color(themeColors?.right || "#ff4fd8"),
    [themeColors?.right],
  );

  const matLane = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color(themeColors?.lane || "#0a0f1f"),
        roughness: 0.3,
        metalness: 0.7,
      }),
    [themeColors?.lane],
  );

  const matRail = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(themeColors?.rail || "#9be7ff"),
        transparent: true,
        opacity: 0.9,
      }),
    [themeColors?.rail],
  );

  const matNote = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.15,
        metalness: 0.9,
        emissive: new THREE.Color(themeColors?.rail || "#2bbcff"),
        emissiveIntensity: 0.25,
      }),
    [themeColors?.rail],
  );

  const matGlow = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(themeColors?.left || "#7dd3fc"),
        transparent: true,
        opacity: 0.18,
        depthWrite: false,
      }),
    [themeColors?.left],
  );

  const matShard = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.22,
        metalness: 0.85,
        emissive: new THREE.Color(themeColors?.rail || "#2bbcff"),
        emissiveIntensity: 0.2,
        transparent: true,
        opacity: 1,
      }),
    [themeColors?.rail],
  );

  const matHitCore = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(themeColors?.hitCore || "#c7f3ff"),
        transparent: true,
        opacity: 0.9,
      }),
    [themeColors?.hitCore],
  );

  const matHitGlow = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(themeColors?.left || "#7dd3fc"),
        transparent: true,
        opacity: 0.18,
        depthWrite: false,
      }),
    [themeColors?.left],
  );

  /* =========================
     resetNonce 변경 시 초기화
  ========================= */
  useEffect(() => {
    for (const n of notes.current) {
      n.alive = false;
      n.judged = false;
      n.lane = 0;
      n.z = SPAWN_Z;
    }
    for (const sh of shards.current) {
      sh.alive = false;
      sh.life = 0;
    }
    for (const sp of sparks.current) {
      sp.alive = false;
      sp.life = 0;
    }
    for (let i = 0; i < SPARK_COUNT; i++) {
      sparkPositions.current[i * 3 + 0] = 9999;
      sparkPositions.current[i * 3 + 1] = 9999;
      sparkPositions.current[i * 3 + 2] = 9999;
    }

    comboRef.current = 0;
    maxComboRef.current = 0;
    scoreRef.current = 0;

    prevL.current.has = false;
    prevR.current.has = false;

    nextStepIdx.current = 0;
    lastSongTime.current = 0;
    lastLaneRef.current = 0;

    lastStatusTs.current = 0;

    statRef.current.perfect = 0;
    statRef.current.good = 0;
    statRef.current.miss = 0;
    statRef.current.swingMiss = 0;

    const resetCursor = (c) => {
      c.current.x = 0;
      c.current.y = 1.2;
      c.current.tx = 0;
      c.current.ty = 1.2;
      c.current.tracking = false;
      c.current.gesture = "NONE";

      c.current.vx = 0;
      c.current.vy = 0;
      c.current._lastT = null;
      c.current._lastTx = 0;
      c.current._lastTy = 0;

      c.current._lastTrackMs = 0;

      c.current._sampleUpdated = false;
      c.current._sampleT = 0;
      c.current._sampleX = 0;
      c.current._sampleY = 0;

      c.current._euroInited = false;
      c.current._euroLastT = 0;
      c.current._euroLastX = 0;
      c.current._euroLastY = 0;
      c.current._euroX = 0;
      c.current._euroY = 0;
      c.current._euroDx = 0;
      c.current._euroDy = 0;
    };
    resetCursor(cursorL);
    resetCursor(cursorR);

    if (notesMesh.current && glowMesh.current) {
      for (let i = 0; i < NOTE_COUNT; i++) {
        tmpMat.current.identity();
        tmpScale.current.set(0.0001, 0.0001, 0.0001);
        tmpQuat.current.identity();
        tmpPos.current.set(0, 0, 0);
        tmpMat.current.compose(
          tmpPos.current,
          tmpQuat.current,
          tmpScale.current,
        );
        notesMesh.current.setMatrixAt(i, tmpMat.current);
        glowMesh.current.setMatrixAt(i, tmpMat.current);
      }
      notesMesh.current.instanceMatrix.needsUpdate = true;
      glowMesh.current.instanceMatrix.needsUpdate = true;
    }

    if (shardMesh.current) {
      for (let i = 0; i < SHARD_COUNT; i++) {
        tmpMat.current.identity();
        tmpScale.current.set(0.0001, 0.0001, 0.0001);
        tmpQuat.current.identity();
        tmpPos.current.set(0, 0, 0);
        tmpMat.current.compose(
          tmpPos.current,
          tmpQuat.current,
          tmpScale.current,
        );
        shardMesh.current.setMatrixAt(i, tmpMat.current);
      }
      shardMesh.current.instanceMatrix.needsUpdate = true;
    }

    if (sparksGeomRef.current) {
      sparksGeomRef.current.attributes.position.needsUpdate = true;
    }
  }, [resetNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  /* =========================
     노트 스폰
  ========================= */
  const spawnNote = (lane, lateSec = 0) => {
    const arr = notes.current;
    const idx = noteWriteIdx.current;
    noteWriteIdx.current = (idx + 1) % arr.length;

    const n = arr[idx];
    n.alive = true;
    n.judged = false;
    n.lane = lane;

    const late = clamp(lateSec, 0, TRAVEL_TIME);
    n.z = SPAWN_Z + NOTE_SPEED * late;
    n.baseSize = 0.78;
  };

  const notePose = (n) => {
    const progress = clamp((n.z - SPAWN_Z) / (HIT_Z - SPAWN_Z), 0, 1);
    const x = LANE_X[n.lane];
    const y = THREE.MathUtils.lerp(2.9, HIT_TOP_Y, progress);
    const s = n.baseSize * THREE.MathUtils.lerp(0.55, 1.25, progress);
    return { x, y, s, z: n.z };
  };

  const applyJudge = (text, lane, kind = "HIT") => {
    if (text === "PERFECT") {
      comboRef.current += 1;
      scoreRef.current += 300;
      statRef.current.perfect += 1;
    } else if (text === "GOOD") {
      comboRef.current += 1;
      scoreRef.current += 100;
      statRef.current.good += 1;
    } else if (text === "MISS") {
      comboRef.current = 0;
      if (kind === "AUTO") statRef.current.miss += 1;
      else statRef.current.swingMiss += 1;
    }

    if (comboRef.current > maxComboRef.current) {
      maxComboRef.current = comboRef.current;
    }
    onJudge?.(text, lane);
  };

  const isSlashInLaneBand = (lane, a, b) => {
    const minX = Math.min(a.x, b.x);
    const maxX = Math.max(a.x, b.x);
    const minY = Math.min(a.y, b.y);
    const maxY = Math.max(a.y, b.y);

    const okX =
      minX <= LANE_X[lane] + ATTEMPT_X_TOL &&
      maxX >= LANE_X[lane] - ATTEMPT_X_TOL;
    const okY =
      maxY >= HIT_BOT_Y - ATTEMPT_Y_PAD && minY <= HIT_TOP_Y + ATTEMPT_Y_PAD;
    return okX && okY;
  };

  const hasCuttableNoteNearHit = (lane) => {
    for (const n of notes.current) {
      if (!n.alive) continue;
      if (n.lane !== lane) continue;

      const dz = Math.abs(n.z - HIT_Z);
      if (dz > ATTEMPT_Z_WIN) continue;

      const { y } = notePose(n);
      const inY =
        y >= HIT_BOT_Y - ATTEMPT_Y_PAD && y <= HIT_TOP_Y + ATTEMPT_Y_PAD;
      if (!inY) continue;

      return true;
    }
    return false;
  };

  /* =========================
     split FX
  ========================= */
  const spawnSplitFX = (lane, hitPos, sizeS, splitAxis, cutRatio) => {
    const laneColor = lane === 0 ? colLeft : colRight;

    const r = clamp(cutRatio ?? 0.5, 0.12, 0.88);
    const aFrac = r;
    const bFrac = 1 - r;

    const sepAxis = splitAxis === "Y" ? tmpAxisY.current : tmpAxisX.current;

    const aCenterOffset = -(0.5 - aFrac / 2) * sizeS;
    const bCenterOffset = +(0.5 - bFrac / 2) * sizeS;

    const spawnShardPiece = (dir, frac, centerOffset) => {
      let pick = null;
      for (let i = 0; i < SHARD_COUNT; i++) {
        if (!shards.current[i].alive) {
          pick = shards.current[i];
          break;
        }
      }
      if (!pick) pick = shards.current[(Math.random() * SHARD_COUNT) | 0];

      pick.alive = true;
      pick.life = 0.55 + Math.random() * 0.25;

      pick.pos.copy(hitPos).addScaledVector(sepAxis, centerOffset);

      const kick = (6.0 + Math.random() * 3.2) * (1.0 + (0.35 - frac) * 0.6);
      pick.vel.copy(sepAxis).multiplyScalar(dir * kick);

      if (splitAxis === "Y") {
        pick.vel.y += (dir > 0 ? 2.2 : -1.0) + Math.random() * 1.8;
        pick.vel.x += (Math.random() - 0.5) * 2.0;
      } else {
        pick.vel.y += 2.4 + Math.random() * 3.8;
      }
      pick.vel.z += -1.6 - Math.random() * 2.6;

      pick.rot.set(0, 0, 0);
      pick.rotVel.set(
        2 + Math.random() * 2,
        (dir > 0 ? 1 : -1) * (2 + Math.random() * 3),
        (dir > 0 ? -1 : 1) * (1 + Math.random() * 2),
      );

      if (splitAxis === "Y") {
        pick.scale.set(sizeS * 1.0, sizeS * frac, sizeS * 0.35);
      } else {
        pick.scale.set(sizeS * frac, sizeS * 1.0, sizeS * 0.35);
      }

      pick.color.copy(laneColor);
    };

    spawnShardPiece(-1, aFrac, aCenterOffset);
    spawnShardPiece(+1, bFrac, bCenterOffset);

    for (let i = 0; i < 18; i++) {
      let sp = null;
      for (let k = 0; k < SPARK_COUNT; k++) {
        if (!sparks.current[k].alive) {
          sp = sparks.current[k];
          break;
        }
      }
      if (!sp) sp = sparks.current[(Math.random() * SPARK_COUNT) | 0];

      const ang = Math.random() * Math.PI * 2;
      const spd = 6 + Math.random() * 11;

      sp.alive = true;
      sp.life = 0.45 + Math.random() * 0.35;
      sp.pos.copy(hitPos);
      sp.vel.set(
        Math.cos(ang) * spd,
        3 + Math.random() * 6,
        -2 - Math.random() * 4,
      );
    }
  };

  /* =========================
     히트 판정
  ========================= */
  const tryHitLane = (lane, segA, segB) => {
    let best = null;
    let bestDist = 1e9;
    let bestCutRatio = 0.5;
    let bestSplitAxis = "X";

    for (const n of notes.current) {
      if (!n.alive) continue;
      if (n.lane !== lane) continue;

      const dz = Math.abs(n.z - HIT_Z);
      if (dz > HIT_Z_WINDOW) continue;

      const { x, y, s } = notePose(n);
      const halfW = s * 0.55;
      const halfH = s * 0.55;
      const pad = s * 0.18;

      const info = segRectIntersectInfo(
        segA,
        segB,
        x - halfW - pad,
        x + halfW + pad,
        y - halfH - pad,
        y + halfH + pad,
      );
      if (!info) continue;

      const slashDx = segB.x - segA.x;
      const slashDy = segB.y - segA.y;
      const splitAxis = Math.abs(slashDx) >= Math.abs(slashDy) ? "Y" : "X";

      const rawRatio =
        splitAxis === "Y"
          ? (info.iy - (y - halfH)) / (2 * halfH)
          : (info.ix - (x - halfW)) / (2 * halfW);

      const cutRatio = clamp(rawRatio, 0.05, 0.95);

      if (dz < bestDist) {
        bestDist = dz;
        best = n;
        bestCutRatio = cutRatio;
        bestSplitAxis = splitAxis;
      }
    }

    if (!best) return;

    const PERFECT = 0.7;
    const GOOD = 1.6;
    const text =
      bestDist <= PERFECT ? "PERFECT" : bestDist <= GOOD ? "GOOD" : "MISS";

    if (text !== "MISS") {
      const { x, y, s, z } = notePose(best);
      hitLocal.current.set(x, y, z);
      spawnSplitFX(lane, hitLocal.current, s, bestSplitAxis, bestCutRatio);
      onSliceSfx?.();
      best.judged = true;
      best.alive = false;
    }

    applyJudge(text, lane, text === "MISS" ? "SWING" : "HIT");
  };

  const stepSlashBySamples = (curRef, prevRef, lane) => {
    if (!curRef.current.tracking) {
      prevRef.current.has = false;
      return false;
    }
    if (!curRef.current._sampleUpdated) return false;

    const cx = curRef.current._sampleX;
    const cy = curRef.current._sampleY;
    const tMs = curRef.current._sampleT;

    if (!prevRef.current.has) {
      prevRef.current.x = cx;
      prevRef.current.y = cy;
      prevRef.current.tMs = tMs;
      prevRef.current.has = true;
      return false;
    }

    const ax = prevRef.current.x;
    const ay = prevRef.current.y;
    const dtMs = Math.max(1, tMs - (prevRef.current.tMs || tMs));
    const dtSec = dtMs / 1000;

    const dx = cx - ax;
    const dy = cy - ay;
    const speed = Math.sqrt(dx * dx + dy * dy) / Math.max(dtSec, 1e-4);

    let didSlash = false;

    if (speed >= SLASH_SPEED) {
      const segA = { x: ax, y: ay };
      const segB = { x: cx, y: cy };

      const attempt =
        hasCuttableNoteNearHit(lane) && isSlashInLaneBand(lane, segA, segB);
      if (attempt) {
        didSlash = true;
        tryHitLane(lane, segA, segB);
      }
    }

    prevRef.current.x = cx;
    prevRef.current.y = cy;
    prevRef.current.tMs = tMs;
    return didSlash;
  };

  const applyOneEuro = (curRef, tNowMs, rawX, rawY) => {
    const minCutoff = 1.15;
    const beta = 0.03;
    const dCutoff = 1.0;

    if (!curRef.current._euroInited) {
      curRef.current._euroInited = true;
      curRef.current._euroLastT = tNowMs;
      curRef.current._euroLastX = rawX;
      curRef.current._euroLastY = rawY;
      curRef.current._euroX = rawX;
      curRef.current._euroY = rawY;
      curRef.current._euroDx = 0;
      curRef.current._euroDy = 0;
      return { fx: rawX, fy: rawY };
    }

    const dtSec = clamp(
      (tNowMs - curRef.current._euroLastT) / 1000,
      0.001,
      0.2,
    );

    const dx = (rawX - curRef.current._euroLastX) / dtSec;
    const dy = (rawY - curRef.current._euroLastY) / dtSec;

    const aD = alphaFromCutoff(dCutoff, dtSec);
    curRef.current._euroDx = lowpass(curRef.current._euroDx, dx, aD);
    curRef.current._euroDy = lowpass(curRef.current._euroDy, dy, aD);

    const cutoffX = minCutoff + beta * Math.abs(curRef.current._euroDx);
    const cutoffY = minCutoff + beta * Math.abs(curRef.current._euroDy);

    const aX = alphaFromCutoff(cutoffX, dtSec);
    const aY = alphaFromCutoff(cutoffY, dtSec);

    curRef.current._euroX = lowpass(curRef.current._euroX, rawX, aX);
    curRef.current._euroY = lowpass(curRef.current._euroY, rawY, aY);

    curRef.current._euroLastT = tNowMs;
    curRef.current._euroLastX = rawX;
    curRef.current._euroLastY = rawY;

    return { fx: curRef.current._euroX, fy: curRef.current._euroY };
  };

  /* =============================================================================
     useFrame
============================================================================= */
  useFrame((state, dt) => {
    const st = statusRef.current;
    const hand = readTwoHandsFromStatus(st);

    const stTs = st?.__ts ?? 0;
    const isNewSample = !!stTs && stTs !== lastStatusTs.current;
    if (isNewSample) lastStatusTs.current = stTs;

    const mouseNdcX = pointer.x;
    const mouseNdcY = pointer.y;

    let leftNdc = null;
    let rightNdc = null;

    const toNdc = (h) => ({
      x: h.nx * 2 - 1,
      y: (1 - h.ny) * 2 - 1,
      tracking: h.tracking,
      gesture: h.gesture ?? "NONE",
    });

    if (hand) {
      const cands = [];
      if (hand.left) cands.push(toNdc(hand.left));
      if (hand.right) cands.push(toNdc(hand.right));
      if (cands.length === 0 && hand.single) cands.push(toNdc(hand.single));

      // ✅ 입력모드에 따라 좌/우 매핑 전략 변경
      const normG = (g) => String(g || "").toUpperCase();

      if (inputMode === "COLOR") {
        // COLOR: BLUE/RED 우선 매핑
        const blueIdx = cands.findIndex((c) => normG(c.gesture) === "BLUE");
        const redIdx = cands.findIndex((c) => normG(c.gesture) === "RED");
        const blue = blueIdx >= 0 ? cands[blueIdx] : null;
        const red = redIdx >= 0 ? cands[redIdx] : null;

        if (blue) leftNdc = blue;
        if (red) rightNdc = red;

        if (leftNdc && !rightNdc && cands.length >= 2) {
          const other = cands.find((c, i) => i !== blueIdx);
          if (other) rightNdc = other;
        }
        if (rightNdc && !leftNdc && cands.length >= 2) {
          const other = cands.find((c, i) => i !== redIdx);
          if (other) leftNdc = other;
        }
      }

      // HAND(또는 COLOR에서 실패) fallback: x로 좌/우 정렬
      if (!leftNdc && !rightNdc) {
        if (cands.length >= 2) {
          cands.sort((a, b) => a.x - b.x);
          leftNdc = cands[0];
          rightNdc = cands[1];
          lastSingleLaneRef.current = 1;
        } else if (cands.length === 1) {
          const s = cands[0];
          const HYS = 0.18;
          if (s.x < -HYS) lastSingleLaneRef.current = 0;
          else if (s.x > HYS) lastSingleLaneRef.current = 1;

          if (lastSingleLaneRef.current === 0) leftNdc = s;
          else rightNdc = s;
        }
      }

      if (leftNdc && !rightNdc) lastSingleLaneRef.current = 0;
      if (rightNdc && !leftNdc) lastSingleLaneRef.current = 1;
    }

    const usingMouseFallback = allowMouseFallback && !leftNdc && !rightNdc;
    if (usingMouseFallback) {
      leftNdc = {
        x: mouseNdcX,
        y: mouseNdcY,
        tracking: true,
        gesture: "MOUSE",
      };
      rightNdc = {
        x: mouseNdcX,
        y: mouseNdcY,
        tracking: true,
        gesture: "MOUSE",
      };
    }

    const trackObj = trackRef.current;
    const raycaster = raycasterRef.current;

    const updateCursorFromNdc = (ndc, curRef, shouldUpdateTarget, tNowMs) => {
      const nowMs = performance.now();
      const grace = 120;

      curRef.current._sampleUpdated = false;

      if (!ndc) {
        const tracking =
          !!curRef.current._lastTrackMs &&
          nowMs - curRef.current._lastTrackMs < grace;
        curRef.current.tracking = tracking;
        curRef.current.gesture = "NONE";
        return false;
      }

      if (ndc.tracking) curRef.current._lastTrackMs = nowMs;

      const tracking =
        !!ndc.tracking ||
        (!!curRef.current._lastTrackMs &&
          nowMs - curRef.current._lastTrackMs < grace);

      curRef.current.tracking = tracking;
      curRef.current.gesture = ndc.gesture ?? "NONE";

      if (!trackObj) return false;
      if (!shouldUpdateTarget) return false;

      const ok = ndcToTrackLocalOnZPlane_NoAlloc({
        ndcX: ndc.x,
        ndcY: ndc.y,
        camera,
        trackObj,
        raycaster,
        invWorldRef: invWorld.current,
        normalMatRef: normalMat.current,
        originLRef: originL.current,
        dirLRef: dirL.current,
        localZPlane: CURSOR_Z,
        outLocal: hitLocal.current,
      });
      if (!ok) return false;

      const rawX = hitLocal.current.x;
      const rawY = hitLocal.current.y;

      const { fx, fy } = applyOneEuro(curRef, tNowMs, rawX, rawY);

      if (curRef.current._lastT != null) {
        const dms = Math.max(1, tNowMs - curRef.current._lastT);
        const ivx = (fx - curRef.current._lastTx) / dms;
        const ivy = (fy - curRef.current._lastTy) / dms;
        curRef.current.vx = curRef.current.vx * 0.75 + ivx * 0.25;
        curRef.current.vy = curRef.current.vy * 0.75 + ivy * 0.25;
      }
      curRef.current._lastT = tNowMs;
      curRef.current._lastTx = fx;
      curRef.current._lastTy = fy;

      curRef.current.tx = fx;
      curRef.current.ty = fy;

      curRef.current._sampleUpdated = true;
      curRef.current._sampleT = tNowMs;
      curRef.current._sampleX = rawX;
      curRef.current._sampleY = rawY;

      return true;
    };

    const tNowHands = stTs || performance.now();
    const tNowMouse = performance.now();

    updateCursorFromNdc(
      leftNdc,
      cursorL,
      usingMouseFallback ? true : isNewSample,
      usingMouseFallback ? tNowMouse : tNowHands,
    );
    updateCursorFromNdc(
      rightNdc,
      cursorR,
      usingMouseFallback ? true : isNewSample,
      usingMouseFallback ? tNowMouse : tNowHands,
    );

    {
      const predMs = 70;

      const smooth = (curRef) => {
        if (!curRef.current.tracking) {
          const damp = Math.exp(-dt * 14);
          curRef.current.vx *= damp;
          curRef.current.vy *= damp;
        }

        const ptx = curRef.current.tx + curRef.current.vx * predMs;
        const pty = curRef.current.ty + curRef.current.vy * predMs;

        const err = Math.hypot(ptx - curRef.current.x, pty - curRef.current.y);

        const base = 28 + err * 0.08;
        const lambda = clamp(
          curRef.current.tracking ? base : base * 0.65,
          18,
          120,
        );
        const k = 1 - Math.exp(-dt * lambda);

        if (err > 2.2) {
          if (curRef.current.tracking) {
            curRef.current.x = ptx;
            curRef.current.y = pty;
          } else {
            curRef.current.x += (ptx - curRef.current.x) * k;
            curRef.current.y += (pty - curRef.current.y) * k;
          }
        } else {
          curRef.current.x += (ptx - curRef.current.x) * k;
          curRef.current.y += (pty - curRef.current.y) * k;
        }
      };

      smooth(cursorL);
      smooth(cursorR);
    }

    const songTime = songTimeRef?.current ?? 0;

    if (songTime < lastSongTime.current - 0.05) {
      nextStepIdx.current = 0;
      lastLaneRef.current = 0;
    }
    lastSongTime.current = songTime;

    // 노트 스폰
    if (playing && bpm > 0) {
      const beatSec = 60 / bpm;
      const stepSec = beatSec * 0.5;

      while (true) {
        const stepIdx = nextStepIdx.current;
        const stepTime = beatOffsetSec + stepIdx * stepSec;
        const spawnTime = stepTime - TRAVEL_TIME;

        if (songTime < spawnTime) break;

        const late = songTime - spawnTime;
        const onBeat = stepIdx % 2 === 0;

        const r = hash01((seed * 1000000 + stepIdx) | 0);
        const spawnThisStep = onBeat ? true : r < 0.35;

        if (spawnThisStep) {
          let lane = lastLaneRef.current ^ 1;
          if (r < (onBeat ? 0.2 : 0.12)) lane = lastLaneRef.current;

          spawnNote(lane, late);
          lastLaneRef.current = lane;

          if (onBeat) {
            const beatIdx = (stepIdx / 2) | 0;
            const r2 = hash01((seed * 777777 + beatIdx) | 0);
            if (beatIdx % 16 === 0 && r2 < 0.55) {
              spawnNote(lane ^ 1, late);
            }
          }
        }

        nextStepIdx.current++;
      }
    }

    // 노트 이동/렌더
    if (notesMesh.current && glowMesh.current) {
      for (let i = 0; i < NOTE_COUNT; i++) {
        const n = notes.current[i];

        if (playing && n.alive) {
          n.z += NOTE_SPEED * dt;

          if (!n.judged && n.z > HIT_Z + HIT_Z_WINDOW) {
            n.judged = true;
            n.alive = false;
            applyJudge("MISS", n.lane, "AUTO");
          }

          if (n.z > PASS_Z) n.alive = false;
        }

        if (!n.alive) {
          tmpMat.current.identity();
          tmpQuat.current.identity();
          tmpPos.current.set(0, 0, 0);
          tmpScale.current.set(0.0001, 0.0001, 0.0001);
          tmpMat.current.compose(
            tmpPos.current,
            tmpQuat.current,
            tmpScale.current,
          );
          notesMesh.current.setMatrixAt(i, tmpMat.current);
          glowMesh.current.setMatrixAt(i, tmpMat.current);
          continue;
        }

        const progress = clamp((n.z - SPAWN_Z) / (HIT_Z - SPAWN_Z), 0, 1);
        const x = LANE_X[n.lane];
        const y = THREE.MathUtils.lerp(2.9, HIT_TOP_Y, progress);
        const z = n.z;
        const s = n.baseSize * THREE.MathUtils.lerp(0.55, 1.25, progress);

        tmpQuat.current.identity();
        tmpPos.current.set(x, y, z);
        tmpScale.current.set(s, s, s * 0.35);
        tmpMat.current.compose(
          tmpPos.current,
          tmpQuat.current,
          tmpScale.current,
        );
        notesMesh.current.setMatrixAt(i, tmpMat.current);

        tmpPos.current.set(x, y, z - 0.08);
        tmpScale.current.set(s * 1.25, s * 1.25, s * 0.25);
        tmpMat.current.compose(
          tmpPos.current,
          tmpQuat.current,
          tmpScale.current,
        );
        glowMesh.current.setMatrixAt(i, tmpMat.current);

        notesMesh.current.setColorAt(i, n.lane === 0 ? colLeft : colRight);
      }

      notesMesh.current.instanceMatrix.needsUpdate = true;
      glowMesh.current.instanceMatrix.needsUpdate = true;
      if (notesMesh.current.instanceColor)
        notesMesh.current.instanceColor.needsUpdate = true;
    }

    // 슬래시 판정
    let firedL = false;
    let firedR = false;
    if (playing) {
      firedL = stepSlashBySamples(cursorL, prevL, 0);
      firedR = stepSlashBySamples(cursorR, prevR, 1);
    }

    // 커서 렌더
    if (cursorMeshL.current) {
      cursorMeshL.current.visible = cursorL.current.tracking;
      cursorMeshL.current.position.set(
        cursorL.current.x,
        cursorL.current.y,
        CURSOR_Z,
      );
    }
    if (cursorMeshR.current) {
      cursorMeshR.current.visible = cursorR.current.tracking;
      cursorMeshR.current.position.set(
        cursorR.current.x,
        cursorR.current.y,
        CURSOR_Z,
      );
    }

    // 파편
    if (shardMesh.current) {
      const g = -13.0;

      for (let i = 0; i < SHARD_COUNT; i++) {
        const sh = shards.current[i];

        if (!sh.alive) {
          tmpMat.current.identity();
          tmpQuat.current.identity();
          tmpPos.current.set(0, 0, 0);
          tmpScale.current.set(0.0001, 0.0001, 0.0001);
          tmpMat.current.compose(
            tmpPos.current,
            tmpQuat.current,
            tmpScale.current,
          );
          shardMesh.current.setMatrixAt(i, tmpMat.current);
          continue;
        }

        sh.life -= dt;
        if (sh.life <= 0) {
          sh.alive = false;
          tmpMat.current.identity();
          tmpQuat.current.identity();
          tmpPos.current.set(0, 0, 0);
          tmpScale.current.set(0.0001, 0.0001, 0.0001);
          tmpMat.current.compose(
            tmpPos.current,
            tmpQuat.current,
            tmpScale.current,
          );
          shardMesh.current.setMatrixAt(i, tmpMat.current);
          continue;
        }

        sh.vel.y += g * dt;
        sh.pos.addScaledVector(sh.vel, dt);

        sh.rot.x += sh.rotVel.x * dt;
        sh.rot.y += sh.rotVel.y * dt;
        sh.rot.z += sh.rotVel.z * dt;

        tmpQuat.current.setFromEuler(sh.rot);
        tmpMat.current.compose(sh.pos, tmpQuat.current, sh.scale);

        shardMesh.current.setMatrixAt(i, tmpMat.current);
        shardMesh.current.setColorAt(i, sh.color);
      }

      shardMesh.current.instanceMatrix.needsUpdate = true;
      if (shardMesh.current.instanceColor)
        shardMesh.current.instanceColor.needsUpdate = true;
    }

    // 스파크
    {
      const g = -12.0;

      for (let i = 0; i < SPARK_COUNT; i++) {
        const sp = sparks.current[i];

        if (!sp.alive) {
          sparkPositions.current[i * 3 + 0] = 9999;
          sparkPositions.current[i * 3 + 1] = 9999;
          sparkPositions.current[i * 3 + 2] = 9999;
          continue;
        }

        sp.life -= dt;
        if (sp.life <= 0) {
          sp.alive = false;
          sparkPositions.current[i * 3 + 0] = 9999;
          sparkPositions.current[i * 3 + 1] = 9999;
          sparkPositions.current[i * 3 + 2] = 9999;
          continue;
        }

        sp.vel.y += g * 0.7 * dt;
        sp.pos.addScaledVector(sp.vel, dt);

        sparkPositions.current[i * 3 + 0] = sp.pos.x;
        sparkPositions.current[i * 3 + 1] = sp.pos.y;
        sparkPositions.current[i * 3 + 2] = sp.pos.z;
      }

      if (sparksGeomRef.current)
        sparksGeomRef.current.attributes.position.needsUpdate = true;
      if (sparksMatRef.current) sparksMatRef.current.opacity = 0.9;
    }

    // HUD 업데이트
    const now = performance.now();
    if (now - hudRef.current.lastT > 100) {
      hudRef.current.lastT = now;
      onHUD?.({
        trackingL: cursorL.current.tracking,
        trackingR: cursorR.current.tracking,
        firedL,
        firedR,
        bpm,
        combo: comboRef.current,
        maxCombo: maxComboRef.current,
        score: scoreRef.current,
        songTime,
        beatOffsetSec,
        gestureL: cursorL.current.gesture,
        gestureR: cursorR.current.gesture,
        perfect: statRef.current.perfect,
        good: statRef.current.good,
        miss: statRef.current.miss,
        swingMiss: statRef.current.swingMiss,
      });
    }
  });

  return (
    <>
      <color attach="background" args={[themeColors?.bg0 || "#060a14"]} />
      <fog
        attach="fog"
        args={[themeColors?.fog || themeColors?.bg1 || "#070a14", 10, 44]}
      />

      <ambientLight intensity={0.55} />
      <directionalLight position={[6, 8, 6]} intensity={0.85} />
      <pointLight
        position={[-6, 3, 2]}
        intensity={1.0}
        color={themeColors?.left || "#7dd3fc"}
      />
      <pointLight
        position={[6, 3, -10]}
        intensity={0.9}
        color={themeColors?.right || "#ff4fd8"}
      />

      <group ref={trackRef} position={[0, 0.8, 0]}>
        <mesh
          rotation={[-Math.PI / 2, 0, 0]}
          position={[0, 0, -14]}
          material={matLane}
        >
          <planeGeometry args={[18, 46]} />
        </mesh>

        <mesh
          rotation={[-Math.PI / 2, 0, 0]}
          position={[-2.1, 0.01, -14]}
          material={matRail}
        >
          <planeGeometry args={[0.03, 46]} />
        </mesh>
        <mesh
          rotation={[-Math.PI / 2, 0, 0]}
          position={[2.1, 0.01, -14]}
          material={matRail}
        >
          <planeGeometry args={[0.03, 46]} />
        </mesh>

        <mesh position={[0, HIT_TOP_Y, HIT_Z]} material={matHitGlow}>
          <boxGeometry args={[HIT_W * 1.06, 0.08, 0.08]} />
        </mesh>
        <mesh position={[0, HIT_TOP_Y, HIT_Z]} material={matHitCore}>
          <boxGeometry args={[HIT_W, 0.022, 0.022]} />
        </mesh>

        <mesh position={[0, HIT_BOT_Y, HIT_Z]} material={matHitGlow}>
          <boxGeometry args={[HIT_W * 1.06, 0.08, 0.08]} />
        </mesh>
        <mesh position={[0, HIT_BOT_Y, HIT_Z]} material={matHitCore}>
          <boxGeometry args={[HIT_W, 0.022, 0.022]} />
        </mesh>

        <instancedMesh
          ref={glowMesh}
          args={[null, null, NOTE_COUNT]}
          material={matGlow}
        >
          <boxGeometry args={[1, 1, 1]} />
        </instancedMesh>

        <instancedMesh
          ref={notesMesh}
          args={[null, null, NOTE_COUNT]}
          material={matNote}
        >
          <boxGeometry args={[1, 1, 1]} />
        </instancedMesh>

        <instancedMesh
          ref={shardMesh}
          args={[null, null, SHARD_COUNT]}
          material={matShard}
        >
          <boxGeometry args={[1, 1, 1]} />
        </instancedMesh>

        <points>
          <bufferGeometry ref={sparksGeomRef}>
            <bufferAttribute
              attach="attributes-position"
              array={sparkPositions.current}
              itemSize={3}
              count={SPARK_COUNT}
            />
          </bufferGeometry>
          <pointsMaterial
            ref={sparksMatRef}
            size={0.08}
            color={themeColors?.white || "#ffffff"}
            transparent
            opacity={0.9}
            depthWrite={false}
          />
        </points>

        {/* 커서 RIGHT */}
        <group ref={cursorMeshR} rotation={[0, 0, -0.6]} renderOrder={999}>
          <pointLight
            color={themeColors?.right || "#ff4fd8"}
            intensity={1.6}
            distance={7}
            decay={2}
          />
          <mesh renderOrder={999}>
            <boxGeometry args={[0.1, 0.85, 0.05]} />
            <meshBasicMaterial
              color={themeColors?.right || "#ff4fd8"}
              transparent
              opacity={0.18}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh position={[0, 0.06, 0]} renderOrder={999}>
            <boxGeometry args={[0.05, 0.72, 0.02]} />
            <meshStandardMaterial
              color={themeColors?.hitCore || "#c7f3ff"}
              metalness={0.85}
              roughness={0.18}
              emissive={themeColors?.right || "#ff4fd8"}
              emissiveIntensity={0.35}
              transparent
              opacity={0.98}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh position={[0, -0.34, 0]} renderOrder={999}>
            <cylinderGeometry args={[0.035, 0.035, 0.18, 12]} />
            <meshStandardMaterial
              color={themeColors?.bg1 || "#1a1f2e"}
              metalness={0.2}
              roughness={0.85}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
        </group>

        {/* 커서 LEFT */}
        <group ref={cursorMeshL} rotation={[0, 0, 0.6]} renderOrder={999}>
          <pointLight
            color={themeColors?.left || "#7dd3fc"}
            intensity={1.6}
            distance={7}
            decay={2}
          />
          <mesh renderOrder={999}>
            <boxGeometry args={[0.1, 0.85, 0.05]} />
            <meshBasicMaterial
              color={themeColors?.left || "#7dd3fc"}
              transparent
              opacity={0.18}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh position={[0, 0.06, 0]} renderOrder={999}>
            <boxGeometry args={[0.05, 0.72, 0.02]} />
            <meshStandardMaterial
              color={themeColors?.hitCore || "#c7f3ff"}
              metalness={0.85}
              roughness={0.18}
              emissive={themeColors?.left || "#7dd3fc"}
              emissiveIntensity={0.35}
              transparent
              opacity={0.98}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh position={[0, -0.34, 0]} renderOrder={999}>
            <cylinderGeometry args={[0.035, 0.035, 0.18, 12]} />
            <meshStandardMaterial
              color={themeColors?.bg1 || "#1a1f2e"}
              metalness={0.2}
              roughness={0.85}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
        </group>
      </group>
    </>
  );
}

/* =============================================================================
   Rush3DPage (export default)
============================================================================= */
export default function Rush3DPage({ status, connected = true }) {
  // ✅ 현재 theme 읽기
  const themeKey = useDaisyThemeKey();
  const themeColors = THEME?.[themeKey]?.colors || THEME.dark.colors;

  const statusRef = useRef(null);

  // 외부 status 주입(있으면)
  useEffect(() => {
    if (status != null) {
      const j = { ...status, __ts: performance.now() };
      statusRef.current = j;
    }
  }, [status]);

  // 자체 폴링
  useEffect(() => {
    let alive = true;
    let timer = null;
    let ctrl = null;

    const loop = async () => {
      if (!alive) return;

      if (ctrl) ctrl.abort();
      ctrl = new AbortController();

      try {
        const r = await fetch(apiUrl("/api/control/status"), { signal: controller.signal });
        const j = await r.json();
        j.__ts = performance.now();
        if (alive) statusRef.current = j;
      } catch {
        // ignore
      } finally {
        if (alive) timer = setTimeout(loop, 33);
      }
    };

    loop();
    return () => {
      alive = false;
      if (ctrl) ctrl.abort();
      if (timer) clearTimeout(timer);
    };
  }, []);

  const SONGS = useMemo(
    () => [
      {
        id: "da",
        title: "다 멍청해",
        src: encodeURI("/audio/다 멍청해.mp3"),
        bpm: 120,
        offsetSec: 0.65,
        seed: 11,
      },
      {
        id: "lemon",
        title: "Lemon Tree",
        src: encodeURI("/audio/lemon_tree.mp3"),
        bpm: 128,
        offsetSec: 0.8,
        seed: 22,
      },
      {
        id: "rush",
        title: "Rush F",
        src: encodeURI("/audio/rush_e.mp3"),
        bpm: 112,
        offsetSec: 0.7,
        seed: 33,
      },
    ],
    [],
  );

  const [selectedId, setSelectedId] = useState(SONGS[0].id);
  const selectedSong = SONGS.find((s) => s.id === selectedId) || SONGS[0];

  const [offsets, setOffsets] = useState(() => {
    const obj = {};
    for (const s of SONGS) obj[s.id] = s.offsetSec;
    return obj;
  });

  const selectedOffsetSec = offsets[selectedId] ?? selectedSong.offsetSec;

  // ✅ RUSH 입력 모드 선택
  // HAND  : 손(좌/우를 x정렬로)
  // COLOR : 제스처 BLUE/RED 우선
  const [rushInput, setRushInput] = useState("HAND"); // "HAND" | "COLOR"
  const desiredLabel = rushInput === "COLOR" ? "RUSH_COLOR" : "RUSH_HAND";

  const audioRef = useRef(null);
  const songTimeRef = useRef(0);

  const [phase, setPhase] = useState("LOBBY");
  const [playing, setPlaying] = useState(false);
  const [resetNonce, setResetNonce] = useState(0);

  const [hud, setHud] = useState({
    trackingL: false,
    trackingR: false,
    firedL: false,
    firedR: false,
    bpm: selectedSong.bpm,
    combo: 0,
    maxCombo: 0,
    score: 0,
    songTime: 0,
    beatOffsetSec: selectedOffsetSec,
    gestureL: "NONE",
    gestureR: "NONE",
    perfect: 0,
    good: 0,
    miss: 0,
    swingMiss: 0,
  });

  const [judge, setJudge] = useState(null);
  const [result, setResult] = useState(null);

  // ✅ Apply/Start용 busy 표시
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyErr, setApplyErr] = useState("");

  // Slice SFX
  const sfxRef = useRef({ ctx: null, buf: null, ready: false });

  const ensureSfxReady = async () => {
    if (sfxRef.current.ready) return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;

    if (!sfxRef.current.ctx) sfxRef.current.ctx = new AudioCtx();
    if (sfxRef.current.ctx.state !== "running")
      await sfxRef.current.ctx.resume();

    const res = await fetch("/sfx/slice.wav", { cache: "force-cache" });
    const arr = await res.arrayBuffer();
    const buf = await sfxRef.current.ctx.decodeAudioData(arr);
    sfxRef.current.buf = buf;
    sfxRef.current.ready = true;
  };

  const playSliceSfx = () => {
    const ctx = sfxRef.current.ctx;
    const buf = sfxRef.current.buf;
    if (!ctx || !buf) return;

    const src = ctx.createBufferSource();
    src.buffer = buf;
    const gain = ctx.createGain();
    gain.gain.value = 0.65;
    src.connect(gain).connect(ctx.destination);
    src.start(0);
  };

  // 곡 바뀌면 리셋
  useEffect(() => {
    setPhase("LOBBY");
    setPlaying(false);
    setResult(null);
    setResetNonce((n) => n + 1);

    const audio = audioRef.current;
    if (!audio) return;

    audio.pause();
    audio.currentTime = 0;
    audio.src = selectedSong.src;
  }, [selectedId, selectedSong.src]);

  // songTime loop
  useEffect(() => {
    let raf = 0;

    const loop = () => {
      const a = audioRef.current;
      const t = a ? a.currentTime || 0 : 0;
      songTimeRef.current = t;

      if (a && phase === "PLAYING") {
        const ended = a.duration && a.currentTime >= a.duration - 0.02;
        if (ended) {
          a.pause();
          setPlaying(false);
          setPhase("RESULT");

          setResult({
            songId: selectedId,
            title: selectedSong.title,
            bpm: selectedSong.bpm,
            offsetSec: selectedOffsetSec,
            score: hud.score,
            maxCombo: hud.maxCombo,
            perfect: hud.perfect,
            good: hud.good,
            miss: hud.miss,
            swingMiss: hud.swingMiss,
          });
        }
      }

      raf = requestAnimationFrame(loop);
    };

    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [
    phase,
    selectedId,
    selectedSong.title,
    selectedSong.bpm,
    selectedOffsetSec,
    hud,
  ]);

  // ✅ 서버에 RUSH 모드/START 적용(핵심)
  const applyRushModeNow = useCallback(async () => {
    setApplyBusy(true);
    setApplyErr("");
    try {
      const modeParam = rushInput === "COLOR" ? "RUSH_COLOR" : "RUSH_HAND";

      const r1 = await fetch(
        `/api/control/mode?mode=${encodeURIComponent(modeParam)}`,
        {
          method: "POST",
        },
      );
      if (!r1.ok) {
        const txt = await r1.text().catch(() => "");
        throw new Error(`mode failed (${r1.status}) ${txt}`);
      }

      const r2 = await fetch(apiUrl("/api/control/start"), { method: "POST" });
      if (!r2.ok) {
        const txt = await r2.text().catch(() => "");
        throw new Error(`start failed (${r2.status}) ${txt}`);
      }
    } catch (e) {
      setApplyErr(String(e?.message || e || "apply failed"));
    } finally {
      setApplyBusy(false);
    }
  }, [rushInput]);

  const startGame = async () => {
    const a = audioRef.current;
    if (!a) return;

    // ✅ Start Game 누르면 먼저 RUSH + START 적용
    await applyRushModeNow();

    try {
      await ensureSfxReady();
    } catch {}

    setResult(null);
    setResetNonce((n) => n + 1);

    a.currentTime = 0;
    try {
      await a.play();
      setPhase("PLAYING");
      setPlaying(true);
    } catch {
      setPlaying(false);
      setPhase("LOBBY");
    }
  };

  const pause = () => {
    const a = audioRef.current;
    if (a) a.pause();
    setPlaying(false);
  };

  const resume = async () => {
    const a = audioRef.current;
    if (!a) return;
    try {
      await a.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
  };

  const reset = () => {
    const a = audioRef.current;
    if (a) {
      a.pause();
      a.currentTime = 0;
    }
    setPlaying(false);
    setResetNonce((n) => n + 1);
  };

  const retry = async () => {
    reset();
    await startGame();
  };

  const backToLobby = () => {
    reset();
    setResult(null);
    setPhase("LOBBY");
  };

  const setNowAsFirstBeat = () => {
    const a = audioRef.current;
    if (!a) return;
    const t = a.currentTime || 0;
    setOffsets((prev) => ({ ...prev, [selectedId]: t }));
    setResetNonce((n) => n + 1);
  };

  const resPerfect = result?.perfect ?? hud.perfect ?? 0;
  const resGood = result?.good ?? hud.good ?? 0;
  const resMiss = result?.miss ?? hud.miss ?? 0;

  const totalNotes = resPerfect + resGood + resMiss;
  const acc = totalNotes > 0 ? (resPerfect + resGood) / totalNotes : 0;

  const rank =
    acc >= 0.95
      ? "S"
      : acc >= 0.9
        ? "A"
        : acc >= 0.8
          ? "B"
          : acc >= 0.65
            ? "C"
            : "D";

  const modeU = String(statusRef.current?.mode || "").toUpperCase();
  const rushOk =
    connected &&
    ["RUSH", "RUSH_HAND", "RUSH_COLOR"].includes(modeU) &&
    !!statusRef.current?.enabled;

  const judgeColor =
    judge?.lane === 0
      ? "text-info"
      : judge?.lane === 1
        ? "text-secondary"
        : "text-base-content";

  return (
    <div
      className="w-full bg-base-100 text-base-content relative overflow-hidden"
      style={{ height: "100dvh" }}
    >
      <audio ref={audioRef} preload="metadata" />

      <Canvas
        dpr={1}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        camera={{ position: [0, 3.6, 9.8], fov: 60 }}
        onCreated={({ gl }) => {
          gl.toneMapping = THREE.ACESFilmicToneMapping;
          gl.toneMappingExposure = 1.15;
        }}
      >
        <group rotation={[THREE.MathUtils.degToRad(-6), 0, 0]}>
          <RushScene
            statusRef={statusRef}
            songTimeRef={songTimeRef}
            bpm={selectedSong.bpm}
            beatOffsetSec={selectedOffsetSec}
            seed={selectedSong.seed}
            playing={phase === "PLAYING" && playing}
            resetNonce={resetNonce}
            onSliceSfx={playSliceSfx}
            onHUD={(h) => setHud(h)}
            onJudge={(text, lane) => {
              setJudge({ text, lane, ts: performance.now() });
              setTimeout(() => setJudge(null), 420);
            }}
            allowMouseFallback={false}
            themeColors={themeColors}
            inputMode={rushInput} // ✅ HAND/COLOR 반영
          />
        </group>
      </Canvas>

      {/* LOBBY UI */}
      {phase === "LOBBY" && (
        <div className="absolute inset-0 z-20 pointer-events-auto">
          <div className="absolute inset-0 bg-gradient-to-b from-base-100/75 via-base-100/45 to-base-100/75" />

          {/* ✅ 아래 잘림 방지: items-center → items-start + pt */}
          <div className="relative h-full flex items-start justify-center px-6 pt-8 pb-6">
            <div className="w-[min(980px,94vw)] bg-base-200/55 border border-base-300/40 rounded-3xl p-6 backdrop-blur">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-xs tracking-[0.35em] text-base-content/70">
                    RHYTHM RUSH
                  </div>
                  <div className="text-2xl font-black mt-1">Lobby</div>
                </div>

                <div className="text-right">
                  <div
                    className={
                      "inline-flex items-center gap-2 px-3 py-1.5 rounded-full border " +
                      (rushOk
                        ? "border-success/30 bg-success/10 text-success"
                        : "border-error/30 bg-error/10 text-error")
                    }
                  >
                    <span className="text-xs font-semibold">
                      {rushOk ? "RUSH READY" : "CHECK MANAGER"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-3">
                {SONGS.map((s) => {
                  const active = s.id === selectedId;
                  return (
                    <button
                      key={s.id}
                      onClick={() => setSelectedId(s.id)}
                      className={
                        "text-left rounded-2xl border p-4 transition " +
                        (active
                          ? "bg-base-300/40 border-base-300/70"
                          : "bg-base-200/30 border-base-300/35 hover:bg-base-300/30")
                      }
                    >
                      <div className="text-lg font-bold mt-1">{s.title}</div>
                      <div className="text-xs text-base-content/60 mt-1">
                        BPM {s.bpm}
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* ✅ BEAT OFFSET + RUSH INPUT */}
              <div className="mt-5 bg-base-200/35 border border-base-300/35 rounded-2xl p-4">
                <div className="text-xs tracking-[0.25em] text-base-content/70">
                  BEAT OFFSET
                </div>

                {/* RUSH INPUT 박스 */}
                <div className="mt-3 bg-base-200/35 border border-base-300/35 rounded-2xl p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs tracking-[0.25em] text-base-content/70">
                        RUSH INPUT
                      </div>
                      <div className="text-sm text-base-content/60 mt-1">
                        입력 방식 선택
                      </div>
                    </div>
                  </div>

                  <div className="mt-3 flex items-center gap-2">
                    <button
                      className={
                        "btn btn-sm rounded-xl " +
                        (rushInput === "HAND" ? "btn-primary" : "btn-ghost")
                      }
                      onClick={() => setRushInput("HAND")}
                      disabled={applyBusy}
                    >
                      손 (Hand)
                    </button>
                    <button
                      className={
                        "btn btn-sm rounded-xl " +
                        (rushInput === "COLOR" ? "btn-primary" : "btn-ghost")
                      }
                      onClick={() => setRushInput("COLOR")}
                      disabled={applyBusy}
                    >
                      스틱 (Color)
                    </button>

                    <button
                      className="btn btn-sm btn-ghost border border-base-300/40 rounded-xl ml-2"
                      onClick={applyRushModeNow}
                      disabled={applyBusy}
                      title="지금 바로 RUSH 모드+START 적용"
                    >
                      {applyBusy ? "Applying..." : "모드 선택"}
                    </button>
                  </div>

                  {applyErr ? (
                    <div className="mt-2 text-xs text-error break-all">
                      {applyErr}
                    </div>
                  ) : null}
                </div>

                {/* offset 컨트롤 */}
                <div className="mt-4 flex items-center justify-between">
                  <div>
                    <div className="text-sm text-base-content/60 mt-1">
                      첫 박 시작 시점(박자가 맞지 않으면 조정하세요)
                    </div>
                  </div>
                  <div className="text-xs text-base-content/70 tabular-nums">
                    {Math.round(selectedOffsetSec * 1000)}ms
                  </div>
                </div>

                <div className="mt-3 flex items-center gap-3">
                  <input
                    type="range"
                    min={0}
                    max={2.5}
                    step={0.01}
                    value={selectedOffsetSec}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setOffsets((prev) => ({ ...prev, [selectedId]: v }));
                      setResetNonce((n) => n + 1);
                    }}
                    className="w-full range range-sm"
                  />
                  <button
                    className="btn btn-sm btn-ghost border border-base-300/40"
                    onClick={setNowAsFirstBeat}
                    title="음악 들으면서 '첫 박'에 맞춰 눌러 오프셋 잡기"
                  >
                    Now=1st Beat
                  </button>
                </div>
              </div>

              <div className="mt-5 flex items-center justify-between gap-3">
                <div className="text-xs text-base-content/60 leading-5">
                  문제 발생 시 Manager 상태 확인
                </div>

                <button
                  onClick={startGame}
                  className="btn btn-primary rounded-xl px-6"
                  disabled={applyBusy}
                >
                  Start Game
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* PLAYING HUD */}
      {phase === "PLAYING" && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[min(820px,92vw)] pointer-events-auto">
          <div className="bg-base-200/55 border border-base-300/35 rounded-2xl px-4 py-3 backdrop-blur">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs tracking-[0.25em] text-base-content/70">
                  NOW PLAYING
                </div>
                <div className="text-lg font-bold">{selectedSong.title}</div>
                <div className="text-xs text-base-content/60">
                  BPM {selectedSong.bpm} · Offset{" "}
                  {Math.round(selectedOffsetSec * 1000)}ms · Score {hud.score} ·
                  Combo {hud.combo} · Input {desiredLabel}
                </div>
              </div>

              <div className="flex gap-2">
                {!playing ? (
                  <button
                    className="btn btn-sm btn-ghost border border-base-300/40"
                    onClick={resume}
                  >
                    Resume
                  </button>
                ) : (
                  <button
                    className="btn btn-sm btn-ghost border border-base-300/40"
                    onClick={pause}
                  >
                    Pause
                  </button>
                )}
                <button
                  className="btn btn-sm btn-ghost border border-base-300/40"
                  onClick={reset}
                >
                  Reset
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {phase === "PLAYING" && (
        <div className="absolute top-28 left-1/2 -translate-x-1/2 text-center pointer-events-none z-10">
          <div className="text-xs tracking-[0.35em] text-base-content/70">
            SCORE
          </div>
          <div className="text-5xl font-black drop-shadow">{hud.score}</div>

          {hud.combo > 1 && (
            <div className="mt-2 text-6xl font-black drop-shadow">
              {hud.combo} <span className="text-base-content/80">COMBO</span>
            </div>
          )}
          <div className="mt-1 text-sm text-base-content/60">
            MAX {hud.maxCombo}
          </div>
        </div>
      )}

      {phase === "PLAYING" && judge && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className={`text-6xl font-black drop-shadow ${judgeColor}`}>
            {judge.text}
          </div>
        </div>
      )}

      {/* RESULT UI */}
      {phase === "RESULT" && (
        <div className="absolute inset-0 z-30 pointer-events-auto">
          <div className="absolute inset-0 bg-base-100/75" />
          <div className="relative h-full flex items-center justify-center px-6">
            <div className="w-[min(720px,92vw)] bg-base-200/55 border border-base-300/35 rounded-3xl p-6 backdrop-blur">
              <div className="text-xs tracking-[0.35em] text-base-content/70">
                RESULT
              </div>
              <div className="mt-1 flex items-end justify-between gap-3">
                <div>
                  <div className="text-2xl font-black">
                    {selectedSong.title}
                  </div>
                  <div className="text-sm text-base-content/60 mt-1">
                    BPM {selectedSong.bpm} · Offset{" "}
                    {Math.round(selectedOffsetSec * 1000)}ms · Input{" "}
                    {desiredLabel}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-base-content/60">RANK</div>
                  <div className="text-4xl font-black">{rank}</div>
                  <div className="text-xs text-base-content/60 mt-1">
                    ACC {(acc * 100).toFixed(1)}%
                  </div>
                </div>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-3">
                <div className="bg-base-200/35 border border-base-300/35 rounded-2xl p-4">
                  <div className="text-xs text-base-content/60">
                    FINAL SCORE
                  </div>
                  <div className="text-4xl font-black mt-1">
                    {result?.score ?? hud.score}
                  </div>
                </div>
                <div className="bg-base-200/35 border border-base-300/35 rounded-2xl p-4">
                  <div className="text-xs text-base-content/60">MAX COMBO</div>
                  <div className="text-4xl font-black mt-1">
                    {result?.maxCombo ?? hud.maxCombo}
                  </div>
                </div>
              </div>

              <div className="mt-3 bg-base-200/35 border border-base-300/35 rounded-2xl p-4">
                <div className="text-xs text-base-content/60 mb-2">
                  JUDGEMENT
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
                  <div className="flex justify-between bg-base-100/35 rounded-xl px-3 py-2">
                    <span className="text-base-content/70">PERFECT</span>
                    <span className="font-bold">
                      {result?.perfect ?? hud.perfect}
                    </span>
                  </div>
                  <div className="flex justify-between bg-base-100/35 rounded-xl px-3 py-2">
                    <span className="text-base-content/70">GOOD</span>
                    <span className="font-bold">
                      {result?.good ?? hud.good}
                    </span>
                  </div>
                  <div className="flex justify-between bg-base-100/35 rounded-xl px-3 py-2">
                    <span className="text-base-content/70">MISS</span>
                    <span className="font-bold">
                      {result?.miss ?? hud.miss}
                    </span>
                  </div>
                  <div className="flex justify-between bg-base-100/35 rounded-xl px-3 py-2">
                    <span className="text-base-content/70">SWING MISS</span>
                    <span className="font-bold">
                      {result?.swingMiss ?? hud.swingMiss}
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-5 flex items-center justify-end gap-2">
                <button
                  className="btn btn-sm btn-ghost border border-base-300/40"
                  onClick={backToLobby}
                >
                  Back to Lobby
                </button>
                <button className="btn btn-sm btn-primary" onClick={retry}>
                  Retry
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {!connected && phase !== "RESULT" && (
        <div className="absolute bottom-4 left-4 z-10 bg-base-200/70 border border-base-300/35 rounded-2xl px-4 py-3 text-xs backdrop-blur pointer-events-none">
          백엔드 연결 OFF
        </div>
      )}
    </div>
  );
}
