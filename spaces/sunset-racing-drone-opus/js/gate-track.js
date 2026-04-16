// ═══════════════════════════════════════════════════════
//  GATE TRACK — sequence of neon torus gates placed in 3D
//  space. Exposes the gate list, pass-through detection
//  (line-segment vs gate plane), and a per-frame update
//  that handles the highlight color of the "next" gate
//  and flash effect on clean pass.
// ═══════════════════════════════════════════════════════
import * as THREE from 'three';
import {
  GATE_COUNT, GATE_RADIUS, GATE_TUBE, GATE_PLANE_EPS,
  C_NEXT_GATE, C_FUTURE_GATE, C_DONE_GATE, C_FLASH,
} from './config.js';

/**
 * Generate the gate positions + orientations for a single lap.
 * The track is a figure-8-ish loop with vertical variation.
 */
function buildGatePath() {
  const gates = [];
  // Parametric loop: spiral-ish canyon.
  // Keep it tight enough to memorize, open enough to fly.
  const waypoints = [
    { x:   0, y:  6, z:  40, heading:  Math.PI      },
    { x:  28, y:  9, z:  20, heading:  Math.PI * 0.65 },
    { x:  38, y: 14, z: -12, heading:  Math.PI * 0.35 },
    { x:  18, y: 18, z: -38, heading:  Math.PI * 0.0  },
    { x: -14, y: 22, z: -46, heading: -Math.PI * 0.25 },
    { x: -38, y: 16, z: -22, heading: -Math.PI * 0.55 },
    { x: -40, y: 10, z:  14, heading: -Math.PI * 0.85 },
    { x: -18, y:  8, z:  34, heading:  Math.PI * 0.95 },
    { x:  -2, y: 12, z:  48, heading:  Math.PI        },
    { x:  16, y:  7, z:  44, heading:  Math.PI * 0.82 },
  ];
  // If GATE_COUNT ever differs, tile the waypoints.
  for (let i = 0; i < GATE_COUNT; i++) {
    const w = waypoints[i % waypoints.length];
    gates.push({
      index: i,
      position: new THREE.Vector3(w.x, w.y, w.z),
      heading: w.heading, // rotation around Y axis; gate faces this way
    });
  }
  return gates;
}

