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
  THROTTLE_SLEW, HOVER_THROTTLE, clamp,
} from './config.js';

const UP_LOCAL = new THREE.Vector3(0, 1, 0);
const Y_AXIS   = new THREE.Vector3(0, 1, 0);

/**
 * Build a drone quaternion for a given yaw heading where
 * heading = 0 means facing -Z (so the drone looks down the
 * course on spawn when the first gate is in -Z direction).
 */
function quatFromHeading(heading) {
  return new THREE.Quaternion().setFromAxisAngle(Y_AXIS, heading);
}

export function createDrone(initialPos, initialHeading = 0, initialThrottle = HOVER_THROTTLE) {
  const state = {
    position: initialPos.clone(),
    velocity: new THREE.Vector3(),
    quaternion: quatFromHeading(initialHeading),
    angularVelocity: new THREE.Vector3(),
    throttle: initialThrottle,
    propPhase: 0,
  };

  // Reusable scratch.
  const _thrustLocal = new THREE.Vector3();
  const _thrustWorld = new THREE.Vector3();
  const _dq          = new THREE.Quaternion();
  const _euler       = new THREE.Euler();

  function step(input, dt) {
    if (dt <= 0) return;

    // 1. Throttle slew
    state.throttle = clamp(
      state.throttle + input.throttleDelta * THROTTLE_SLEW * dt, 0, 1
    );

    // 2. Angular rate command
    const cmdPitch = input.pitch * PITCH_RATE;
    const cmdYaw   = input.yaw   * YAW_RATE;
    const cmdRoll  = input.roll  * ROLL_RATE;

    const rateAlpha = 1 - Math.exp(-RATE_RESPONSE * dt);
    state.angularVelocity.x += (cmdPitch - state.angularVelocity.x) * rateAlpha;
    state.angularVelocity.y += (cmdYaw   - state.angularVelocity.y) * rateAlpha;
    state.angularVelocity.z += (cmdRoll  - state.angularVelocity.z) * rateAlpha;

    const angDrag = Math.max(0, 1 - DRAG_ANGULAR * dt * 0.12);
    state.angularVelocity.multiplyScalar(angDrag);

    // 3. Integrate orientation (body-frame small-angle)
    _euler.set(
      state.angularVelocity.x * dt,
      state.angularVelocity.y * dt,
      state.angularVelocity.z * dt,
      'XYZ'
    );
    _dq.setFromEuler(_euler);
    state.quaternion.multiply(_dq);
    state.quaternion.normalize();

    // 4. Forces — thrust along drone's local +Y to world
    _thrustLocal.copy(UP_LOCAL).multiplyScalar(state.throttle * MAX_THRUST);
    _thrustWorld.copy(_thrustLocal).applyQuaternion(state.quaternion);

    const ax = _thrustWorld.x - state.velocity.x * DRAG_LINEAR;
    const ay = _thrustWorld.y - GRAVITY          - state.velocity.y * DRAG_LINEAR;
    const az = _thrustWorld.z - state.velocity.z * DRAG_LINEAR;

    // 5. Integrate velocity + position
    state.velocity.x += ax * dt;
    state.velocity.y += ay * dt;
    state.velocity.z += az * dt;

    state.position.x += state.velocity.x * dt;
    state.position.y += state.velocity.y * dt;
    state.position.z += state.velocity.z * dt;

    // 6. Prop phase
    state.propPhase += (8 + state.throttle * 70) * dt;

    // 7. Ground clamp
    if (state.position.y < 0.3) {
      state.position.y = 0.3;
      if (state.velocity.y < 0) state.velocity.y = 0;
    }
  }

  function resetToHover(pos, heading, throttle = HOVER_THROTTLE) {
    state.position.copy(pos);
    state.velocity.set(0, 0, 0);
    state.quaternion.copy(quatFromHeading(heading));
    state.angularVelocity.set(0, 0, 0);
    state.throttle = throttle;
  }

  function getForward(out) {
    out.set(0, 0, -1).applyQuaternion(state.quaternion);
    return out;
  }

  return { state, step, resetToHover, getForward };
}
