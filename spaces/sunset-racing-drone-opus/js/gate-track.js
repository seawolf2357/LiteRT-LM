// ═══════════════════════════════════════════════════════
//  GATE TRACK — sequence of neon torus gates placed in 3D
//  space. Gates are oriented by computing a "travel
//  direction" from the previous waypoint to the current
//  one (so the drone always approaches head-on). Next
//  gate gets a tall sky beacon column and a breathing
//  glow so it reads from anywhere on the map.
// ═══════════════════════════════════════════════════════
import * as THREE from 'three';
import {
  GATE_COUNT, GATE_RADIUS, GATE_TUBE, GATE_PLANE_EPS,
  C_NEXT_GATE, C_FUTURE_GATE, C_DONE_GATE, C_FLASH, C_BEACON,
} from './config.js';

// Spawn position is where the drone starts — used to orient
// the first gate so it faces the drone directly.
const SPAWN_POS = new THREE.Vector3(0, 8, 60);

/**
 * Raw waypoint positions. Each gate's orientation is derived
 * from the vector from the previous waypoint (or spawn, for
 * index 0) to this waypoint, so the course is auto-oriented.
 */
function buildGatePath() {
  const waypoints = [
    { x:   0, y:  8, z:  30 }, // 0 — straight ahead from spawn
    { x:  16, y: 11, z:   5 }, // 1 — bank right
    { x:  30, y: 14, z: -20 }, // 2 — right curve, climbing
    { x:  18, y: 18, z: -44 }, // 3 — top of right-side climb
    { x:  -8, y: 22, z: -55 }, // 4 — apex over the center
    { x: -30, y: 18, z: -40 }, // 5 — descending left-side
    { x: -38, y: 13, z: -14 }, // 6 — left sweep
    { x: -26, y:  9, z:  10 }, // 7 — coming back home
    { x:  -8, y:  8, z:  32 }, // 8 — home stretch left
    { x:  12, y:  8, z:  46 }, // 9 — last gate, near spawn
  ];

  const gates = [];
  for (let i = 0; i < GATE_COUNT; i++) {
    const w = waypoints[i % waypoints.length];
    const prev = i === 0 ? SPAWN_POS : waypoints[(i - 1) % waypoints.length];
    // Travel direction = normalized (this - prev), this is the
    // direction the drone flies THROUGH the gate. Ignore the
    // vertical component so gates stay upright (torus axis is
    // horizontal, ring is vertical, drone flies through).
    const dx = w.x - prev.x;
    const dz = w.z - prev.z;
    const len = Math.hypot(dx, dz) || 1;
    const forward = new THREE.Vector3(dx / len, 0, dz / len);

    gates.push({
      index: i,
      position: new THREE.Vector3(w.x, w.y, w.z),
      forward,       // unit vector, direction of travel through gate
      passed: false,
    });
  }
  return gates;
}

