import React, { Suspense, useEffect, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF, PerspectiveCamera, Environment, Preload } from "@react-three/drei";
import { io } from "socket.io-client";
import * as THREE from "three";

const MODELS_LIST = {
  base: "/models/enemy_boxer.glb",
  hook: "/models/Hook.glb",
  punch_l: "/models/Punch_left.glb",
  punch_r: "/models/Punch_right.glb",
  straight: "/models/Straight.glb",
  uppercut: "/models/Uppercut.glb"
};
const DRACO_URL = "https://www.gstatic.com/draco/versioned/decoders/1.5.5/";

function BoxerScene({ activeKey, headX, onReturnToBase, onHitJudge, isShaking, gameState }) {
  const m0 = useGLTF(MODELS_LIST.base, DRACO_URL);
  const m1 = useGLTF(MODELS_LIST.hook, DRACO_URL);
  const m2 = useGLTF(MODELS_LIST.punch_l, DRACO_URL);
  const m3 = useGLTF(MODELS_LIST.punch_r, DRACO_URL);
  const m4 = useGLTF(MODELS_LIST.straight, DRACO_URL);
  const m5 = useGLTF(MODELS_LIST.uppercut, DRACO_URL);

  const mixerRef = useRef();
  const actionsRef = useRef({});
  const isHitProcessed = useRef(false);

  useEffect(() => {
    if (!m0.scene) return;
    mixerRef.current = new THREE.AnimationMixer(m0.scene);
    const handleFinished = () => { isHitProcessed.current = false; onReturnToBase(); };
    mixerRef.current.addEventListener("finished", handleFinished);

    const gltfMap = { base: m0, hook: m1, punch_l: m2, punch_r: m3, straight: m4, uppercut: m5 };
    Object.keys(gltfMap).forEach((key) => {
      if (gltfMap[key]?.animations?.[0]) {
        const action = mixerRef.current.clipAction(gltfMap[key].animations[0]);
        action.setEffectiveTimeScale(gameState === "ATTACK_CHANCE" ? 0.6 : 1.8);
        if (key !== "base") { action.setLoop(THREE.LoopOnce); action.clampWhenFinished = true; }
        actionsRef.current[key] = action;
      }
    });
    actionsRef.current["base"]?.play();
    return () => mixerRef.current?.removeEventListener("finished", handleFinished);
  }, [m0, gameState]);

  useEffect(() => {
    if (activeKey !== "base") isHitProcessed.current = false;
    Object.keys(actionsRef.current).forEach(key => {
      const action = actionsRef.current[key];
      if (!action) return;
      if (key === activeKey) action.reset().fadeIn(0.1).play();
      else action.fadeOut(0.1);
    });
  }, [activeKey]);

  useFrame((state, delta) => {
    if (mixerRef.current) mixerRef.current.update(delta);
    if (activeKey !== "base" && !isHitProcessed.current && gameState === "DEFENSE") {
      const action = actionsRef.current[activeKey];
      if (action && action.time > action.getClip().duration * 0.5) {
        isHitProcessed.current = true;
        onHitJudge(activeKey);
      }
    }
    if (isShaking) {
      state.camera.position.x += (Math.random() - 0.5) * 0.15;
      state.camera.position.y += (Math.random() - 0.5) * 0.15;
    }
    if (m0.scene) m0.scene.position.x = THREE.MathUtils.lerp(m0.scene.position.x, -headX * 2.5, 0.15);
  });

  return <primitive object={m0.scene} scale={3.8} position={[0, -2.4, -1.8]} />;
}

