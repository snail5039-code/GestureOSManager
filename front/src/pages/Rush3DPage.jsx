// Rush3DPage.jsx
// -----------------------------------------------------------------------------
// 변경 핵심
// 1) "차트 배열(hitTime...)"에 의존하지 않고, BPM/offset 기반 "비트 스폰"으로 노트 생성
//    - songTime으로 "다음 박(또는 8분박)"이 spawnTime에 도달했는지 계산해서 스폰
// 2) 곡마다 offsetSec(첫 박 시작 시간)를 맞추면 노트가 "비트에 딱 맞게" 나온다.
// 3) 히트 성공(PERFECT/GOOD) 시 slice SFX 재생(WebAudio, 저지연)
// 4) UI에 offset 조절 슬라이더 + "지금 시점을 첫 박으로" 버튼 제공
// -----------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

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
   status → 양손 읽기(네 코드 패턴 유지)
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

  const sx = status.pointerX ?? status.cursorX ?? status.x ?? status?.pointer?.x ?? null;
  const sy = status.pointerY ?? status.cursorY ?? status.y ?? status?.pointer?.y ?? null;

  const sTracking =
    status.isTracking ?? status.tracking ?? status.handTracking ?? status.handPresent ?? null;

  const hasLeft = lx != null && ly != null;
  const hasRight = rx != null && ry != null;
  const hasSingle = sx != null && sy != null;

  if (!hasLeft && !hasRight && !hasSingle) return null;

  const norm = (n) => clamp(Number(n), 0, 1);

  const left = hasLeft
    ? { nx: norm(lx), ny: norm(ly), tracking: (lTracking == null ? true : !!lTracking) && enabled }
    : null;

  const right = hasRight
    ? { nx: norm(rx), ny: norm(ry), tracking: (rTracking == null ? true : !!rTracking) && enabled }
    : null;

  const single = hasSingle
    ? { nx: norm(sx), ny: norm(sy), tracking: (sTracking == null ? true : !!sTracking) && enabled }
    : null;

  return { left, right, single };
}

/* =============================================================================
   NDC → 트랙 로컬 z평면 교차
============================================================================= */

function ndcToTrackLocalOnZPlane({ ndcX, ndcY, camera, trackObj, raycaster, localZPlane, outLocal }) {
  if (!trackObj) return false;

  raycaster.setFromCamera({ x: ndcX, y: ndcY }, camera);

  const inv = new THREE.Matrix4().copy(trackObj.matrixWorld).invert();

  const originL = raycaster.ray.origin.clone().applyMatrix4(inv);

  const dirW = raycaster.ray.direction.clone();
  const nmat = new THREE.Matrix3().getNormalMatrix(inv);
  const dirL = dirW.applyMatrix3(nmat).normalize();

  const dz = dirL.z;
  if (Math.abs(dz) < 1e-6) return false;

  const t = (localZPlane - originL.z) / dz;
  if (t <= 0) return false;

  outLocal.copy(originL).addScaledVector(dirL, t);
  return true;
}

/* =============================================================================
   RushScene (비트 기반 스폰 + 히트 FX + SFX)
============================================================================= */

