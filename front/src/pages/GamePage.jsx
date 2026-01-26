import React, { Suspense, useEffect, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF, PerspectiveCamera, Environment, Preload } from "@react-three/drei";
import { io } from "socket.io-client";
import * as THREE from "three";

const MODELS_LIST = {
  base: "/models/enemy_boxer.glb",
  jab_l: "/models/Punch_left.glb",
  jab_r: "/models/Punch_right.glb",
  straight: "/models/Straight.glb",
  hook: "/models/Hook.glb",
  uppercut: "/models/Uppercut.glb",
};

function BoxerScene({ activeKey, headX, onReturnToBase }) {
  const m = {
    base: useGLTF(MODELS_LIST.base),
    jab_l: useGLTF(MODELS_LIST.jab_l),
    jab_r: useGLTF(MODELS_LIST.jab_r),
    straight: useGLTF(MODELS_LIST.straight),
    hook: useGLTF(MODELS_LIST.hook),
    uppercut: useGLTF(MODELS_LIST.uppercut),
  };

  const mixerRef = useRef();
  const actionsRef = useRef({});
  const actionProcessed = useRef(false);

  useEffect(() => {
    if (!m.base?.scene) {
      console.warn("Base model not loaded:", MODELS_LIST.base);
      return;
    }
    mixerRef.current = new THREE.AnimationMixer(m.base.scene);

    const handleFinished = () => {
      actionProcessed.current = false;
      onReturnToBase();
    };
    mixerRef.current.addEventListener("finished", handleFinished);

    Object.keys(m).forEach((key) => {
      if (m[key]?.animations?.[0]) {
        const action = mixerRef.current.clipAction(m[key].animations[0]);
        if (key !== "base") {
          action.setLoop(THREE.LoopOnce);
          action.clampWhenFinished = true;
        }
        actionsRef.current[key] = action;
      }
    });

    actionsRef.current.base?.play();
    console.log("Boxer animations loaded");
    return () => mixerRef.current?.removeEventListener("finished", handleFinished);
  }, [m.base]);

  useEffect(() => {
    Object.keys(actionsRef.current).forEach((key) => {
      if (key === activeKey) actionsRef.current[key].reset().fadeIn(0.05).play();
      else actionsRef.current[key]?.fadeOut(0.1);
    });
  }, [activeKey]);

  useFrame((state, delta) => {
    mixerRef.current?.update(delta);
    if (m.base?.scene) m.base.scene.position.x = THREE.MathUtils.lerp(m.base.scene.position.x, -headX * 2.5, 0.2);
  });

  if (!m.base?.scene) {
    return <mesh position={[0, 0, 0]}><boxGeometry args={[1, 1, 1]} /><meshBasicMaterial color="red" /></mesh>;
  }

  return <primitive object={m.base.scene} scale={3.8} position={[0, -2.4, -1.8]} />;
}

