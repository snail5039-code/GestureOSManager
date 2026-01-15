import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader";

export default function GamePage() {
  const mountRef = useRef(null);
  const [gameState] = useState({ message: "FIGHT!", hp: 100, enemyHp: 100 });
  const gameRef = useRef({ mixer: null, clock: new THREE.Clock() });

  useEffect(() => {
    const scene = new THREE.Scene();
    
    // 1. 카메라 - 캐릭터 바로 앞 눈높이
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 1.4, 2.5);

    // 2. 렌더러
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    if (mountRef.current) mountRef.current.appendChild(renderer.domElement);

    // 3. 조명 (모델이 검게 보이지 않도록 강력하게)
    scene.add(new THREE.AmbientLight(0xffffff, 3.0));

    // 4. 배경 로드 (public 폴더에 있는 파일 직접 참조)
    const loader = new THREE.TextureLoader();
    loader.load("/ring_bg.png", (tex) => {
      scene.background = tex;
    });

    // 5. 적 캐릭터 로드 (public 폴더에 있는 파일 직접 참조)
    const gltfLoader = new GLTFLoader();
    gltfLoader.load("/enemy_boxer.glb", (gltf) => {
      const model = gltf.scene;
      scene.add(model);

      // 애니메이션 강제 재생 (T-Pose 해결)
      if (gltf.animations.length > 0) {
        gameRef.current.mixer = new THREE.AnimationMixer(model);
        gameRef.current.mixer.clipAction(gltf.animations[0]).play();
      }
    });

    // 6. 루프
    let frameId;
    const animate = () => {
      frameId = requestAnimationFrame(animate);
      const delta = gameRef.current.clock.getDelta();
      if (gameRef.current.mixer) gameRef.current.mixer.update(delta);
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(frameId);
      if (mountRef.current) mountRef.current.innerHTML = "";
      renderer.dispose();
    };
  }, []);

  return (
    <div style={{ width: "100%", height: "100vh", position: "relative" }}>
      <div ref={mountRef} style={{ width: "100%", height: "100%" }} />
      
      {/* UI 영역 */}
      <div style={{ position: "absolute", top: "40px", width: "100%", textAlign: "center", pointerEvents: "none" }}>
        <div style={{ width: "300px", height: "15px", background: "#333", margin: "0 auto", border: "2px solid #fff" }}>
          <div style={{ width: "100%", height: "100%", background: "red" }} />
        </div>
        <h1 style={{ color: "#fff", fontSize: "5rem", textShadow: "0 0 20px red" }}>{gameState.message}</h1>
        <div style={{ color: "#fff" }}>HP: {gameState.hp}% | ENEMY: {gameState.enemyHp}%</div>
      </div>
    </div>
  );
}