import React, { Suspense, useEffect, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF, PerspectiveCamera, Environment, Preload } from "@react-three/drei";
import { io } from "socket.io-client";
import * as THREE from "three";

/* =======================
   GLB 경로
======================= */
const MODELS_LIST = {
  base: "/models/enemy_boxer.glb",
  jab_l: "/models/Punch_left.glb",
  jab_r: "/models/Punch_right.glb",
  straight: "/models/Straight.glb",
  hook: "/models/Hook.glb",
  uppercut: "/models/Uppercut.glb",
  hit1: "/models/Hit1.glb",
  hit2: "/models/Hit2.glb",
};

Object.values(MODELS_LIST).forEach((url) => useGLTF.preload(url));

/* =======================
   HP 유틸
======================= */
const getHpStage = (hp) => {
  if (hp >= 71) return 0;
  if (hp >= 41) return 1;
  if (hp >= 11) return 2;
  return 3;
};

const getHpColor = (hp) => {
  const stage = getHpStage(hp);
  if (stage === 0) return "#00ff5a";
  if (stage === 1) return "#ffe600";
  if (stage === 2) return "#ff8c00";
  return "#ff2a2a";
};

const getContinuousVignette = (hp) => {
  if (hp >= 70) return 0;

  // 70 -> 0, 10 -> 0.75
  const t = THREE.MathUtils.clamp((70 - hp) / 60, 0, 1);
  return t * 0.75;
};

/* =======================
   3D 씬
======================= */
function BoxerScene({ activeKey, headX, onReturnToBase, isHitPlayingRef, animMetaRef }) {
  const m = {
    base: useGLTF(MODELS_LIST.base),
    jab_l: useGLTF(MODELS_LIST.jab_l),
    jab_r: useGLTF(MODELS_LIST.jab_r),
    straight: useGLTF(MODELS_LIST.straight),
    hook: useGLTF(MODELS_LIST.hook),
    uppercut: useGLTF(MODELS_LIST.uppercut),
    hit1: useGLTF(MODELS_LIST.hit1),
    hit2: useGLTF(MODELS_LIST.hit2),
  };

  const mixerRef = useRef();
  const actionsRef = useRef({});

  useEffect(() => {
    if (!m.base?.scene) return;

    mixerRef.current = new THREE.AnimationMixer(m.base.scene);

    const handleFinished = () => {
      onReturnToBase();
      if (isHitPlayingRef.current) isHitPlayingRef.current = false;
    };

    mixerRef.current.addEventListener("finished", handleFinished);

    Object.keys(m).forEach((key) => {
      if (m[key]?.animations?.[0]) {
        const clip = m[key].animations[0];
        const action = mixerRef.current.clipAction(clip);

        const duration = clip.duration; // 🔥 실제 GLB 애니 길이 (초)

        if (key !== "base") {
          action.setLoop(THREE.LoopOnce);
          action.clampWhenFinished = true;
        }

        actionsRef.current[key] = action;

        // 🔥 GamePage에서 쓰도록 저장
        if (animMetaRef?.current) {
          animMetaRef.current[key] = {
            durationSec: duration,
          };
        }

        console.log(`[ANIM] ${key} duration = ${duration.toFixed(3)}s`);
      }
    });


    actionsRef.current.base?.play();

    return () => {
      mixerRef.current?.removeEventListener("finished", handleFinished);
    };
  }, [m.base]);

  useEffect(() => {
    Object.keys(actionsRef.current).forEach((key) => {
      if (key === activeKey) {
        actionsRef.current[key].reset().fadeIn(0.05).play();
      } else {
        actionsRef.current[key]?.fadeOut(0.1);
      }
    });
  }, [activeKey]);

  useFrame((_, delta) => {
    mixerRef.current?.update(delta);

    if (m.base?.scene) {
      const targetX = isFinite(headX) ? -headX * 1.8 : 0;
      m.base.scene.position.x = THREE.MathUtils.lerp(m.base.scene.position.x, targetX, 0.15);
      m.base.scene.rotation.y = THREE.MathUtils.lerp(
        m.base.scene.rotation.y,
        isFinite(headX) ? -headX * 0.2 : 0,
        0.1
      );
    }
  });

  if (!m.base?.scene) return null;
  return <primitive object={m.base.scene} scale={3.8} position={[0, -2.4, -1.8]} />;
}

