import { useEffect, useRef } from "react";
import * as THREE from "three";

export default function GameScene3D({ state, gauge }) {
  const mountRef = useRef(null);

  useEffect(() => {
    if (!mountRef.current) return;

    const mount = mountRef.current; // ⭐ 핵심

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000000);

    const camera = new THREE.PerspectiveCamera(
      60,
      window.innerWidth / window.innerHeight,
      0.1,
      100
    );
    camera.position.set(0, 1.6, 3);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    mount.appendChild(renderer.domElement);

    // light
    const light = new THREE.DirectionalLight(0xffffff, 1);
    light.position.set(1, 2, 3);
    scene.add(light);

    // floor
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(10, 10),
      new THREE.MeshStandardMaterial({ color: 0x222222 })
    );
    floor.rotation.x = -Math.PI / 2;
    scene.add(floor);

    // dummy enemy
    const enemy = new THREE.Mesh(
      new THREE.BoxGeometry(0.6, 1.6, 0.4),
      new THREE.MeshStandardMaterial({ color: 0xff3333 })
    );
    enemy.position.y = 0.8;
    scene.add(enemy);

    let running = true;

    const animate = () => {
      if (!running) return;
      requestAnimationFrame(animate);

      if (state === "CHANCE") {
        camera.position.z = 2.6;
        enemy.material.color.set(0xffff00);
      } else {
        camera.position.z = 3;
        enemy.material.color.set(0xff3333);
      }

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      running = false;
      renderer.dispose();

      // ⭐ 여기 중요
      if (mount) {
        mount.innerHTML = "";
      }
    };
  }, [state]);

  return <div ref={mountRef} className="absolute inset-0" />;
}