export function createGateTrack(scene) {
  const gates = buildGatePath();

  // Shared geometry — one torus for all gates.
  const torusGeo = new THREE.TorusGeometry(GATE_RADIUS, GATE_TUBE, 10, 40);

  // Per-gate mesh + outer glow mesh.
  for (const g of gates) {
    const mat = new THREE.MeshBasicMaterial({ color: C_FUTURE_GATE });
    const mesh = new THREE.Mesh(torusGeo, mat);
    mesh.position.copy(g.position);
    // Torus lies in its local XY plane; rotate so the "opening"
    // faces along the gate's heading vector.
    mesh.rotation.y = g.heading;
    mesh.rotation.x = Math.PI / 2;
    scene.add(mesh);
    g.mesh = mesh;
    g.material = mat;

    // A fainter, slightly larger ring for glow/bloom stand-in.
    const glowGeo = new THREE.TorusGeometry(GATE_RADIUS + 0.25, GATE_TUBE * 0.35, 8, 40);
    const glowMat = new THREE.MeshBasicMaterial({
      color: C_FUTURE_GATE, transparent: true, opacity: 0.35,
    });
    const glow = new THREE.Mesh(glowGeo, glowMat);
    glow.position.copy(mesh.position);
    glow.rotation.copy(mesh.rotation);
    scene.add(glow);
    g.glow = glow;

    // Forward unit vector — used for plane math during detection.
    g.normal = new THREE.Vector3(0, 0, 1).applyAxisAngle(
      new THREE.Vector3(0, 1, 0), g.heading
    );

    // A small ember sprite placed in front of the gate (visible
    // for the next gate only), a hint arrow shown by game.js.
    g.passed = false;
  }

  // A flash sphere used by flashAt() — reused between gates.
  const flashGeo = new THREE.SphereGeometry(GATE_RADIUS * 0.9, 24, 12);
  const flashMat = new THREE.MeshBasicMaterial({
    color: C_FLASH, transparent: true, opacity: 0.0, depthWrite: false,
  });
  const flashMesh = new THREE.Mesh(flashGeo, flashMat);
  scene.add(flashMesh);
  let flashTimer = 0;
  function triggerFlashAt(pos) {
    flashMesh.position.copy(pos);
    flashMat.opacity = 0.75;
    flashMesh.scale.set(0.6, 0.6, 0.6);
    flashTimer = 0.45; // seconds
  }

  /**
   * Test whether the line segment (prev → curr) pierces the
   * upcoming gate's disc. Returns true on clean pass.
   */
  function testPass(prev, curr, gate) {
    const p = gate.position;
    const n = gate.normal;
    // Signed distances of endpoints to the gate plane.
    const d0 = (prev.x - p.x) * n.x + (prev.y - p.y) * n.y + (prev.z - p.z) * n.z;
    const d1 = (curr.x - p.x) * n.x + (curr.y - p.y) * n.y + (curr.z - p.z) * n.z;

    // Forward crossing only (front → back relative to gate normal).
    if (d0 < GATE_PLANE_EPS || d1 > -GATE_PLANE_EPS) return false;

    // Find the intersection point on the plane.
    const t = d0 / (d0 - d1); // 0..1
    if (t < 0 || t > 1) return false;
    const ix = prev.x + (curr.x - prev.x) * t;
    const iy = prev.y + (curr.y - prev.y) * t;
    const iz = prev.z + (curr.z - prev.z) * t;

    // Radial distance from gate center at the intersection.
    const dx = ix - p.x;
    const dy = iy - p.y;
    const dz = iz - p.z;
    const dist2 = dx * dx + dy * dy + dz * dz;
    return dist2 <= GATE_RADIUS * GATE_RADIUS;
  }

  let nextGateIndex = 0;

  /**
   * Called each frame with the drone's previous + current positions.
   * If the drone passes the next gate, advances the index and
   * triggers visual effects. Returns the gate that was passed
   * (or null if none).
   */
  function update(prevPos, currPos, dt) {
    // Animate gate materials: breathing glow on next, dim on done.
    for (let i = 0; i < gates.length; i++) {
      const g = gates[i];
      const isNext = (i === nextGateIndex);
      const isDone = g.passed;
      if (isNext) {
        g.material.color.setHex(C_NEXT_GATE);
        g.glow.material.color.setHex(C_NEXT_GATE);
        const breath = 0.55 + 0.45 * Math.abs(Math.sin(performance.now() * 0.004));
        g.glow.material.opacity = 0.2 + 0.5 * breath;
      } else if (isDone) {
        g.material.color.setHex(C_DONE_GATE);
        g.glow.material.color.setHex(C_DONE_GATE);
        g.glow.material.opacity = 0.15;
      } else {
        g.material.color.setHex(C_FUTURE_GATE);
        g.glow.material.color.setHex(C_FUTURE_GATE);
        g.glow.material.opacity = 0.28;
      }
    }

    // Flash decay.
    if (flashTimer > 0) {
      flashTimer -= dt;
      const t = Math.max(0, flashTimer / 0.45);
      flashMat.opacity = 0.75 * t;
      const s = 0.6 + (1 - t) * 1.6;
      flashMesh.scale.set(s, s, s);
    }

    // Pass detection against just the next gate.
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

  /** Start a new lap: mark all gates unpassed, reset index. */
  function resetForLap() {
    for (const g of gates) g.passed = false;
    nextGateIndex = 0;
  }

  /** Get the next gate object (for HUD arrow + AI targeting). */
  function getNextGate() {
    return gates[nextGateIndex] || null;
  }

  function getNextGateIndex() { return nextGateIndex; }
  function getGateCount()     { return gates.length; }
  function getAllGates()      { return gates; }

  return {
    update, resetForLap, getNextGate, getNextGateIndex,
    getGateCount, getAllGates,
  };
}
