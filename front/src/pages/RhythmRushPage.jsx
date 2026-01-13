import { useEffect, useRef, useState } from "react";

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}
function nowMs() {
  return performance.now();
}

/**
 * status에서 포인터 좌표를 최대한 넓게 추정해서 뽑음.
 * - (1) flat 키: pointerX/pointerY, cursorX/cursorY, x/y
 * - (2) nested: pointer:{x,y}, cursor:{x,y}
 * - 좌표가 0~1이면 canvas 픽셀로 변환
 */
function readPointerFromStatus(status, rectLike) {
  if (!status || !rectLike) return null;

  const rawX =
    status.pointerX ??
    status.cursorX ??
    status.handX ??
    status.x ??
    status?.pointer?.x ??
    status?.cursor?.x ??
    null;

  const rawY =
    status.pointerY ??
    status.cursorY ??
    status.handY ??
    status.y ??
    status?.pointer?.y ??
    status?.cursor?.y ??
    null;

  if (rawX == null || rawY == null) return null;

  let x = Number(rawX);
  let y = Number(rawY);

  // rectLike: { width, height }
  const w = rectLike.width;
  const h = rectLike.height;

  // 0~1 정규화면 픽셀로 변환
  if (x >= 0 && x <= 1) x = x * w;
  if (y >= 0 && y <= 1) y = y * h;

  // 트래킹 후보 키들 (없으면 true로 가정)
  const tracking =
    status.isTracking ??
    status.tracking ??
    status.handTracking ??
    status.handPresent ??
    true;

  // enabled가 false면 입력 끊긴 것으로 취급
  const enabled = status.enabled == null ? true : !!status.enabled;

  return {
    x: clamp(x, 0, w),
    y: clamp(y, 0, h),
    tracking: !!tracking && enabled,
  };
}

/**
 * SwipeDown detector (debug는 10fps로만 업데이트)
 */
function useSwipeDownDetector({
  dyThresholdPx = 140,
  vyThresholdPxPerSec = 1200,
  dxLimitPx = 260,
  windowMs = 180,
  cooldownMs = 260,
} = {}) {
  const samplesRef = useRef([]);
  const lastFireRef = useRef(-1e9);

  const [debug, setDebug] = useState({
    dy: 0,
    dx: 0,
    vy: 0,
    cooldownLeft: 0,
    fired: false,
    samples: 0,
  });
  const debugThrottleRef = useRef({ lastT: 0 });

  const pushSample = (x, y) => {
    const t = nowMs();
    const arr = samplesRef.current;
    arr.push({ t, x, y });

    const cutoff = t - windowMs;
    while (arr.length && arr[0].t < cutoff) arr.shift();
  };

  const consumeSwipeIfAny = () => {
    const t = nowMs();
    const since = t - lastFireRef.current;
    const cooldownLeft = Math.max(0, cooldownMs - since);

    const arr = samplesRef.current;
    let fired = false;
    let dy = 0,
      dx = 0,
      vy = 0;

    if (arr.length >= 2) {
      const first = arr[0];
      const last = arr[arr.length - 1];

      dy = last.y - first.y;
      dx = last.x - first.x;

      const dt = (last.t - first.t) / 1000;
      vy = dt > 0 ? dy / dt : 0;

      if (cooldownLeft <= 0) {
        const okDy = dy >= dyThresholdPx;
        const okVy = vy >= vyThresholdPxPerSec;
        const okDx = Math.abs(dx) <= dxLimitPx;

        if (okDy && okVy && okDx) {
          fired = true;
          lastFireRef.current = t;
          samplesRef.current = [];
        }
      }
    }

    // debug는 10fps만
    const th = debugThrottleRef.current;
    if (t - th.lastT > 100) {
      th.lastT = t;
      setDebug({
        dy: Math.round(dy),
        dx: Math.round(dx),
        vy: Math.round(vy),
        cooldownLeft: Math.round(cooldownLeft),
        fired,
        samples: arr.length,
      });
    }

    return fired;
  };

  return { pushSample, consumeSwipeIfAny, debug };
}

