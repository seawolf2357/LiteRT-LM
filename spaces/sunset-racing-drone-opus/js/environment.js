// ═══════════════════════════════════════════════════════
//  ENVIRONMENT — sunset sky dome, horizon mountains,
//  ground plane, and directional sunlight that can drop
//  across the race (sun descends each completed lap).
// ═══════════════════════════════════════════════════════
import * as THREE from 'three';
import {
  SUN_BASE_ANGLE, SUN_DROP_PER_LAP, FOG_NEAR, FOG_FAR,
} from './config.js';

export function createEnvironment(scene, renderer) {
  // ── Background fog for depth cues ─────────────────────
  // Warm sunset tint so distant geometry blends with sky.
  scene.fog = new THREE.Fog(0x5a1838, FOG_NEAR, FOG_FAR);

  // ── Sky dome: vertical sunset gradient on the inside of
  //    a large inverted sphere (shader-free, works on HF
  //    static Spaces with zero build step). ──
  const skyGeo = new THREE.SphereGeometry(500, 32, 20);
  const skyMat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: {
      topColor:    { value: new THREE.Color(0x1a0835) },
      midColor:    { value: new THREE.Color(0xa11f4c) },
      botColor:    { value: new THREE.Color(0xff6a3d) },
      sunColor:    { value: new THREE.Color(0xffdba0) },
      sunDir:      { value: new THREE.Vector3(0.3, 0.1, 0.95).normalize() },
    },
    vertexShader: `
      varying vec3 vWorldPos;
      varying vec3 vNormal;
      void main() {
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vWorldPos = wp.xyz;
        vNormal = normalize(position);
        gl_Position = projectionMatrix * viewMatrix * wp;
      }
    `,
    fragmentShader: `
      uniform vec3 topColor;
      uniform vec3 midColor;
      uniform vec3 botColor;
      uniform vec3 sunColor;
      uniform vec3 sunDir;
      varying vec3 vWorldPos;
      varying vec3 vNormal;
      void main() {
        float h = clamp(vNormal.y * 0.5 + 0.5, 0.0, 1.0);
        vec3 col;
        if (h < 0.5) {
          col = mix(botColor, midColor, smoothstep(0.0, 0.5, h));
        } else {
          col = mix(midColor, topColor, smoothstep(0.5, 1.0, h));
        }
        // Sun glow blob (dot against sun direction)
        float s = max(dot(normalize(vNormal), normalize(sunDir)), 0.0);
        float sun = pow(s, 64.0);
        col += sunColor * sun * 1.4;
        // Soft horizon bloom
        float horizon = pow(1.0 - abs(vNormal.y), 6.0);
        col += vec3(1.0, 0.45, 0.2) * horizon * 0.35;
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  });
  const sky = new THREE.Mesh(skyGeo, skyMat);
  scene.add(sky);

  // ── Distant ground: a huge low-contrast disc so the
  //    drone has a visual reference for "down", but we
  //    don't actually expect the player to land on it. ──
  const groundGeo = new THREE.CircleGeometry(480, 48);
  const groundMat = new THREE.MeshStandardMaterial({
    color: 0x1c0828,
    roughness: 0.95,
    metalness: 0.0,
  });
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.5;
  ground.receiveShadow = true;
  scene.add(ground);

  // ── Subtle radial grid on the ground for spatial sense ──
  const grid = new THREE.GridHelper(300, 40, 0x4a1a3a, 0x2a0a22);
  grid.position.y = -0.49;
  grid.material.transparent = true;
  grid.material.opacity = 0.35;
  scene.add(grid);

  // ── Horizon mountain silhouettes (cheap: ring of cones) ──
  const mountainMat = new THREE.MeshStandardMaterial({
    color: 0x180a28,
    roughness: 1.0,
    metalness: 0.0,
  });
  const mountainGroup = new THREE.Group();
  const RING_RADIUS = 340;
  const MOUNTAIN_COUNT = 48;
  for (let i = 0; i < MOUNTAIN_COUNT; i++) {
    const angle = (i / MOUNTAIN_COUNT) * Math.PI * 2;
    const jitter = (Math.sin(i * 2.7) + 1) * 0.5;
    const height = 28 + jitter * 36;
    const radius = 16 + jitter * 12;
    const cone = new THREE.Mesh(
      new THREE.ConeGeometry(radius, height, 8),
      mountainMat
    );
    cone.position.set(
      Math.cos(angle) * RING_RADIUS,
      height / 2 - 4,
      Math.sin(angle) * RING_RADIUS
    );
    mountainGroup.add(cone);
  }
  scene.add(mountainGroup);

  // ── Lighting ──────────────────────────────────────────
  // Brighter ambient so drone + gates stay readable even when
  // the sunset casts long shadows across them.
  const ambient = new THREE.AmbientLight(0xffc99a, 1.05);
  scene.add(ambient);

  // Hemispheric fill — sky-to-ground color bleed for free contrast.
  const hemi = new THREE.HemisphereLight(0xffd0a0, 0x2a0a22, 0.6);
  scene.add(hemi);

  const sun = new THREE.DirectionalLight(0xffe2b0, 1.75);
  sun.position.set(120, 90, 200);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.camera.near = 10;
  sun.shadow.camera.far = 400;
  sun.shadow.camera.left = -80;
  sun.shadow.camera.right = 80;
  sun.shadow.camera.top = 80;
  sun.shadow.camera.bottom = -80;
  scene.add(sun);

  // Warm rim-fill from the opposite side — gives the drone
  // some bounce even when it's facing away from the sun.
  const rim = new THREE.DirectionalLight(0x6a28aa, 0.45);
  rim.position.set(-150, 60, -120);
  scene.add(rim);

  // ── Sun progression: called per completed lap so the
  //    "sunset" in the title actually sunsets. ──
  let sunAngle = SUN_BASE_ANGLE; // radians above horizon
  function advanceSun(laps) {
    sunAngle = Math.max(-0.08, SUN_BASE_ANGLE - laps * SUN_DROP_PER_LAP);
    const h = Math.sin(sunAngle) * 120;
    const horiz = Math.cos(sunAngle) * 220;
    sun.position.set(horiz * 0.6, h + 50, horiz);

    // Tint the sky shader to deepen with sun angle.
    const k = 1 - Math.max(0, sunAngle / SUN_BASE_ANGLE);
    skyMat.uniforms.botColor.value.setRGB(
      1.0 - k * 0.4,
      0.41 + k * 0.05,
      0.23 - k * 0.1
    );
    skyMat.uniforms.midColor.value.setRGB(
      0.63 - k * 0.3,
      0.12 - k * 0.05,
      0.3 + k * 0.1
    );
    // Update sun direction for the sky shader
    skyMat.uniforms.sunDir.value.set(
      Math.cos(sunAngle) * 0.8,
      Math.sin(sunAngle) + 0.05,
      0.2
    ).normalize();
  }

  return { sun, ambient, advanceSun };
}
