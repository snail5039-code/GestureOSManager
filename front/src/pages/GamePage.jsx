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

function BoxerScene({ activeKey, headX, onReturnToBase, onHitJudge }) {
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
    const handleFinished = () => onReturnToBase();
    mixerRef.current.addEventListener("finished", handleFinished);

    const gltfMap = { base: m0, hook: m1, punch_l: m2, punch_r: m3, straight: m4, uppercut: m5 };
    Object.keys(gltfMap).forEach((key) => {
      const data = gltfMap[key];
      if (data?.animations?.[0]) {
        const action = mixerRef.current.clipAction(data.animations[0]);
        action.setEffectiveTimeScale(1.8);
        if (key !== "base") { action.setLoop(THREE.LoopOnce); action.clampWhenFinished = true; }
        actionsRef.current[key] = action;
      }
    });
    actionsRef.current["base"]?.play();
    return () => mixerRef.current?.removeEventListener("finished", handleFinished);
  }, [m0, m1, m2, m3, m4, m5]);

  useEffect(() => {
    isHitProcessed.current = false;
    const actions = actionsRef.current;
    Object.keys(actions).forEach(key => {
      if (key === activeKey) actions[key].reset().fadeIn(0.1).play();
      else actions[key].fadeOut(0.1);
    });
  }, [activeKey]);

  useFrame((state, delta) => {
    mixerRef.current?.update(delta);
    if (activeKey !== "base" && !isHitProcessed.current) {
      const action = actionsRef.current[activeKey];
      if (action && action.time > action.getClip().duration * 0.6) {
        isHitProcessed.current = true;
        onHitJudge();
      }
    }
    if (m0.scene) m0.scene.position.x = THREE.MathUtils.lerp(m0.scene.position.x, -headX * 2.5, 0.15);
  });

  return <primitive object={m0.scene} scale={3.8} position={[0, -2.4, -1.8]} />;
}

export default function GamePage() {
  const [hp, setHp] = useState(100);
  const [activeKey, setActiveKey] = useState("base");
  const [motion, setMotion] = useState({ x: 0, z: 0 });
  const [msg, setMsg] = useState("READY");
  const socketRef = useRef();

  useEffect(() => {
    // ✅ Invalid frame header 방지를 위해 websocket 전송방식 강제
    socketRef.current = io("http://127.0.0.1:65432", { transports: ["websocket"] });
    socketRef.current.on("motion", (data) => {
      setMotion({ x: data.x || 0, z: data.z || 0 });
    });
    return () => socketRef.current.disconnect();
  }, []);

  useEffect(() => {
    if (activeKey !== "base") return;
    const timer = setTimeout(() => {
      const attacks = ["hook", "straight", "punch_l", "punch_r", "uppercut"];
      setActiveKey(attacks[Math.floor(Math.random() * attacks.length)]);
    }, 2500);
    return () => clearTimeout(timer);
  }, [activeKey]);

  const handleHitJudge = () => {
    // ✅ 가드 판정 기준을 0.01로 극단적으로 낮춤 (조금만 반응해도 가드)
    const isGuarded = motion.z > 0.01;
    const isDodged = Math.abs(motion.x) > 0.22;

    if (isGuarded) {
      setMsg("🛡️ GUARD SUCCESS!");
    } else if (isDodged) {
      setMsg("💨 DODGE!");
    } else {
      setHp(p => Math.max(0, p - 10));
      setMsg("💥 HIT!");
    }
    setTimeout(() => setMsg(""), 800);
  };

  return (
    <div style={{ width: "100vw", height: "100vh", background: "#000", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: 20, width: "100%", textAlign: "center", color: "white", zIndex: 10 }}>
        <h1>HP: {hp} | Z: {motion.z.toFixed(3)}</h1>
        <h2 style={{ color: msg === "💥 HIT!" ? "red" : "#00ff00" }}>{msg}</h2>
      </div>

      <Canvas>
        <Suspense fallback={null}>
          <PerspectiveCamera makeDefault position={[0, 1.5, 4.5]} />
          <Environment preset="city" />
          <BoxerScene activeKey={activeKey} headX={motion.x} onReturnToBase={() => setActiveKey("base")} onHitJudge={handleHitJudge} />
        </Suspense>
      </Canvas>

      {/* 가드 시각적 표시 */}
      {motion.z > 0.01 && (
        <div style={{ position: "absolute", inset: 0, border: "20px solid #00e5ff", pointerEvents: "none", zIndex: 5 }} />
      )}
    </div>
  );
}