export default function RhythmRushPage({ status, connected = true }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);
  const hostRef = useRef(null);

  // ✅ loop에서 rect를 매 프레임 읽지 않기 위한 w/h ref
  const viewRef = useRef({ w: 0, h: 0 });

  // ✅ status는 state로 돌리지 말고 ref로만 최신값 유지 (리렌더 방지)
  const statusRef = useRef(null);

  // 부모에서 status prop이 오면 ref에 반영(있으면 사용)
  useEffect(() => {
    if (status) statusRef.current = status;
  }, [status]);

  // pointer 상태(에이전트/마우스 공용) + target(tx,ty)로 스무딩
  const pointerRef = useRef({
    x: 0,
    y: 0,
    tx: 0,
    ty: 0,
    down: false,
    tracking: false,
    source: "none", // "agent" | "mouse"

    // ✅ agent 좌표 속도 추정용
    vx: 0, // px/ms
    vy: 0,
    _lastAx: null,
    _lastAy: null,
    _lastAt: null, // ms
  });

  const [swipeCount, setSwipeCount] = useState(0);
  const [source, setSource] = useState("none");
  const [trackingUI, setTrackingUI] = useState(false);

  // HUD 업데이트는 10fps 제한
  const hudRef = useRef({ source: "none", tracking: false, lastT: 0 });

  // 판정 표시
  const [judge, setJudge] = useState(null); // { text, t }
  const judgeRef = useRef(null);

  // 노트(큰 네모)
  const noteRef = useRef({
    y: -80,
    speed: 520,
    alive: true,
  });

  const { pushSample, consumeSwipeIfAny, debug } = useSwipeDownDetector({
    dyThresholdPx: 140,
    vyThresholdPxPerSec: 1200,
    dxLimitPx: 260,
    windowMs: 180,
    cooldownMs: 260,
  });

  // draw loop에서 안정적으로 쓰기 위해 ref로 보관
  const pushSampleRef = useRef(pushSample);
  const consumeRef = useRef(consumeSwipeIfAny);
  useEffect(() => {
    pushSampleRef.current = pushSample;
    consumeRef.current = consumeSwipeIfAny;
  }, [pushSample, consumeSwipeIfAny]);

  const resizeCanvas = () => {
    const c = canvasRef.current;
    if (!c) return;
    const parent = hostRef.current;
    if (!parent) return;

    const rect = parent.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;

    c.width = Math.floor(rect.width * dpr);
    c.height = Math.floor(rect.height * dpr);
    c.style.width = `${rect.width}px`;
    c.style.height = `${rect.height}px`;

    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // ✅ loop에서 쓸 값은 여기서만 갱신
    viewRef.current.w = rect.width;
    viewRef.current.h = rect.height;
  };

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;

    const ro = new ResizeObserver(() => resizeCanvas());
    ro.observe(el);

    // 처음 1~2프레임은 레이아웃이 늦게 잡히는 경우가 있어서 보강
    const r1 = requestAnimationFrame(() => resizeCanvas());
    const r2 = requestAnimationFrame(() => resizeCanvas());

    return () => {
      ro.disconnect();
      cancelAnimationFrame(r1);
      cancelAnimationFrame(r2);
    };
  }, []);

  // ✅ 고속 폴링: "겹치지 않게(single-flight)" + ref만 업데이트(리렌더 X)
  useEffect(() => {
    let alive = true;
    let timer = null;
    const ctrl = new AbortController();

    const poll = async () => {
      if (!alive) return;

      const t0 = performance.now();
      try {
        const r = await fetch("/api/control/status", {
          cache: "no-store",
          signal: ctrl.signal,
        });
        const j = await r.json();
        statusRef.current = j; // ✅ 렌더링 없이 최신 status 반영
      } catch {
        // ignore
      } finally {
        // ✅ 목표 30fps 정도. 서버가 느리면 자동으로 더 느려짐(겹침 방지)
        const elapsed = performance.now() - t0;
        const wait = Math.max(0, 33 - elapsed);
        timer = window.setTimeout(poll, wait);
      }
    };

    poll();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
      ctrl.abort();
    };
  }, []);

  // 마우스/터치 fallback 입력
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;

    const getPos = (clientX, clientY) => {
      const rect = c.getBoundingClientRect();
      return {
        x: clamp(clientX - rect.left, 0, rect.width),
        y: clamp(clientY - rect.top, 0, rect.height),
      };
    };

    const onMouseDown = (e) => {
      if (pointerRef.current.source === "agent") return;

      const p = getPos(e.clientX, e.clientY);
      pointerRef.current = {
        ...pointerRef.current,
        ...p,
        x: p.x,
        y: p.y,
        tx: p.x,
        ty: p.y,
        down: true,
        tracking: true,
        source: "mouse",
      };
      pushSampleRef.current?.(p.x, p.y);
    };

    const onMouseMove = (e) => {
      if (pointerRef.current.source === "agent") return;

      const p = getPos(e.clientX, e.clientY);

      // ✅ 위치는 항상 갱신(버벅 느낌 줄임)
      pointerRef.current = {
        ...pointerRef.current,
        ...p,
        tx: p.x,
        ty: p.y,
        tracking: true,
        source: "mouse",
      };

      // ✅ 샘플은 드래그(다운) 중일 때만
      if (pointerRef.current.down) {
        pushSampleRef.current?.(p.x, p.y);
      }
    };

    const onMouseUp = () => {
      if (pointerRef.current.source === "agent") return;
      pointerRef.current.down = false;
      // tracking 유지
    };

    const onTouchStart = (e) => {
      if (pointerRef.current.source === "agent") return;
      const t = e.touches[0];
      if (!t) return;

      const p = getPos(t.clientX, t.clientY);
      pointerRef.current = {
        ...pointerRef.current,
        ...p,
        x: p.x,
        y: p.y,
        tx: p.x,
        ty: p.y,
        down: true,
        tracking: true,
        source: "mouse",
      };
      pushSampleRef.current?.(p.x, p.y);
    };

    const onTouchMove = (e) => {
      if (pointerRef.current.source === "agent") return;
      const t = e.touches[0];
      if (!t) return;

      const p = getPos(t.clientX, t.clientY);
      pointerRef.current = {
        ...pointerRef.current,
        ...p,
        tx: p.x,
        ty: p.y,
        tracking: true,
        source: "mouse",
      };
      if (pointerRef.current.down) {
        pushSampleRef.current?.(p.x, p.y);
      }
    };

    const onTouchEnd = () => {
      if (pointerRef.current.source === "agent") return;
      pointerRef.current.down = false;
      // tracking 유지
    };

    c.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    c.addEventListener("touchstart", onTouchStart, { passive: true });
    c.addEventListener("touchmove", onTouchMove, { passive: true });
    c.addEventListener("touchend", onTouchEnd);

    return () => {
      c.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);

      c.removeEventListener("touchstart", onTouchStart);
      c.removeEventListener("touchmove", onTouchMove);
      c.removeEventListener("touchend", onTouchEnd);
    };
  }, []);

  // draw loop (의존성 최소화: 한번만 실행)
  useEffect(() => {
    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);

    const c = canvasRef.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;

    const lastTRef = { t: performance.now() };

    const loop = () => {
      const w = viewRef.current.w;
      const h = viewRef.current.h;

      // 아직 레이아웃 안 잡혔으면 다음 프레임
      if (!w || !h) {
        rafRef.current = requestAnimationFrame(loop);
        return;
      }

      // dt
      const tNow = performance.now();
      const dt = (tNow - lastTRef.t) / 1000;
      lastTRef.t = tNow;

      // 1) agent status 좌표가 있으면 target(tx,ty) 갱신
      const st = statusRef.current;
      const agentPtr = readPointerFromStatus(st, { width: w, height: h });

      if (agentPtr) {
        const p = pointerRef.current;

        // ✅ 속도(vx,vy) 추정 (px/ms)
        const tms = tNow;
        if (p._lastAt != null) {
          const dms = Math.max(1, tms - p._lastAt);
          const instVx = (agentPtr.x - p._lastAx) / dms;
          const instVy = (agentPtr.y - p._lastAy) / dms;

          // 튐 완화 필터
          p.vx = p.vx * 0.7 + instVx * 0.3;
          p.vy = p.vy * 0.7 + instVy * 0.3;
        }
        p._lastAt = tms;
        p._lastAx = agentPtr.x;
        p._lastAy = agentPtr.y;

        p.source = "agent";
        p.tracking = agentPtr.tracking;
        p.down = false;
        p.tx = agentPtr.x;
        p.ty = agentPtr.y;
      } else {
        if (pointerRef.current.source !== "mouse") {
          pointerRef.current.source = "mouse";
        }
      }

      // 2) 스무딩/예측: 더 빠르고 부드럽게
      {
        const p = pointerRef.current;

        // 1~2프레임 앞 예측(레이턴시 체감 감소)
        const predMs = 60; // 40~90 사이 취향
        const ptx = p.tx + (p.vx || 0) * predMs;
        const pty = p.ty + (p.vy || 0) * predMs;

        // Adaptive follow: 멀수록 더 빨리
        const err = Math.hypot(ptx - p.x, pty - p.y);

        // ✅ 반응 속도 (기본 40 근처, 멀면 더 빠르게)
        const lambda = clamp(38 + err * 0.08, 38, 95);
        const k = 1 - Math.exp(-dt * lambda);

        // 끊김 복구/초기 스냅
        if (err > 260) {
          p.x = ptx;
          p.y = pty;
        } else {
          p.x += (ptx - p.x) * k;
          p.y += (pty - p.y) * k;
        }
      }

      // 3) HUD 업데이트(10fps)
      {
        const nextSource = pointerRef.current.source;
        const nextTracking = !!pointerRef.current.tracking;

        const ht = hudRef.current;
        const now = performance.now();

        const changed = ht.source !== nextSource || ht.tracking !== nextTracking;
        const timeOk = now - ht.lastT > 100;

        if (changed && timeOk) {
          ht.source = nextSource;
          ht.tracking = nextTracking;
          ht.lastT = now;
          setSource(nextSource);
          setTrackingUI(nextTracking);
        }
      }

      // 4) agent tracking일 때는 샘플을 "스무딩된 x/y"로 쌓기
      if (pointerRef.current.source === "agent" && pointerRef.current.tracking) {
        pushSampleRef.current?.(pointerRef.current.x, pointerRef.current.y);
      }

      // 5) 스와이프 판정
      const fired = pointerRef.current.tracking ? consumeRef.current?.() : false;
      if (fired) setSwipeCount((v) => v + 1);

      // 6) 노트 이동
      const note = noteRef.current;
      if (note.alive) {
        note.y += note.speed * dt;
        if (note.y > h + 120) note.y = -120;
      }

      // 7) 렌더
      ctx.clearRect(0, 0, w, h);

      // 배경
      const grad = ctx.createLinearGradient(0, 0, 0, h);
      grad.addColorStop(0, "#060a14");
      grad.addColorStop(1, "#0b1020");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);

      // 그리드(대각/수평)
      const tt = performance.now() * 0.001;
      ctx.save();
      ctx.globalAlpha = 0.18;
      ctx.strokeStyle = "#8aa0c8";
      ctx.lineWidth = 1;

      const spacing = 28;
      const drift = (tt * 120) % spacing;

      for (let y = -spacing; y < h + spacing; y += spacing) {
        const yy = y + drift;
        ctx.beginPath();
        ctx.moveTo(0, yy);
        ctx.lineTo(w, yy);
        ctx.stroke();
      }

      ctx.globalAlpha = 0.10;
      for (let x = -w; x < w * 2; x += spacing * 2) {
        const xx = x + drift * 2;
        ctx.beginPath();
        ctx.moveTo(xx, 0);
        ctx.lineTo(xx - w * 0.6, h);
        ctx.stroke();
      }
      ctx.restore();

      // 스캔라인
      ctx.save();
      ctx.globalAlpha = 0.08;
      ctx.fillStyle = "#ffffff";
      const scanY = (tt * 220) % h;
      ctx.fillRect(0, scanY, w, 2);
      ctx.restore();

      // 노트(네온 네모)
      if (note.alive) {
        const size = 62;
        const x = w * 0.5;
        const y = note.y;

        ctx.save();
        ctx.globalAlpha = 0.28;
        ctx.fillStyle = "#38bdf8";
        ctx.fillRect(x - size / 2 - 10, y - size / 2 - 10, size + 20, size + 20);
        ctx.restore();

        ctx.fillStyle = "#7dd3fc";
        ctx.fillRect(x - size / 2, y - size / 2, size, size);

        ctx.globalAlpha = 0.9;
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.strokeRect(x - size / 2, y - size / 2, size, size);
        ctx.globalAlpha = 1;
      }

      // Hit line
      const hitY = Math.round(h * 0.62);

      ctx.save();
      ctx.globalAlpha = fired ? 0.35 : 0.22;
      ctx.strokeStyle = "#7dd3fc";
      ctx.lineWidth = fired ? 18 : 12;
      ctx.beginPath();
      ctx.moveTo(24, hitY);
      ctx.lineTo(w - 24, hitY);
      ctx.stroke();
      ctx.restore();

      ctx.save();
      ctx.globalAlpha = 0.95;
      ctx.strokeStyle = fired ? "#ffffff" : "#7dd3fc";
      ctx.lineWidth = fired ? 6 : 4;
      ctx.beginPath();
      ctx.moveTo(24, hitY);
      ctx.lineTo(w - 24, hitY);
      ctx.stroke();
      ctx.restore();

      // 판정
      if (note.alive && fired) {
        const dist = Math.abs(note.y - hitY);
        const PERFECT = 18;
        const GOOD = 40;

        let text = "MISS";
        if (dist <= PERFECT) text = "PERFECT";
        else if (dist <= GOOD) text = "GOOD";

        const j = { text, t: performance.now() };
        judgeRef.current = j;
        setJudge(j);

        note.y = -120;
      }

      // Pointer
      const p = pointerRef.current;
      if (p.tracking) {
        ctx.fillStyle = "#dfe7ff";
        ctx.beginPath();
        ctx.arc(p.x, p.y, 18, 0, Math.PI * 2);
        ctx.fill();
      }

      // 판정 텍스트(0.6초)
      const jj = judgeRef.current ?? judge;
      if (jj && performance.now() - jj.t < 600) {
        ctx.globalAlpha = 0.95;
        ctx.fillStyle = "#ffffff";
        ctx.font = "700 36px system-ui";
        ctx.textAlign = "center";
        ctx.fillText(jj.text, w / 2, hitY - 40);
        ctx.globalAlpha = 1;
      }

      // Flash
      if (fired) {
        ctx.globalAlpha = 0.2;
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, hitY - 20, w, 40);
        ctx.globalAlpha = 1;
      }

      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);

    return () => {
      window.removeEventListener("resize", resizeCanvas);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const overlay = !connected
    ? "백엔드 연결 OFF"
    : source === "agent" && !trackingUI
    ? "손 트래킹 없음 (손을 카메라 중앙에)"
    : null;

  return (
    <div className="w-full h-full bg-slate-950 text-slate-100 relative overflow-hidden">
      <div ref={hostRef} className="absolute inset-0">
        <canvas ref={canvasRef} className="w-full h-full touch-none" />
      </div>

      {/* HUD */}
      <div className="absolute top-3 left-3 right-3 flex items-start justify-between gap-3 pointer-events-none">
        <div className="bg-black/50 rounded-xl px-3 py-2 text-sm leading-6">
          <div className="font-semibold">RHYTHM RUSH</div>
          <div>source: {source}</div>
          <div>tracking: {String(trackingUI)}</div>
          <div>swipeCount: {swipeCount}</div>
        </div>

        <div className="bg-black/50 rounded-xl px-3 py-2 text-sm leading-6 text-right">
          <div>dy: {debug.dy}px</div>
          <div>vy: {debug.vy}px/s</div>
          <div>dx: {debug.dx}px</div>
          <div>samples: {debug.samples}</div>
          <div>cooldown: {debug.cooldownLeft}ms</div>
          <div className={debug.fired ? "font-bold" : ""}>fired: {String(debug.fired)}</div>
        </div>
      </div>

      {/* Overlay */}
      {overlay && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="bg-black/60 border border-white/10 rounded-2xl px-5 py-4 text-sm text-slate-100 backdrop-blur">
            {overlay}
          </div>
        </div>
      )}

      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-black/50 rounded-full px-4 py-2 text-sm pointer-events-none">
        {source === "agent"
          ? "에이전트 좌표로 스와이프 판정 중"
          : "status에 좌표가 없어서 마우스/터치 테스트 모드"}
      </div>
    </div>
  );
}