export default function GamePage() {
  const [enemyHp, setEnemyHp] = useState(100);
  const [playerHp, setPlayerHp] = useState(100);
  const [attackGauge, setAttackGauge] = useState(0);
  const [gameState, setGameState] = useState("DEFENSE");
  const [activeKey, setActiveKey] = useState("base");
  const [gameMsg, setGameMsg] = useState("Start");
  const [motion, setMotion] = useState({ x: 0, z: 0, dir: "none" });
  const msgTimeoutRef = useRef(null);
  const enemyAttackPendingRef = useRef(false);
  const judgeTimeoutRef = useRef(null);
  const lastChanceAttackRef = useRef("none");
  const lastMotionAtRef = useRef(0);
  const motionRef = useRef({ x: 0, z: 0, dir: "none" });

  const attackTypes = new Set(["jab", "straight", "hook", "uppercut"]);
  const enemyHitDelayMs = {
    jab_l: 250,
    jab_r: 250,
    straight: 380,
    hook: 520,
    uppercut: 520,
  };

  const socketRef = useRef();

  useEffect(() => {
    socketRef.current = io("http://127.0.0.1:65432");
    socketRef.current.on("motion", (data) => {
      const now = Date.now();
      const ts = typeof data.t === "number" ? data.t * 1000 : now;
      lastMotionAtRef.current = ts;
      motionRef.current = { ...data, t: ts };
      setMotion(data);
    });
    return () => socketRef.current.disconnect();
  }, []);

  useEffect(() => {
    if (socketRef.current) socketRef.current.emit("chance", { active: gameState === "ATTACK_CHANCE" });
  }, [gameState]);

  // 찬스타임 공격
  useEffect(() => {
    if (gameState === "ATTACK_CHANCE") lastChanceAttackRef.current = "none";
  }, [gameState]);

  useEffect(() => {
    if (gameState === "ATTACK_CHANCE" && attackTypes.has(motion.dir) && motion.dir !== lastChanceAttackRef.current) {
      lastChanceAttackRef.current = motion.dir;
      handlePlayerAttack(motion.dir);
    }
  }, [motion]);

  const showMessage = (msg, duration = 600) => {
    setGameMsg(msg);
    if (msgTimeoutRef.current) clearTimeout(msgTimeoutRef.current);
    msgTimeoutRef.current = setTimeout(() => setGameMsg(""), duration);
  };

  const handlePlayerAttack = (type) => {
    const damages = { jab: 15, straight: 25, hook: 70, uppercut: 100 };
    setEnemyHp((prev) => Math.max(0, prev - (damages[type] || 20)));
    setAttackGauge(0);
    setGameState("DEFENSE");
    setActiveKey("base");
    showMessage(`${type.toUpperCase()}!!`, 400);
  };

  const handleEnemyAttackJudge = () => {
    if (gameState !== "DEFENSE") return;

    const now = Date.now();
    const snapshot = motionRef.current;
    const isFresh = now - lastMotionAtRef.current < 180;
    const isDodged = isFresh && snapshot.dir === "weaving";
    const isGuarded = isFresh && snapshot.dir === "guard";

    if (isDodged || isGuarded) {
      setAttackGauge((prev) => {
        const next = Math.min(100, prev + (isDodged ? 40 : 20));
        if (next >= 100) {
          setGameState("ATTACK_CHANCE");
          showMessage("🔥 CHANCE! 🔥", 1000);
        } else {
          showMessage(isDodged ? "💨 DODGE!" : "🛡️ GUARD!");
        }
        return next;
      });
    } else {
      setPlayerHp((prev) => Math.max(0, prev - 15));
      showMessage("💥 HIT!");
    }
    enemyAttackPendingRef.current = false;
  };

  // 랜덤 공격 모션 재생
  useEffect(() => {
    if (gameState !== "DEFENSE" || activeKey !== "base") return;
    const timer = setTimeout(() => {
      if (enemyAttackPendingRef.current) return;
      const attacks = ["jab_l", "jab_r", "straight", "hook", "uppercut"];
      const nextAttack = attacks[Math.floor(Math.random() * attacks.length)];
      setActiveKey(nextAttack);
      enemyAttackPendingRef.current = true;
      if (judgeTimeoutRef.current) clearTimeout(judgeTimeoutRef.current);
      const hitDelay = enemyHitDelayMs[nextAttack] ?? 350;
      judgeTimeoutRef.current = setTimeout(handleEnemyAttackJudge, hitDelay);
    }, 2000);
    return () => clearTimeout(timer);
  }, [activeKey, gameState]);

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative", overflow: "hidden", backgroundColor: "#000" }}>
      <div style={{ position: "absolute", top: 30, width: "100%", textAlign: "center", color: "white", zIndex: 10 }}>
        <div style={{ width: "400px", height: "16px", background: "#222", margin: "0 auto", borderRadius: "10px", border: "2px solid #fff", overflow: "hidden" }}>
          <div style={{ width: `${enemyHp}%`, height: "100%", background: "linear-gradient(90deg, #f00, #ff416c)", transition: "width 0.4s" }} />
        </div>
        <div style={{ width: "400px", height: "16px", background: "#222", margin: "8px auto 0", borderRadius: "10px", border: "2px solid #fff", overflow: "hidden" }}>
          <div style={{ width: `${playerHp}%`, height: "100%", background: "linear-gradient(90deg, #00b3ff, #00ffd5)", transition: "width 0.4s" }} />
        </div>
        {gameMsg && <h1 style={{ fontSize: "80px", fontWeight: "900", textShadow: "4px 4px 10px #000", margin: "10px 0" }}>{gameMsg}</h1>}
        <div style={{ width: "500px", height: "20px", background: "rgba(0,0,0,0.5)", border: "2px solid #555", margin: "10px auto", borderRadius: "10px", overflow: "hidden" }}>
          <div style={{ width: `${attackGauge}%`, height: "100%", background: "cyan", boxShadow: "0 0 15px cyan", transition: "width 0.2s" }} />
        </div>
      </div>
      <Canvas>
        <Suspense fallback={null}>
          <PerspectiveCamera makeDefault position={[0, 1.5, 4.5]} />
          <Environment preset="city" />
          <BoxerScene
            activeKey={activeKey}
            headX={motion.x}
            onReturnToBase={() => setActiveKey("base")}
          />
          <Preload all />
        </Suspense>
      </Canvas>
    </div>
  );
}