function RushScene({
  statusRef,
  onHUD,
  onJudge,

  // 오디오 시간 ref(부모에서 raf로 계속 갱신)
  songTimeRef,

  // 비트 파라미터
  bpm = 120,
  beatOffsetSec = 0.65, // "첫 박"이 시작되는 시간(초) - 곡마다 튜닝
  seed = 1,             // 패턴 결정용
  playing = false,
  resetNonce = 0,

  // 히트 SFX 콜백
  onSliceSfx,
}) {
  const { camera, pointer } = useThree();

  // -----------------------------
  // 트랙/노트 파라미터
  // -----------------------------
  const LANE_X = [-2.1, 2.1];

  const HIT_Z = 5.2;
  const HIT_TOP_Y = 0.95;
  const HIT_BOT_Y = 0.45;
  const HIT_W = Math.abs(LANE_X[1] - LANE_X[0]) + 1.2;

  const CURSOR_Z = HIT_Z + 0.25;
  const SPAWN_Z = -23;
  const NOTE_SPEED = 13.0;
  const PASS_Z = HIT_Z + 10;

  // 노트가 SPAWN_Z -> HIT_Z 도착까지 걸리는 시간
  const TRAVEL_TIME = (HIT_Z - SPAWN_Z) / NOTE_SPEED;

  // -----------------------------
  // 판정/슬래시 파라미터
  // -----------------------------
  const HIT_Z_WINDOW = 1.6;
  const SLASH_SPEED = 2.2;

  // 허공 칼질 필터
  const ATTEMPT_X_TOL = 1.25;
  const ATTEMPT_Y_PAD = 0.35;
  const ATTEMPT_Z_WIN = 2.2;

  // -----------------------------
  // 풀 크기
  // -----------------------------
  const NOTE_COUNT = 26;
  const SHARD_COUNT = 40;
  const SPARK_COUNT = 120;

  // -----------------------------
  // refs
  // -----------------------------
  const trackRef = useRef(null);
  const raycasterRef = useRef(new THREE.Raycaster());
  const tmpLocal = useRef(new THREE.Vector3());
  const tmpMat = useRef(new THREE.Matrix4());

  const tmpAxisX = useRef(new THREE.Vector3(1, 0, 0));
  const tmpAxisY = useRef(new THREE.Vector3(0, 1, 0));

  // ✅ 비트 스폰 인덱스(0.5박 단위 = 8분박)
  const nextStepIdx = useRef(0);

  // 곡 시간이 뒤로 점프하면(리셋/스크럽) 보정용
  const lastSongTime = useRef(0);

  // 레인 패턴(너무 단조롭지 않게)
  const lastLaneRef = useRef(0);

  // -----------------------------
  // 커서
  // -----------------------------
  const cursorL = useRef({ x: 0, y: 1.2, tx: 0, ty: 1.2, tracking: false });
  const cursorR = useRef({ x: 0, y: 1.2, tx: 0, ty: 1.2, tracking: false });

  const cursorMeshL = useRef(null);
  const cursorMeshR = useRef(null);

  const prevL = useRef({ x: 0, y: 0, has: false });
  const prevR = useRef({ x: 0, y: 0, has: false });

  // -----------------------------
  // 점수/콤보
  // -----------------------------
  const comboRef = useRef(0);
  const maxComboRef = useRef(0);
  const scoreRef = useRef(0);

  // -----------------------------
  // 노트/파편/스파크 풀
  // -----------------------------
  const notes = useRef(
    Array.from({ length: NOTE_COUNT }, () => ({
      alive: false,
      judged: false,
      lane: 0,
      z: SPAWN_Z,
      baseSize: 0.78,
    }))
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
    }))
  );

  const sparks = useRef(
    Array.from({ length: SPARK_COUNT }, () => ({
      alive: false,
      life: 0,
      pos: new THREE.Vector3(),
      vel: new THREE.Vector3(),
    }))
  );
  const sparkPositions = useRef(new Float32Array(SPARK_COUNT * 3));

  const notesMesh = useRef(null);
  const glowMesh = useRef(null);
  const shardMesh = useRef(null);
  const sparksGeomRef = useRef(null);
  const sparksMatRef = useRef(null);

  const hudRef = useRef({ lastT: 0 });

  // -----------------------------
  // 색/재질
  // -----------------------------
  const colLeft = useMemo(() => new THREE.Color("#7dd3fc"), []);
  const colRight = useMemo(() => new THREE.Color("#ff4fd8"), []);

  const matLane = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color("#0a0f1f"),
        roughness: 0.3,
        metalness: 0.7,
      }),
    []
  );

  const matRail = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color("#9be7ff"),
        transparent: true,
        opacity: 0.9,
      }),
    []
  );

  const matNote = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.15,
        metalness: 0.9,
        emissive: new THREE.Color("#2bbcff"),
        emissiveIntensity: 0.25,
      }),
    []
  );

  const matGlow = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color("#7dd3fc"),
        transparent: true,
        opacity: 0.18,
        depthWrite: false,
      }),
    []
  );

  const matShard = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.22,
        metalness: 0.85,
        emissive: new THREE.Color("#2bbcff"),
        emissiveIntensity: 0.2,
        transparent: true,
        opacity: 1,
      }),
    []
  );

  const sparkMaterial = useMemo(
    () =>
      new THREE.PointsMaterial({
        size: 0.08,
        color: new THREE.Color("#ffffff"),
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
      }),
    []
  );

  const matHitCore = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color("#c7f3ff"),
        transparent: true,
        opacity: 0.9,
      }),
    []
  );

  const matHitGlow = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: new THREE.Color("#7dd3fc"),
        transparent: true,
        opacity: 0.18,
        depthWrite: false,
      }),
    []
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

    // ✅ 비트 스폰 인덱스 리셋
    nextStepIdx.current = 0;
    lastSongTime.current = 0;
    lastLaneRef.current = 0;

    // 인스턴스 숨김
    if (notesMesh.current && glowMesh.current) {
      for (let i = 0; i < NOTE_COUNT; i++) {
        tmpMat.current.identity();
        tmpMat.current.makeScale(0.0001, 0.0001, 0.0001);
        notesMesh.current.setMatrixAt(i, tmpMat.current);
        glowMesh.current.setMatrixAt(i, tmpMat.current);
      }
      notesMesh.current.instanceMatrix.needsUpdate = true;
      glowMesh.current.instanceMatrix.needsUpdate = true;
    }

    if (shardMesh.current) {
      for (let i = 0; i < SHARD_COUNT; i++) {
        tmpMat.current.identity();
        tmpMat.current.makeScale(0.0001, 0.0001, 0.0001);
        shardMesh.current.setMatrixAt(i, tmpMat.current);
      }
      shardMesh.current.instanceMatrix.needsUpdate = true;
    }

    if (sparksGeomRef.current) sparksGeomRef.current.attributes.position.needsUpdate = true;
  }, [resetNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  /* =========================
     노트 스폰
     - lateSec: 스폰 늦었으면 z를 앞으로 당겨 싱크 보정
  ========================= */
  const spawnNote = (lane, lateSec = 0) => {
    const arr = notes.current;
    const idx = noteWriteIdx.current;
    noteWriteIdx.current = (idx + 1) % arr.length;

    arr[idx].alive = true;
    arr[idx].judged = false;
    arr[idx].lane = lane;

    const late = clamp(lateSec, 0, TRAVEL_TIME);
    arr[idx].z = SPAWN_Z + NOTE_SPEED * late;
    arr[idx].baseSize = 0.78;
  };

  const notePose = (n) => {
    const progress = clamp((n.z - SPAWN_Z) / (HIT_Z - SPAWN_Z), 0, 1);
    const x = LANE_X[n.lane];
    const y = THREE.MathUtils.lerp(2.9, HIT_TOP_Y, progress);
    const s = n.baseSize * THREE.MathUtils.lerp(0.55, 1.25, progress);
    return { x, y, s, z: n.z };
  };

  const applyJudge = (text, lane) => {
    if (text === "PERFECT") {
      comboRef.current += 1;
      scoreRef.current += 300;
    } else if (text === "GOOD") {
      comboRef.current += 1;
      scoreRef.current += 100;
    } else if (text === "MISS") {
      comboRef.current = 0;
    }

    if (comboRef.current > maxComboRef.current) maxComboRef.current = comboRef.current;
    onJudge?.(text, lane);
  };

  const isSlashInLaneBand = (lane, a, b) => {
    const minX = Math.min(a.x, b.x);
    const maxX = Math.max(a.x, b.x);
    const minY = Math.min(a.y, b.y);
    const maxY = Math.max(a.y, b.y);

    const okX = minX <= LANE_X[lane] + ATTEMPT_X_TOL && maxX >= LANE_X[lane] - ATTEMPT_X_TOL;
    const okY = maxY >= HIT_BOT_Y - ATTEMPT_Y_PAD && minY <= HIT_TOP_Y + ATTEMPT_Y_PAD;
    return okX && okY;
  };

  const hasCuttableNoteNearHit = (lane) => {
    for (const n of notes.current) {
      if (!n.alive) continue;
      if (n.lane !== lane) continue;

      const dz = Math.abs(n.z - HIT_Z);
      if (dz > ATTEMPT_Z_WIN) continue;

      const { y } = notePose(n);
      const inY = y >= HIT_BOT_Y - ATTEMPT_Y_PAD && y <= HIT_TOP_Y + ATTEMPT_Y_PAD;
      if (!inY) continue;

      return true;
    }
    return false;
  };

  /* =========================
     split FX (가로/세로 베기 반영)
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
      let pick = shards.current.find((s) => !s.alive);
      if (!pick) pick = shards.current[(Math.random() * shards.current.length) | 0];

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
        (dir > 0 ? -1 : 1) * (1 + Math.random() * 2)
      );

      if (splitAxis === "Y") {
        pick.scale.set(sizeS * 1.0, sizeS * frac, sizeS * 0.35); // 위/아래 분리
      } else {
        pick.scale.set(sizeS * frac, sizeS * 1.0, sizeS * 0.35); // 좌/우 분리
      }

      pick.color.copy(laneColor);
    };

    spawnShardPiece(-1, aFrac, aCenterOffset);
    spawnShardPiece(+1, bFrac, bCenterOffset);

    for (let i = 0; i < 18; i++) {
      let sp = sparks.current.find((s) => !s.alive);
      if (!sp) sp = sparks.current[(Math.random() * sparks.current.length) | 0];

      const ang = Math.random() * Math.PI * 2;
      const spd = 6 + Math.random() * 11;

      sp.alive = true;
      sp.life = 0.45 + Math.random() * 0.35;
      sp.pos.copy(hitPos);
      sp.vel.set(Math.cos(ang) * spd, 3 + Math.random() * 6, -2 - Math.random() * 4);
    }
  };

  /* =========================
     히트 판정
     - 가로로 휘두르면 splitAxis="Y" => 위/아래로 갈라짐
     - 세로로 휘두르면 splitAxis="X" => 좌/우로 갈라짐
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
        y + halfH + pad
      );
      if (!info) continue;

      const slashDx = segB.x - segA.x;
      const slashDy = segB.y - segA.y;

      // 가로 휘두름 => 위/아래 분리(Y)
      // 세로 휘두름 => 좌/우 분리(X)
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
    const text = bestDist <= PERFECT ? "PERFECT" : bestDist <= GOOD ? "GOOD" : "MISS";

    if (text !== "MISS") {
      const { x, y, s, z } = notePose(best);
      const hitLocal = new THREE.Vector3(x, y, z);

      spawnSplitFX(lane, hitLocal, s, bestSplitAxis, bestCutRatio);

      // ✅ 히트 성공 시 슬라이스 소리
      onSliceSfx?.();

      best.judged = true;
      best.alive = false;
    }

    applyJudge(text, lane);
  };

  const stepSlash = (curRef, prevRef, lane, dt) => {
    const now = { x: curRef.current.x, y: curRef.current.y };

    if (!prevRef.current.has) {
      prevRef.current.x = now.x;
      prevRef.current.y = now.y;
      prevRef.current.has = true;
      return false;
    }

    const a = { x: prevRef.current.x, y: prevRef.current.y };
    const b = { x: now.x, y: now.y };

    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const speed = Math.sqrt(dx * dx + dy * dy) / Math.max(dt, 1e-4);

    let didSlash = false;

    if (curRef.current.tracking && speed >= SLASH_SPEED) {
      const attempt = hasCuttableNoteNearHit(lane) && isSlashInLaneBand(lane, a, b);
      if (attempt) {
        didSlash = true;
        tryHitLane(lane, a, b);
      }
    }

    prevRef.current.x = now.x;
    prevRef.current.y = now.y;
    return didSlash;
  };

  /* =============================================================================
     useFrame: 비트 기반 스폰 핵심
     - stepSec = (60/bpm) * 0.5  (8분박 단위)
     - stepTime = beatOffsetSec + stepIdx * stepSec  (해당 스텝이 울리는 시간)
     - spawnTime = stepTime - TRAVEL_TIME
     - songTime >= spawnTime 이면 스폰
  ============================================================================= */
  useFrame((state, dt) => {
    const st = statusRef.current;
    const hand = readTwoHandsFromStatus(st);

    const mouseNdcX = pointer.x;
    const mouseNdcY = pointer.y;

    let leftNdc = null;
    let rightNdc = null;

    if (hand) {
      if (hand.left) {
        leftNdc = { x: hand.left.nx * 2 - 1, y: (1 - hand.left.ny) * 2 - 1, tracking: hand.left.tracking };
      }
      if (hand.right) {
        rightNdc = { x: hand.right.nx * 2 - 1, y: (1 - hand.right.ny) * 2 - 1, tracking: hand.right.tracking };
      }
      if (!leftNdc && !rightNdc && hand.single) {
        rightNdc = { x: hand.single.nx * 2 - 1, y: (1 - hand.single.ny) * 2 - 1, tracking: hand.single.tracking };
      }
    }

    if (!leftNdc && !rightNdc) {
      leftNdc = { x: mouseNdcX, y: mouseNdcY, tracking: true };
      rightNdc = { x: mouseNdcX, y: mouseNdcY, tracking: true };
    }

    // 레이캐스트 -> 커서 타겟
    const trackObj = trackRef.current;
    const raycaster = raycasterRef.current;
    const hit = tmpLocal.current;

    const updateCursorFromNdc = (ndc, curRef) => {
      if (!ndc) {
        curRef.current.tracking = false;
        return;
      }
      curRef.current.tracking = !!ndc.tracking;
      if (!trackObj) return;

      const ok = ndcToTrackLocalOnZPlane({
        ndcX: ndc.x,
        ndcY: ndc.y,
        camera,
        trackObj,
        raycaster,
        localZPlane: CURSOR_Z,
        outLocal: hit,
      });
      if (!ok) return;

      curRef.current.tx = hit.x;
      curRef.current.ty = hit.y;
    };

    updateCursorFromNdc(leftNdc, cursorL);
    updateCursorFromNdc(rightNdc, cursorR);

    // 커서 스무딩
    {
      const smooth = (curRef) => {
        const k = 1 - Math.exp(-dt * 28);
        curRef.current.x += (curRef.current.tx - curRef.current.x) * k;
        curRef.current.y += (curRef.current.ty - curRef.current.y) * k;
      };
      smooth(cursorL);
      smooth(cursorR);
    }

    // ✅ 비트 스폰
    const songTime = songTimeRef?.current ?? 0;

    // 시간이 뒤로 점프하면(리셋/스크럽) 스폰 인덱스도 리셋
    if (songTime < lastSongTime.current - 0.05) {
      nextStepIdx.current = 0;
      lastLaneRef.current = 0;
    }
    lastSongTime.current = songTime;

    if (playing && bpm > 0) {
      const beatSec = 60 / bpm;
      const stepSec = beatSec * 0.5; // 8분박 단위

      // while로 "지금 시간까지 스폰되어야 할 스텝"을 다 처리
      while (true) {
        const stepIdx = nextStepIdx.current;
        const stepTime = beatOffsetSec + stepIdx * stepSec; // 이 스텝이 울리는 시각
        const spawnTime = stepTime - TRAVEL_TIME;          // 이 스텝 노트를 스폰해야 하는 시각

        if (songTime < spawnTime) break; // 아직 스폰 시간 아님

        // 늦게 스폰된 정도(보정용)
        const late = songTime - spawnTime;

        // 스텝 종류: on-beat(박) vs off-beat(8분)
        const onBeat = stepIdx % 2 === 0;

        // 결정적 난수(곡마다, 스텝마다 고정)
        const r = hash01((seed * 1000000 + stepIdx) | 0);

        // 중간 난이도 규칙:
        // - onBeat는 항상 스폰
        // - offBeat는 확률로만(너무 어렵지 않게)
        const spawnThisStep = onBeat ? true : r < 0.35;

        if (spawnThisStep) {
          // 레인 선택
          let lane;

          if (onBeat) {
            // 기본은 번갈이, 가끔 같은 레인
            lane = lastLaneRef.current ^ 1;
            if (r < 0.20) lane = lastLaneRef.current;
          } else {
            // offBeat는 보통 반대 레인(손맛), 가끔 같은 레인
            lane = lastLaneRef.current ^ 1;
            if (r < 0.12) lane = lastLaneRef.current;
          }

          spawnNote(lane, late);
          lastLaneRef.current = lane;

          // 아주 가끔 강박(예: 16박마다) 양손 동시치기 1번
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

    // 노트 이동 + MISS 처리
    if (playing) {
      const noteIM = notesMesh.current;
      const glowIM = glowMesh.current;

      if (noteIM && glowIM) {
        for (let i = 0; i < NOTE_COUNT; i++) {
          const n = notes.current[i];

          if (n.alive) {
            n.z += NOTE_SPEED * dt;

            if (!n.judged && n.z > HIT_Z + HIT_Z_WINDOW) {
              n.judged = true;
              n.alive = false;
              applyJudge("MISS", n.lane);
            }

            if (n.z > PASS_Z) n.alive = false;
          }

          if (!n.alive) {
            tmpMat.current.identity();
            tmpMat.current.makeScale(0.0001, 0.0001, 0.0001);
            noteIM.setMatrixAt(i, tmpMat.current);
            glowIM.setMatrixAt(i, tmpMat.current);
            continue;
          }

          const progress = clamp((n.z - SPAWN_Z) / (HIT_Z - SPAWN_Z), 0, 1);

          const x = LANE_X[n.lane];
          const y = THREE.MathUtils.lerp(2.9, HIT_TOP_Y, progress);
          const z = n.z;

          const s = n.baseSize * THREE.MathUtils.lerp(0.55, 1.25, progress);

          tmpMat.current.compose(new THREE.Vector3(x, y, z), new THREE.Quaternion(), new THREE.Vector3(s, s, s * 0.35));
          noteIM.setMatrixAt(i, tmpMat.current);

          tmpMat.current.compose(
            new THREE.Vector3(x, y, z - 0.08),
            new THREE.Quaternion(),
            new THREE.Vector3(s * 1.25, s * 1.25, s * 0.25)
          );
          glowIM.setMatrixAt(i, tmpMat.current);

          noteIM.setColorAt(i, n.lane === 0 ? colLeft : colRight);
        }

        noteIM.instanceMatrix.needsUpdate = true;
        glowIM.instanceMatrix.needsUpdate = true;
        if (noteIM.instanceColor) noteIM.instanceColor.needsUpdate = true;
      }
    }

    // 히트(양손)
    let firedL = false;
    let firedR = false;
    if (playing) {
      firedL = stepSlash(cursorL, prevL, 0, dt);
      firedR = stepSlash(cursorR, prevR, 1, dt);
    }

    // 커서 표시
    if (cursorMeshL.current) {
      cursorMeshL.current.visible = cursorL.current.tracking;
      cursorMeshL.current.position.set(cursorL.current.x, cursorL.current.y, CURSOR_Z);
    }
    if (cursorMeshR.current) {
      cursorMeshR.current.visible = cursorR.current.tracking;
      cursorMeshR.current.position.set(cursorR.current.x, cursorR.current.y, CURSOR_Z);
    }

    // 파편 업데이트
    if (shardMesh.current) {
      const g = -13.0;

      for (let i = 0; i < SHARD_COUNT; i++) {
        const sh = shards.current[i];

        if (!sh.alive) {
          tmpMat.current.identity();
          tmpMat.current.makeScale(0.0001, 0.0001, 0.0001);
          shardMesh.current.setMatrixAt(i, tmpMat.current);
          continue;
        }

        sh.life -= dt;
        if (sh.life <= 0) {
          sh.alive = false;
          tmpMat.current.identity();
          tmpMat.current.makeScale(0.0001, 0.0001, 0.0001);
          shardMesh.current.setMatrixAt(i, tmpMat.current);
          continue;
        }

        sh.vel.y += g * dt;
        sh.pos.addScaledVector(sh.vel, dt);

        sh.rot.x += sh.rotVel.x * dt;
        sh.rot.y += sh.rotVel.y * dt;
        sh.rot.z += sh.rotVel.z * dt;

        const q = new THREE.Quaternion().setFromEuler(sh.rot);
        tmpMat.current.compose(sh.pos, q, sh.scale);

        shardMesh.current.setMatrixAt(i, tmpMat.current);
        shardMesh.current.setColorAt(i, sh.color);
      }

      shardMesh.current.instanceMatrix.needsUpdate = true;
      if (shardMesh.current.instanceColor) shardMesh.current.instanceColor.needsUpdate = true;
    }

    // 스파크 업데이트
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

      if (sparksGeomRef.current) sparksGeomRef.current.attributes.position.needsUpdate = true;
      if (sparksMatRef.current) sparksMatRef.current.opacity = 0.9;
    }

    // HUD(10fps)
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
      });
    }
  });

  return (
    <>
      <color attach="background" args={["#050816"]} />
      <fog attach="fog" args={["#070a14", 10, 44]} />

      <ambientLight intensity={0.55} />
      <directionalLight position={[6, 8, 6]} intensity={0.85} />
      <pointLight position={[-6, 3, 2]} intensity={1.0} color={"#7dd3fc"} />
      <pointLight position={[6, 3, -10]} intensity={0.9} color={"#ff4fd8"} />

      <group ref={trackRef} position={[0, 0.8, 0]}>
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, -14]} material={matLane}>
          <planeGeometry args={[18, 46]} />
        </mesh>

        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[-2.1, 0.01, -14]} material={matRail}>
          <planeGeometry args={[0.03, 46]} />
        </mesh>
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[2.1, 0.01, -14]} material={matRail}>
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

        <instancedMesh ref={glowMesh} args={[null, null, NOTE_COUNT]} material={matGlow}>
          <boxGeometry args={[1, 1, 1]} />
        </instancedMesh>

        <instancedMesh ref={notesMesh} args={[null, null, NOTE_COUNT]} material={matNote}>
          <boxGeometry args={[1, 1, 1]} />
        </instancedMesh>

        <instancedMesh ref={shardMesh} args={[null, null, SHARD_COUNT]} material={matShard}>
          <boxGeometry args={[1, 1, 1]} />
        </instancedMesh>

        <points>
          <bufferGeometry ref={sparksGeomRef}>
            <bufferAttribute attach="attributes-position" array={sparkPositions.current} itemSize={3} count={SPARK_COUNT} />
          </bufferGeometry>
          <pointsMaterial ref={sparksMatRef} attach="material" {...sparkMaterial} />
        </points>

        {/* 커서 RIGHT */}
        <group ref={cursorMeshR} rotation={[0, 0, -0.6]} renderOrder={999}>
          <pointLight color={"#ff4fd8"} intensity={1.6} distance={7} decay={2} />
          <mesh renderOrder={999}>
            <boxGeometry args={[0.10, 0.85, 0.05]} />
            <meshBasicMaterial color={"#ff4fd8"} transparent opacity={0.18} depthTest={false} depthWrite={false} />
          </mesh>
          <mesh position={[0, 0.06, 0]} renderOrder={999}>
            <boxGeometry args={[0.05, 0.72, 0.02]} />
            <meshStandardMaterial
              color={"#ffd1f3"}
              metalness={0.85}
              roughness={0.18}
              emissive={"#ff4fd8"}
              emissiveIntensity={0.35}
              transparent
              opacity={0.98}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh position={[0, -0.34, 0]} renderOrder={999}>
            <cylinderGeometry args={[0.035, 0.035, 0.18, 12]} />
            <meshStandardMaterial color={"#1a1f2e"} metalness={0.2} roughness={0.85} depthTest={false} depthWrite={false} />
          </mesh>
        </group>

        {/* 커서 LEFT */}
        <group ref={cursorMeshL} rotation={[0, 0, 0.6]} renderOrder={999}>
          <pointLight color={"#7dd3fc"} intensity={1.6} distance={7} decay={2} />
          <mesh renderOrder={999}>
            <boxGeometry args={[0.10, 0.85, 0.05]} />
            <meshBasicMaterial color={"#7dd3fc"} transparent opacity={0.18} depthTest={false} depthWrite={false} />
          </mesh>
          <mesh position={[0, 0.06, 0]} renderOrder={999}>
            <boxGeometry args={[0.05, 0.72, 0.02]} />
            <meshStandardMaterial
              color={"#d7f4ff"}
              metalness={0.85}
              roughness={0.18}
              emissive={"#7dd3fc"}
              emissiveIntensity={0.35}
              transparent
              opacity={0.98}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh position={[0, -0.34, 0]} renderOrder={999}>
            <cylinderGeometry args={[0.035, 0.035, 0.18, 12]} />
            <meshStandardMaterial color={"#1a1f2e"} metalness={0.2} roughness={0.85} depthTest={false} depthWrite={false} />
          </mesh>
        </group>
      </group>
    </>
  );
}