/* =======================
   메인 게임
======================= */
export default function GamePage() {
  const [enemyHp, setEnemyHp] = useState(100);
  const [playerHp, setPlayerHp] = useState(100);
  const [attackGauge, setAttackGauge] = useState(0);
  const [gameState, setGameState] = useState("IDLE"); // IDLE(시작 전) | DEFENSE | ATTACK_CHANCE | END
  const [activeKey, setActiveKey] = useState("base");
  const [gameMsg, setGameMsg] = useState("");
  const [motion, setMotion] = useState({ x: 0, z: 0, dir: "none" });

  const socketRef = useRef(null);
  const gameStateRef = useRef(gameState);
  const motionRef = useRef(motion);
  const lastMotionAtRef = useRef(0);

  const enemyAttackPendingRef = useRef(false);
  const judgeTimeoutRef = useRef(null);
  const isHitAnimationPlayingRef = useRef(false);
  const enemyAnimMetaRef = useRef({});
  const currentEnemyAttackRef = useRef(null);

  const clearTimers = () => {
    if (judgeTimeoutRef.current) {
      clearTimeout(judgeTimeoutRef.current);
      judgeTimeoutRef.current = null;
    }
    if (timerReqRef.current) {
      cancelAnimationFrame(timerReqRef.current);
      timerReqRef.current = null;
    }
    enemyAttackPendingRef.current = false;
  };

  const resetGame = (nextState = "DEFENSE") => {
    clearTimers();
    setEnemyHp(100);
    setPlayerHp(100);
    setAttackGauge(0);
    setActiveKey("base");
    setGameMsg("");
    setChanceTimer(2.5);
    lastWeavingPosRef.current = { x: null, z: null };
    isHitAnimationPlayingRef.current = false;
    setGameState(nextState);
  };

  const startGame = () => resetGame("DEFENSE");
  const restartGame = () => resetGame("DEFENSE");

  const lastWeavingPosRef = useRef({ x: null, z: null }); // 👈 위빙 꼼수 방지

  const [chanceTimer, setChanceTimer] = useState(2.5);
  const chanceStartTimeRef = useRef(0);
  const timerReqRef = useRef(null);

  const enemyHitRatio = {
    jab_l: 0.48,
    jab_r: 0.48,
    straight: 0.80,   // 🔥 팔 거의 다 뻗을 때
    hook: 0.72,
    uppercut: 0.65
  };
  const enemyDamage = {
  jab_l: 10,
  jab_r: 10,
  straight: 15,
  hook: 20,
  uppercut: 30,
  };

  const isGameOver = playerHp <= 0;
  const isWin = enemyHp <= 0;


  // 게임 종료 시 상태를 END로 고정 + 타이머 정리 (버튼으로 재시작 가능)
  useEffect(() => {
    if (playerHp <= 0 || enemyHp <= 0) {
      clearTimers();
      setGameState("END");
    }
  }, [playerHp, enemyHp]);

  /* ===================
     HP 단계 연출
  =================== */
  const prevPlayerStageRef = useRef(getHpStage(playerHp));
  const prevEnemyStageRef = useRef(getHpStage(enemyHp));
  const [vignette, setVignette] = useState(0);
  const [shake, setShake] = useState(0);

  const triggerHpStageEffect = (stage) => {
    let s = 0;

    if (stage === 1) s = 4;   // 70 진입
    if (stage === 2) s = 7;   // 40 진입
    if (stage === 3) s = 12;  // 10 진입

    if (s > 0) {
      setShake(s);
      setTimeout(() => setShake(0), 400);
    }
  };


  useEffect(() => {
    const cur = getHpStage(playerHp);
    if (cur !== prevPlayerStageRef.current) {
      triggerHpStageEffect(cur);
      prevPlayerStageRef.current = cur;
    }
  }, [playerHp]);

  useEffect(() => {
    setVignette(getContinuousVignette(playerHp));
  }, [playerHp]);

  // useEffect(() => {
  //   const cur = getHpStage(enemyHp);
  //   if (cur !== prevEnemyStageRef.current) {
  //     triggerHpStageEffect(cur);
  //     prevEnemyStageRef.current = cur;
  //   }
  // }, [enemyHp]);

  useEffect(() => { gameStateRef.current = gameState; }, [gameState]);


  // 키보드 단축키: Enter/Space로 시작, R로 재시작
  useEffect(() => {
    const onKey = (e) => {
      const key = (e.key || "").toLowerCase();
      if (gameStateRef.current === "IDLE" && (key === "enter" || key === " " || key === "spacebar")) {
        startGame();
      }
      if (gameStateRef.current === "END" && (key === "enter" || key === "r" || key === " ")) {
        restartGame();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /* ================= Socket ================= */
  useEffect(() => {
    socketRef.current = io("http://127.0.0.1:65432");

    const onMotion = (data) => {
      const ts = Date.now();
      if (ts - lastMotionAtRef.current < 40) return;
      lastMotionAtRef.current = ts;

      motionRef.current = { ...data, t: ts };
      setMotion(data);

      if (gameStateRef.current === "ATTACK_CHANCE") {
        const rawDir = (data.dir || "").toLowerCase();
        if (rawDir.includes("jab") || rawDir.includes("straight") || rawDir.includes("hook") || rawDir.includes("upper")) {
          const mapped =
            rawDir.includes("jab") ? "jab" :
            rawDir.includes("straight") ? "straight" :
            rawDir.includes("hook") ? "hook" : "uppercut";
          handlePlayerAttack(mapped);
          setGameState("DEFENSE");
        }
      }
    };

    socketRef.current.on("motion", onMotion);
    return () => socketRef.current.disconnect();
  }, []);

  /* ================= Chance Timer ================= */
  useEffect(() => {
    if (gameState === "ATTACK_CHANCE") {
      chanceStartTimeRef.current = Date.now();
      const updateTimer = () => {
        const elapsed = (Date.now() - chanceStartTimeRef.current) / 1000;
        const remaining = Math.max(0, 2.5 - elapsed);
        setChanceTimer(remaining);
        if (remaining > 0) timerReqRef.current = requestAnimationFrame(updateTimer);
        else setGameState("DEFENSE");
      };
      timerReqRef.current = requestAnimationFrame(updateTimer);
    } else {
      if (timerReqRef.current) cancelAnimationFrame(timerReqRef.current);
      setChanceTimer(2.5);
    }
  }, [gameState]);

  const showMessage = (msg, duration = 600) => {
    setGameMsg(msg);
    setTimeout(() => setGameMsg(""), duration);
  };

  /* ================= 플레이어 공격 ================= */
  const handlePlayerAttack = (type) => {
    const damages = { jab: 10, straight: 15, hook: 20, uppercut: 30 };
    setEnemyHp((prev) => Math.max(0, prev - (damages[type] || 20)));
    setAttackGauge(0);
    showMessage(`${type.toUpperCase()}!!`, 400);

    const hitKey = Math.random() < 0.5 ? "hit1" : "hit2";
    isHitAnimationPlayingRef.current = true;
    setActiveKey(hitKey);
  };

  /* ================= 적 공격 판정 ================= */
  const handleEnemyAttackJudge = () => {
    if (gameStateRef.current !== "DEFENSE" || isGameOver || isWin) return;

    const snapshot = motionRef.current;
    const now = Date.now();
    const isFresh = now - lastMotionAtRef.current < 180;

    let isDodged = false;
    let isGuarded = false;

    if (isFresh) {
      if (snapshot.dir === "weaving") {
        // 같은 위치에서 반복 위빙이면 회피 무효
        if (
          lastWeavingPosRef.current.x !== snapshot.x ||
          lastWeavingPosRef.current.z !== snapshot.z
        ) {
          isDodged = true;
          lastWeavingPosRef.current = { x: snapshot.x, z: snapshot.z };
        }
      } else if (snapshot.dir === "guard") {
        isGuarded = true;
      } else {
        lastWeavingPosRef.current = { x: null, z: null };
      }
    }

    if (isDodged || isGuarded) {
      setAttackGauge((prev) => {
        const next = Math.min(100, prev + (isDodged ? 40 : 20));
        if (next >= 100) {
          setGameState("ATTACK_CHANCE");
          showMessage("🔥 CHANCE! 🔥", 800);
          socketRef.current.emit("chance", { chance_trigger: true });
        } else {
          showMessage(isDodged ? "💨 DODGE!" : "🛡️ GUARD!");
        }
        return next;
      });
    } else {
      const atk = currentEnemyAttackRef.current;
      const dmg = enemyDamage[atk] || 15; // ref 기준
      setPlayerHp((prev) => Math.max(0, prev - dmg));
      showMessage(`💥 HIT! (-${dmg})`);

    }

    currentEnemyAttackRef.current = null;
    enemyAttackPendingRef.current = false;
  };

  /* ================= 랜덤 적 공격 ================= */
  useEffect(() => {
    if (gameState !== "DEFENSE" || activeKey !== "base" || isHitAnimationPlayingRef.current || isGameOver || isWin) return;

    const timer = setTimeout(() => {
      if (enemyAttackPendingRef.current) return;

      const attacks = ["jab_l", "jab_r", "straight", "hook", "uppercut"];
      const nextAttack = attacks[Math.floor(Math.random() * attacks.length)];

      currentEnemyAttackRef.current = nextAttack;   // ⭐ 이 줄 추가
      setActiveKey(nextAttack);
      enemyAttackPendingRef.current = true;

      const meta = enemyAnimMetaRef.current[nextAttack];
      const durationMs = meta ? meta.durationSec * 1000 : 800;

      const ratio = enemyHitRatio[nextAttack] ?? 0.55;
      const hitDelay = durationMs * ratio;

      judgeTimeoutRef.current = setTimeout(handleEnemyAttackJudge, hitDelay);
    }, 1500);

    return () => clearTimeout(timer);
  }, [activeKey, gameState, isGameOver, isWin]);

  const shakeStyle = shake > 0 ? { animation: `shake 0.12s infinite` } : {};

  /* =======================
       렌더
  ======================= */
  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        position: "relative",
        overflow: "hidden",
        background: `url(/models/Background.png) center/cover no-repeat`,
        boxShadow: vignette ? `inset 0 0 ${vignette * 300}px rgba(0,0,0,0.85)` : "none",
        ...shakeStyle,
      }}
    >
      <style>
        {`
        @keyframes shake {
          0% { transform: translate(0px, 0px); }
          25% { transform: translate(3px, -3px); }
          50% { transform: translate(-3px, 3px); }
          75% { transform: translate(3px, 3px); }
          100% { transform: translate(0px, 0px); }
        }
        `}
      </style>

      {/* UI */}
      <div style={{ position: "absolute", top: 20, left: 0, right: 0, zIndex: 10, pointerEvents: "none" }}>
        {/* PLAYER */}
        <div style={{ position: "absolute", left: 30, top: 0, width: 360 }}>
          <div style={{ marginBottom: 6, fontWeight: 900, color: "#4da6ff", textAlign: "left" }}>PLAYER</div>
          <div style={{ width: "100%", height: 16, background: "#111", borderRadius: 10, border: "2px solid #4da6ff" }}>
            <div style={{
              width: `${playerHp}%`,
              height: "100%",
              background: getHpColor(playerHp),
              boxShadow: `0 0 10px ${getHpColor(playerHp)}`,
              borderRadius: 10,
              transition: "width 0.6s ease"
            }} />
          </div>
        </div>

        {/* ENEMY */}
        <div style={{ position: "absolute", right: 30, top: 0, width: 360 }}>
          <div style={{ marginBottom: 6, fontWeight: 900, color: "#ff4d4d", textAlign: "right" }}>ENEMY</div>
          <div style={{ width: "100%", height: 16, background: "#111", borderRadius: 10, border: "2px solid #ff4d4d" }}>
            <div style={{
              width: `${enemyHp}%`,
              height: "100%",
              background: getHpColor(enemyHp),
              boxShadow: `0 0 10px ${getHpColor(enemyHp)}`,
              borderRadius: 10,
              transition: "width 0.6s ease",
              marginLeft: "auto"
            }} />
          </div>
        </div>

        {/* Gauge */}
        <div style={{ width: 420, height: 18, margin: "50px auto 0", background: "#000", borderRadius: 12 }}>
          <div style={{
            width: `${attackGauge}%`,
            height: "100%",
            background: "linear-gradient(90deg,#00ffff,#0077ff)",
            boxShadow: "0 0 15px #00ffff",
            borderRadius: 12,
            transition: "width 0.3s ease",
          }} />
        </div>

        {/* Chance Timer */}
        {gameState === "ATTACK_CHANCE" && (
          <div style={{ width: 260, height: 8, margin: "8px auto 0", background: "#222", borderRadius: 6 }}>
            <div style={{
              width: `${(chanceTimer / 2.5) * 100}%`,
              height: "100%",
              background: chanceTimer < 0.4 ? "#ff0000" : "#00ff00",
              borderRadius: 6,
            }} />
          </div>
        )}

        {gameMsg && (
          <div style={{ marginTop: 30, textAlign: "center" }}>
            <h1 style={{ fontSize: 72, fontWeight: 900, textShadow: "4px 4px 12px #000" }}>{gameMsg}</h1>
          </div>
        )}
      </div>


{/* START (IDLE) */}
{gameState === "IDLE" && (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: "rgba(0,0,0,0.82)",
      zIndex: 40,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 18,
      color: "#fff",
      textAlign: "center",
    }}
  >
    <div style={{ fontSize: 84, fontWeight: 900, letterSpacing: 1, textShadow: "4px 4px 14px #000" }}>
      READY?
    </div>
    <div style={{ opacity: 0.85, fontSize: 18, lineHeight: 1.6, maxWidth: 560 }}>
      방어(WEAVING/ GUARD)로 게이지를 채우고, CHANCE가 뜨면 공격 모션으로 타격하세요.
    </div>
    <button
      type="button"
      onClick={startGame}
      style={{
        pointerEvents: "auto",
        padding: "14px 26px",
        fontSize: 20,
        fontWeight: 900,
        borderRadius: 14,
        border: "2px solid rgba(255,255,255,0.25)",
        background: "linear-gradient(90deg, rgba(0,255,255,0.28), rgba(0,119,255,0.22))",
        boxShadow: "0 0 18px rgba(0,255,255,0.35)",
        cursor: "pointer",
      }}
    >
      START
    </button>
    <div style={{ opacity: 0.65, fontSize: 13 }}>
      (Enter/Space로도 시작 가능)
    </div>
  </div>
)}

{/* END (WIN / GAME OVER) */}
{gameState === "END" && (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: "rgba(0,0,0,0.85)",
      zIndex: 40,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 18,
      textAlign: "center",
    }}
  >
    <div
      style={{
        fontSize: 110,
        fontWeight: 900,
        color: isWin ? "#00ff5a" : "#ff0000",
        textShadow: "4px 4px 14px #000",
      }}
    >
      {isWin ? "YOU WIN!" : "GAME OVER"}
    </div>

    <button
      type="button"
      onClick={restartGame}
      style={{
        pointerEvents: "auto",
        padding: "14px 26px",
        fontSize: 20,
        fontWeight: 900,
        borderRadius: 14,
        border: "2px solid rgba(255,255,255,0.25)",
        background: "linear-gradient(90deg, rgba(255,255,255,0.18), rgba(255,255,255,0.08))",
        boxShadow: "0 0 16px rgba(255,255,255,0.18)",
        cursor: "pointer",
        color: "#fff",
      }}
    >
      RESTART
    </button>

    <div style={{ opacity: 0.65, color: "#fff", fontSize: 13 }}>
      (R / Enter로도 재시작 가능)
    </div>
  </div>
)}

      {/* 3D */}
      <Canvas>
        <Suspense fallback={null}>
          <PerspectiveCamera makeDefault position={[0, 1.5, 4.5]} />
          <Environment preset="city" />
          <BoxerScene
            activeKey={activeKey}
            headX={motion.x}
            onReturnToBase={() => setActiveKey("base")}
            isHitPlayingRef={isHitAnimationPlayingRef}
            animMetaRef={enemyAnimMetaRef}
          />
          <Preload all />
        </Suspense>
      </Canvas>
    </div>
  );
}