export function createGateTrack(scene) {
  const gates = buildGatePath();

  // Shared geometries.
  const torusGeo = new THREE.TorusGeometry(GATE_RADIUS, GATE_TUBE, 12, 48);
  const glowGeo  = new THREE.TorusGeometry(GATE_RADIUS + 0.35, GATE_TUBE * 0.45, 10, 48);
  // Beacon column: tall thin cylinder that rises from ground to sky.
  const beaconGeo = new THREE.CylinderGeometry(0.45, 0.45, 80, 8, 1, true);

  const _tmpTarget = new THREE.Vector3();

  for (const g of gates) {
    // ── Main ring ──
    const mat = new THREE.MeshBasicMaterial({ color: C_FUTURE_GATE });
    const mesh = new THREE.Mesh(torusGeo, mat);
    mesh.position.copy(g.position);
    // Orient torus so its axis (local +Z by default) points
    // along the travel direction. lookAt rotates so local -Z
    // points AT the target, so point at (pos - forward).
    _tmpTarget.copy(g.position).sub(g.forward);
    mesh.lookAt(_tmpTarget);
    scene.add(mesh);
    g.mesh = mesh;
    g.material = mat;

    // ── Outer glow ring ──
    const glowMat = new THREE.MeshBasicMaterial({
      color: C_FUTURE_GATE, transparent: true, opacity: 0.4,
      depthWrite: false,
    });
    const glow = new THREE.Mesh(glowGeo, glowMat);
    glow.position.copy(mesh.position);
    glow.quaternion.copy(mesh.quaternion);
    scene.add(glow);
    g.glow = glow;
    g.glowMat = glowMat;

    // ── Sky beacon column (visible from anywhere on map) ──
    const beaconMat = new THREE.MeshBasicMaterial({
      color: C_FUTURE_GATE,
      transparent: true,
      opacity: 0.0, // default hidden; turned on only for next gate
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    const beacon = new THREE.Mesh(beaconGeo, beaconMat);
    beacon.position.set(g.position.x, 40, g.position.z);
    scene.add(beacon);
    g.beacon = beacon;
    g.beaconMat = beaconMat;

    // ── Gate index label board (a thin sprite-like plane above the gate) ──
    const labelCanvas = document.createElement('canvas');
    labelCanvas.width = 128; labelCanvas.height = 64;
    const lctx = labelCanvas.getContext('2d');
    lctx.fillStyle = 'rgba(0,0,0,0)'; lctx.fillRect(0, 0, 128, 64);
    lctx.fillStyle = '#ffffff';
    lctx.font = '900 48px Orbitron, sans-serif';
    lctx.textAlign = 'center';
    lctx.textBaseline = 'middle';
    lctx.shadowColor = 'rgba(0,0,0,0.9)';
    lctx.shadowBlur = 6;
    lctx.fillText(String(g.index + 1), 64, 34);
    const labelTex = new THREE.CanvasTexture(labelCanvas);
    labelTex.minFilter = THREE.LinearFilter;
    const labelMat = new THREE.SpriteMaterial({ map: labelTex, transparent: true, depthTest: false });
    const label = new THREE.Sprite(labelMat);
    label.scale.set(3.5, 1.75, 1);
    label.position.set(g.position.x, g.position.y + GATE_RADIUS + 1.2, g.position.z);
    label.renderOrder = 10;
    scene.add(label);
    g.label = label;
  }

  // Flash sphere reused between gates.
  const flashGeo = new THREE.SphereGeometry(GATE_RADIUS * 0.9, 24, 12);
  const flashMat = new THREE.MeshBasicMaterial({
    color: C_FLASH, transparent: true, opacity: 0.0, depthWrite: false,
  });
  const flashMesh = new THREE.Mesh(flashGeo, flashMat);
  scene.add(flashMesh);
  let flashTimer = 0;
  function triggerFlashAt(pos) {
    flashMesh.position.copy(pos);
    flashMat.opacity = 0.85;
    flashMesh.scale.set(0.6, 0.6, 0.6);
    flashTimer = 0.5;
  }

  /**
   * Line segment (prev → curr) vs gate disc intersection test.
   * Returns true if the drone passed through this gate going
   * in the correct travel direction.
   */
  function testPass(prev, curr, gate) {
    const p = gate.position;
    const n = gate.forward;
    // Signed distances — positive = "in front" of gate (approach side).
    // A point is "in front" if it is on the -forward side of the gate,
    // so we flip the sign: d = (point - gatePos) · (-forward).
    const d0 = -((prev.x - p.x) * n.x + (prev.y - p.y) * n.y + (prev.z - p.z) * n.z);
    const d1 = -((curr.x - p.x) * n.x + (curr.y - p.y) * n.y + (curr.z - p.z) * n.z);

    // Drone must go from "in front" (d0>0) to "behind" (d1<0).
    if (d0 < GATE_PLANE_EPS || d1 > -GATE_PLANE_EPS) return false;

    const t = d0 / (d0 - d1);
    if (t < 0 || t > 1) return false;
    const ix = prev.x + (curr.x - prev.x) * t;
    const iy = prev.y + (curr.y - prev.y) * t;
    const iz = prev.z + (curr.z - prev.z) * t;

    const dx = ix - p.x;
    const dy = iy - p.y;
    const dz = iz - p.z;
    return (dx * dx + dy * dy + dz * dz) <= GATE_RADIUS * GATE_RADIUS;
  }

  let nextGateIndex = 0;

  function update(prevPos, currPos, dt) {
    const t = performance.now() * 0.004;

    // Breathing animation + per-state coloring.
    for (let i = 0; i < gates.length; i++) {
      const g = gates[i];
      const isNext = (i === nextGateIndex);
      const isDone = g.passed;

      if (isNext) {
        g.material.color.setHex(C_NEXT_GATE);
        g.glowMat.color.setHex(C_NEXT_GATE);
        const breath = 0.55 + 0.45 * Math.abs(Math.sin(t));
        g.glowMat.opacity = 0.35 + 0.55 * breath;
        // Beacon column on.
        g.beaconMat.color.setHex(C_BEACON);
        g.beaconMat.opacity = 0.18 + 0.12 * breath;
        // Label bigger
        g.label.scale.set(5.5, 2.75, 1);
      } else if (isDone) {
        g.material.color.setHex(C_DONE_GATE);
        g.glowMat.color.setHex(C_DONE_GATE);
        g.glowMat.opacity = 0.15;
        g.beaconMat.opacity = 0.0;
        g.label.scale.set(2.8, 1.4, 1);
      } else {
        g.material.color.setHex(C_FUTURE_GATE);
        g.glowMat.color.setHex(C_FUTURE_GATE);
        g.glowMat.opacity = 0.35;
        g.beaconMat.opacity = 0.0;
        g.label.scale.set(3.5, 1.75, 1);
      }
    }

    // Flash decay.
    if (flashTimer > 0) {
      flashTimer -= dt;
      const f = Math.max(0, flashTimer / 0.5);
      flashMat.opacity = 0.85 * f;
      const s = 0.6 + (1 - f) * 2.0;
      flashMesh.scale.set(s, s, s);
    }

    // Pass detection.
    const nextGate = gates[nextGateIndex];
    if (!nextGate) return null;
    if (testPass(prevPos, currPos, nextGate)) {
      nextGate.passed = true;
      triggerFlashAt(nextGate.position);
      nextGateIndex++;
      return nextGate;
    }
    return null;
  }

  function resetForLap() {
    for (const g of gates) g.passed = false;
    nextGateIndex = 0;
  }

  function getNextGate()      { return gates[nextGateIndex] || null; }
  function getNextGateIndex() { return nextGateIndex; }
  function getGateCount()     { return gates.length; }
  function getAllGates()      { return gates; }

  return {
    update, resetForLap, getNextGate, getNextGateIndex,
    getGateCount, getAllGates, SPAWN_POS,
  };
}
