// ═══════════════════════════════════════════════════════
//  DRONE PHYSICS — 6DoF acro-mode simulation.
//  State: position (Vec3), velocity (Vec3), quaternion
//  (orientation), angular velocity (Vec3 in body frame),
//  throttle (0..1). Integrated with semi-implicit Euler.
// ═══════════════════════════════════════════════════════
import * as THREE from 'three';
import {
  MAX_THRUST, GRAVITY, DRAG_LINEAR, DRAG_ANGULAR,
  PITCH_RATE, YAW_RATE, ROLL_RATE, RATE_RESPONSE,
  THROTTLE_SLEW, clamp,
} from './config.js';

const UP_LOCAL = new THREE.Vector3(0, 1, 0); // drone thrust axis
const GRAVITY_VEC = new THREE.Vector3(0, -GRAVITY, 0);

export function createDrone(initialPos, initialHeading = 0) {
  const state = {
    position: initialPos.clone(),
    velocity: new THREE.Vector3(),
    // Start upright, facing +Z rotated by initialHeading around Y.
    quaternion: new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 1, 0), initialHeading
    ),
    angularVelocity: new THREE.Vector3(), // rad/s in body frame
    throttle: 0.0,
    // Propeller visual spin, not physical — just a fast RPM counter.
    propPhase: 0,
  };

  // Reusable scratch objects to avoid per-frame allocation in the loop.
  const _thrustLocal = new THREE.Vector3();
  const _thrustWorld = new THREE.Vector3();
  const _dq          = new THREE.Quaternion();
  const _euler       = new THREE.Euler();
  const _axis        = new THREE.Vector3();

  /**
   * Advance one physics step.
   * @param {object} input - { pitch, yaw, roll, throttleDelta } all in [-1, 1]
   * @param {number} dt    - seconds
   */
  function step(input, dt) {
    if (dt <= 0) return;

    // ── 1. Throttle slew ─────────────────────────────────
    const throttleTarget = clamp(state.throttle + input.throttleDelta * THROTTLE_SLEW * dt, 0, 1);
    state.throttle = throttleTarget;

    // ── 2. Angular velocity ──────────────────────────────
    // Commanded body rates from input (acro mode: no auto-level).
    const cmdPitch =  input.pitch * PITCH_RATE;
    const cmdYaw   =  input.yaw   * YAW_RATE;
    const cmdRoll  =  input.roll  * ROLL_RATE;

    // Smoothly approach commanded rates. Using framerate-independent
    // exponential lerp: rate = 1 - exp(-RATE_RESPONSE*dt).
    const rateAlpha = 1 - Math.exp(-RATE_RESPONSE * dt);
    state.angularVelocity.x += (cmdPitch - state.angularVelocity.x) * rateAlpha;
    state.angularVelocity.y += (cmdYaw   - state.angularVelocity.y) * rateAlpha;
    state.angularVelocity.z += (cmdRoll  - state.angularVelocity.z) * rateAlpha;

    // Angular drag (small — drone keeps spinning in acro).
    const angDrag = Math.max(0, 1 - DRAG_ANGULAR * dt * 0.25);
    state.angularVelocity.multiplyScalar(angDrag);

    // ── 3. Integrate orientation ─────────────────────────
    // Build the small-rotation quaternion for this step from the
    // body-frame angular velocity, then right-multiply (body-local).
    _euler.set(
      state.angularVelocity.x * dt,
      state.angularVelocity.y * dt,
      state.angularVelocity.z * dt,
      'XYZ'
    );
    _dq.setFromEuler(_euler);
    state.quaternion.multiply(_dq);
    state.quaternion.normalize();

    // ── 4. Forces ────────────────────────────────────────
    // Thrust along the drone's local +Y, transformed to world space.
    _thrustLocal.copy(UP_LOCAL).multiplyScalar(state.throttle * MAX_THRUST);
    _thrustWorld.copy(_thrustLocal).applyQuaternion(state.quaternion);

    // a = thrust + gravity - linear drag proportional to velocity
    const ax = _thrustWorld.x - state.velocity.x * DRAG_LINEAR;
    const ay = _thrustWorld.y + GRAVITY_VEC.y - state.velocity.y * DRAG_LINEAR;
    const az = _thrustWorld.z - state.velocity.z * DRAG_LINEAR;

    // ── 5. Integrate velocity + position ─────────────────
    state.velocity.x += ax * dt;
    state.velocity.y += ay * dt;
    state.velocity.z += az * dt;

    state.position.x += state.velocity.x * dt;
    state.position.y += state.velocity.y * dt;
    state.position.z += state.velocity.z * dt;

    // ── 6. Prop phase (visual only) ──────────────────────
    // Spin speed tracks thrust intensity; min spin so idle props still turn.
    state.propPhase += (6 + state.throttle * 60) * dt;

    // ── 7. Soft ground collision ─────────────────────────
    // Bounce weakly on the floor so you can't tunnel; a proper
    // crash model would destroy the drone, but for the MVP we
    // just clamp to y=0 and kill vertical velocity.
    if (state.position.y < 0.2) {
      state.position.y = 0.2;
      if (state.velocity.y < 0) state.velocity.y = 0;
    }
  }

  /** Reset the drone to a hover at a given world position + heading. */
  function resetToHover(pos, heading) {
    state.position.copy(pos);
    state.velocity.set(0, 0, 0);
    state.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), heading);
    state.angularVelocity.set(0, 0, 0);
    state.throttle = 0.55; // mid-throttle so you don't fall on reset
  }

  /** Forward unit vector in world space (drone nose direction). */
  function getForward(out) {
    out.set(0, 0, -1).applyQuaternion(state.quaternion);
    return out;
  }

  return { state, step, resetToHover, getForward };
}