export default function GamePage() {
  const [playerHp, setPlayerHp] = useState(9);
  const [enemyHp, setEnemyHp] = useState(100);
  const [attackGauge, setAttackGauge] = useState(0);
  const [activeKey, setActiveKey] = useState("base");
  const [motion, setMotion] = useState({ x: 0, z: 0, dir: "none" });
  const [gameState, setGameState] = useState("DEFENSE");
  const [gameMsg, setGameMsg] = useState("READY");
  const [isShaking, setIsShaking] = useState(false);
  const socketRef = useRef();

  useEffect(() => {
    socketRef.current = io("http://127.0.0.1:65432", { transports: ["websocket"] });
    socketRef.current.on("motion", (data) => {
      setMotion(data);
      // ✅ 찬스타임일 때 공격 명령이 오면 handlePlayerAttack 실행
      if (gameState === "ATTACK_CHANCE" && data.dir !== "none") {
        handlePlayerAttack(data.dir);
      }
    });
    return () => socketRef.current.disconnect();
  }, [gameState]);

  // 찬스타임 5초 타임아웃
  useEffect(() => {
    if (gameState === "ATTACK_CHANCE") {
      const timer = setTimeout(() => {
        if (gameState === "ATTACK_CHANCE") {
          setGameState("DEFENSE");
          setAttackGauge(0);
          setGameMsg("TIME OVER!");
        }
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [gameState]);

  useEffect(() => {
    if (gameState !== "DEFENSE" || activeKey !== "base") return;
    const timer = setTimeout(() => {
      const attacks = ["punch_l", "punch_r", "straight", "hook", "uppercut"];
      setActiveKey(attacks[Math.floor(Math.random() * attacks.length)]);
    }, 2000);
    return () => clearTimeout(timer);
  }, [activeKey, gameState]);

  const handlePlayerAttack = (punchType) => {
    // 펀치 인식 즉시 상태 변경하여 중복 타격 및 교착 상태 방지
    const damages = { jab: 20, straight: 30, uppercut: 60 };
    const damage = damages[punchType] || 25;

    setEnemyHp(prev => Math.max(0, prev - damage));
    setGameState("DEFENSE"); // ✅ 즉시 상태 전환
    setAttackGauge(0);
    setGameMsg(`👊 ${punchType.toUpperCase()} SUCCESS!`);
    setIsShaking(true);
    setTimeout(() => setIsShaking(false), 200);

    if (enemyHp - damage <= 0) {
      setGameState("WIN");
      setGameMsg("🏆 K.O. VICTORY!");
    }
  };

  const handleEnemyAttackJudge = (attackType) => {
    if (gameState !== "DEFENSE") return;
    const isDodged = Math.abs(motion.x) > 0.22;
    const isGuarded = motion.z >= 0.8;

    if (isDodged || isGuarded) {
      setAttackGauge(prev => {
        const next = Math.min(100, prev + (isDodged ? 35 : 15));
        if (next >= 100) {
          setGameState("ATTACK_CHANCE");
          setGameMsg("🔥 CHANCE TIME! 🔥");
        }
        return next;
      });
      setGameMsg(isDodged ? "💨 DODGE!" : "🛡️ GUARD!");
      setTimeout(() => setActiveKey("base"), 100);
    } else {
      setGameMsg("💥 HIT!");
      setIsShaking(true);
      setTimeout(() => setIsShaking(false), 200);
      setPlayerHp(prev => {
        const next = Math.max(0, prev - 1);
        if (next === 0) setGameState("GAME_OVER");
        return next;
      });
      setTimeout(() => setActiveKey("base"), 100);
    }
  };

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative", overflow: "hidden", backgroundImage: "url('/models/Background.png')", backgroundSize: "cover", backgroundColor: "#000" }}>
      <div style={{ position: "absolute", inset: 0, zIndex: 5, pointerEvents: "none", background: `radial-gradient(circle, transparent 30%, rgba(255,0,0,${isShaking ? 0.3 : 0}))` }} />
      <div style={{ position: "absolute", top: 30, width: "100%", textAlign: "center", color: "white", zIndex: 10 }}>
        <div style={{ width: "400px", height: "16px", background: "#222", margin: "0 auto", borderRadius: "10px", border: "2px solid #fff", overflow: "hidden" }}>
          <div style={{ width: `${enemyHp}%`, height: "100%", background: "linear-gradient(90deg, #f00, #ff416c)", transition: "width 0.4s" }} />
        </div>
        <h1 style={{ fontSize: "80px", fontWeight: "900", textShadow: "4px 4px 10px #000" }}>{gameMsg}</h1>
        <div style={{ width: "500px", height: "20px", background: "#111", border: "2px solid #555", margin: "0 auto", borderRadius: "10px", overflow: "hidden" }}>
          <div style={{ width: `${attackGauge}%`, height: "100%", background: attackGauge >= 100 ? "cyan" : "deepskyblue", transition: "width 0.2s" }} />
        </div>
      </div>
      <Canvas>
        <Suspense fallback={null}>
          <PerspectiveCamera makeDefault position={[0, 1.5, 4.5]} />
          <Environment preset="city" />
          <BoxerScene activeKey={activeKey} headX={motion.x} onReturnToBase={() => setActiveKey("base")} onHitJudge={handleEnemyAttackJudge} isShaking={isShaking} gameState={gameState} />
          <Preload all />
        </Suspense>
      </Canvas>
    </div>
  );
}