/* =============================================================================
   Rush3DPage (곡 선택 + 오디오 + offset 조절 + SFX 로딩)
============================================================================= */

export default function Rush3DPage({ status, connected = true }) {
  const statusRef = useRef(null);
  useEffect(() => {
    statusRef.current = status ?? null;
  }, [status]);

  // (테스트용) polling
  const [fastStatus, setFastStatus] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch("/api/control/status");
        const j = await r.json();
        if (alive) setFastStatus(j);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 100);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    statusRef.current = fastStatus ?? status ?? null;
  }, [fastStatus, status]);

  // ✅ 곡 목록
  // - 공백/한글 파일명은 환경에 따라 로딩 이슈가 생길 수 있어(특히 배포)
  // - 가장 안전: 파일명을 ASCII로(da.mp3, lemon_tree.mp3, rush_f.mp3)
  const SONGS = useMemo(
    () => [
      // offsetSec: "첫 박(다운비트)"가 시작되는 시점 (처음엔 대충 넣고 슬라이더로 맞추면 됨)
      { id: "da", title: "다 멍청해", src: encodeURI("/audio/다 멍청해.mp3"), bpm: 120, offsetSec: 0.65, seed: 11 },
      { id: "lemon", title: "Lemon Tree", src: encodeURI("/audio/lemon_tree.mp3"), bpm: 128, offsetSec: 0.80, seed: 22 },
      { id: "rush", title: "Rush F", src: encodeURI("/audio/rush_e.mp3"), bpm: 112, offsetSec: 0.70, seed: 33 },
    ],
    []
  );

  const [selectedId, setSelectedId] = useState(SONGS[0].id);
  const selectedSong = SONGS.find((s) => s.id === selectedId) || SONGS[0];

  // 곡별 offset을 state로 관리(슬라이더로 튜닝 가능)
  const [offsets, setOffsets] = useState(() => {
    const obj = {};
    for (const s of SONGS) obj[s.id] = s.offsetSec;
    return obj;
  });

  const selectedOffsetSec = offsets[selectedId] ?? selectedSong.offsetSec;

  // 오디오 ref + songTime ref
  const audioRef = useRef(null);
  const songTimeRef = useRef(0);

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
  });

  const [judge, setJudge] = useState(null);

  // ---------------------------------------------------------------------------
  // ✅ Slice SFX (WebAudio - 저지연)
  // - 브라우저 정책 때문에 "사용자 클릭"에서 AudioContext resume/로드가 안전함
  // ---------------------------------------------------------------------------
  const sfxRef = useRef({
    ctx: null,
    buf: null,
    ready: false,
  });

  const ensureSfxReady = async () => {
    if (sfxRef.current.ready) return;

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;

    if (!sfxRef.current.ctx) {
      sfxRef.current.ctx = new AudioCtx();
    }

    // 사용자 제스처에서 resume되어야 함
    if (sfxRef.current.ctx.state !== "running") {
      await sfxRef.current.ctx.resume();
    }

    // 버퍼 로드/디코드
    const res = await fetch("/sfx/slice.wav");
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
    gain.gain.value = 0.65; // 소리 크기

    src.connect(gain).connect(ctx.destination);
    src.start(0);
  };

  // ---------------------------------------------------------------------------
  // 곡 변경 시 오디오 로드/리셋
  // ---------------------------------------------------------------------------
  useEffect(() => {
    setPlaying(false);
    setResetNonce((n) => n + 1);

    const audio = audioRef.current;
    if (!audio) return;

    audio.pause();
    audio.currentTime = 0;
    audio.src = selectedSong.src;
  }, [selectedId, selectedSong.src]);

  // songTimeRef 갱신
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      const a = audioRef.current;
      songTimeRef.current = a ? a.currentTime || 0 : 0;

      if (a && playing && a.duration && a.currentTime >= a.duration) {
        setPlaying(false);
      }

      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  // ---------------------------------------------------------------------------
  // 버튼
  // ---------------------------------------------------------------------------
  const start = async () => {
    const a = audioRef.current;
    if (!a) return;

    // ✅ SFX 준비 (사용자 클릭에서만 안정적으로 동작)
    try {
      await ensureSfxReady();
    } catch {
      // SFX 실패해도 게임은 진행
    }

    a.currentTime = 0;
    try {
      await a.play();
      setPlaying(true);
      setResetNonce((n) => n + 1);
    } catch {
      setPlaying(false);
    }
  };

  const pause = () => {
    const a = audioRef.current;
    if (a) a.pause();
    setPlaying(false);
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

  // "지금 시점을 첫 박으로" (offset 빠르게 맞추기)
  const setNowAsFirstBeat = () => {
    const a = audioRef.current;
    if (!a) return;
    const t = a.currentTime || 0;

    setOffsets((prev) => ({ ...prev, [selectedId]: t }));
    setResetNonce((n) => n + 1);
  };

  // 판정 텍스트 색
  const judgeColor =
    judge?.lane === 0 ? "text-cyan-200" : judge?.lane === 1 ? "text-fuchsia-200" : "text-white";

  return (
    <div className="w-full bg-slate-950 text-slate-100 relative overflow-hidden" style={{ height: "100dvh" }}>
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
            playing={playing}
            resetNonce={resetNonce}
            onSliceSfx={playSliceSfx}
            onHUD={(h) => setHud(h)}
            onJudge={(text, lane) => {
              setJudge({ text, lane, ts: performance.now() });
              setTimeout(() => setJudge(null), 420);
            }}
          />
        </group>
      </Canvas>

      {/* 상단: 곡 선택 + 컨트롤 */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-[min(820px,92vw)] pointer-events-auto">
        <div className="bg-black/45 border border-white/10 rounded-2xl px-4 py-3 backdrop-blur">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs tracking-[0.25em] text-white/70">MUSIC SELECT</div>
              <div className="text-lg font-bold">{selectedSong.title}</div>
              <div className="text-xs text-white/60">
                BPM {selectedSong.bpm} · BeatOffset {Math.round(selectedOffsetSec * 1000)}ms
              </div>
            </div>

            <div className="flex gap-2">
              <button className="px-4 py-2 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15" onClick={start}>
                Start
              </button>
              <button className="px-4 py-2 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15" onClick={pause}>
                Pause
              </button>
              <button className="px-4 py-2 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15" onClick={reset}>
                Reset
              </button>
            </div>
          </div>

          {/* 곡 버튼 */}
          <div className="mt-3 flex gap-2 flex-wrap">
            {SONGS.map((s) => {
              const active = s.id === selectedId;
              return (
                <button
                  key={s.id}
                  onClick={() => setSelectedId(s.id)}
                  className={
                    "px-3 py-2 rounded-xl border text-sm " +
                    (active ? "bg-white/15 border-white/25" : "bg-white/5 border-white/10 hover:bg-white/10")
                  }
                >
                  {s.title}
                </button>
              );
            })}
          </div>

          {/* ✅ Beat Offset 튜닝 UI */}
          <div className="mt-3 grid gap-2">
            <div className="text-xs text-white/70">Beat Offset (첫 박 시작 시점) — 노트가 박자에서 밀리면 여기만 맞추면 됨</div>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={0}
                max={2.5}
                step={0.01}
                value={selectedOffsetSec}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setOffsets((prev) => ({ ...prev, [selectedId]: v }));
                  // 튜닝 중엔 즉시 반영되게 씬 리셋
                  setResetNonce((n) => n + 1);
                }}
                className="w-full"
              />
              <div className="w-24 text-right text-xs text-white/80 tabular-nums">
                {Math.round(selectedOffsetSec * 1000)}ms
              </div>
              <button
                className="px-3 py-2 rounded-lg bg-white/10 border border-white/15 hover:bg-white/15 text-xs"
                onClick={setNowAsFirstBeat}
                title="음악 들으면서 '첫 박'에 맞춰 눌러서 오프셋을 잡기"
              >
                Now=1st Beat
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 큰 SCORE / COMBO */}
      <div className="absolute top-28 left-1/2 -translate-x-1/2 text-center pointer-events-none z-10">
        <div className="text-xs tracking-[0.35em] text-white/70">SCORE</div>
        <div className="text-5xl font-black drop-shadow">{hud.score}</div>

        {hud.combo > 1 && (
          <div className="mt-2 text-6xl font-black drop-shadow">
            {hud.combo} <span className="text-white/80">COMBO</span>
          </div>
        )}
        <div className="mt-1 text-sm text-white/60">MAX {hud.maxCombo}</div>
      </div>

      {/* 판정 텍스트 */}
      {judge && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className={`text-6xl font-black drop-shadow ${judgeColor}`}>{judge.text}</div>
        </div>
      )}

      {!connected && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="bg-black/60 border border-white/10 rounded-2xl px-5 py-4 text-sm backdrop-blur">
            백엔드 연결 OFF
          </div>
        </div>
      )}

      {/* 디버그 */}
      <div className="absolute bottom-4 right-4 bg-black/45 border border-white/10 rounded-xl px-3 py-2 text-xs leading-5 pointer-events-none">
        <div>playing: {String(playing)}</div>
        <div>songTime: {hud.songTime?.toFixed?.(2) ?? "0.00"}</div>
        <div>offset: {hud.beatOffsetSec?.toFixed?.(2) ?? "0.00"}s</div>
        <div>tracking L/R: {String(hud.trackingL)} / {String(hud.trackingR)}</div>
      </div>
    </div>
  );
}
