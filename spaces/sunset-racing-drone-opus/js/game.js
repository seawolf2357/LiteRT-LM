// ═══════════════════════════════════════════════════════
//  GAME — main entry. Wires together the three.js scene,
//  drone physics, gate track, HUD, sound, and input.
//  Run-loop uses a fixed-timestep physics update with
//  accumulator so frame-rate variance doesn't desync the
//  simulation.
// ═══════════════════════════════════════════════════════
import * as THREE from 'three';
import {
  TOTAL_LAPS, FOV_FPV, FOV_CHASE, CAMERA_TILT,
  CHASE_DIST, CHASE_HEIGHT, OFF_COURSE_RADIUS, RESET_HOVER_Y,
  clamp, smoothDamp,
} from './config.js';
import { createDrone }        from './drone-physics.js';
import { createDroneMesh }    from './drone-mesh.js';
import { createGateTrack }    from './gate-track.js';
import { createEnvironment }  from './environment.js';
import { createHUD }          from './hud.js';
import { createDroneSound }   from './sound.js';

// ── Scene setup ─────────────────────────────────────────
const canvas = document.getElementById('game');
const renderer = new THREE.WebGLRenderer({
  canvas, antialias: true, powerPreference: 'high-performance',
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight, false);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.1;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(
  FOV_FPV, window.innerWidth / window.innerHeight, 0.1, 1200
);
camera.position.set(0, 8, 50);

// ── World + drone + track ───────────────────────────────
const env = createEnvironment(scene, renderer);
const droneMesh = createDroneMesh();
scene.add(droneMesh.group);

const spawnPos = new THREE.Vector3(0, 6, 56);
const drone = createDrone(spawnPos, Math.PI); // facing -Z (into the course)
const track = createGateTrack(scene);

// ── HUD + sound ─────────────────────────────────────────
const hud = createHUD();
const sound = createDroneSound();

// ── Game state ──────────────────────────────────────────
const gameState = {
  phase: 'countdown', // 'countdown' | 'racing' | 'finished' | 'paused'
  countdown: 3.2,
  lap: 1,
  raceStartTime: 0,
  currentLapStartTime: 0,
  bestLapTime: null,
  lastLapTime: null,
  lapSplits: [], // times at which each gate was passed on the best lap
  currentSplits: [],
  finishTime: null,
  cameraMode: 'fpv', // 'fpv' | 'chase'
  offCourseFlash: 0,
};

// ── Input: keyboard ─────────────────────────────────────
const keys = Object.create(null);
window.addEventListener('keydown', (e) => {
  keys[e.code] = true;
  if (e.code === 'KeyP' || e.code === 'Escape') togglePause();
  if (e.code === 'KeyR') resetRace();
  if (e.code === 'Tab') {
    e.preventDefault();
    gameState.cameraMode = gameState.cameraMode === 'fpv' ? 'chase' : 'fpv';
    camera.fov = gameState.cameraMode === 'fpv' ? FOV_FPV : FOV_CHASE;
    camera.updateProjectionMatrix();
  }
  if (e.code === 'KeyF') {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen();
    else document.exitFullscreen();
  }
  // Resume AudioContext on first real key.
  sound.start();
});
window.addEventListener('keyup', (e) => { keys[e.code] = false; });

// ── Input: touch virtual sticks (mobile) ────────────────
const touchInput = { lx: 0, ly: 0, rx: 0, ry: 0 };
function setupTouchSticks() {
  if (!('ontouchstart' in window) && !navigator.maxTouchPoints) return;

  const style = document.createElement('style');
  style.textContent = `
    .tstick { position: fixed; bottom: 24px; width: 140px; height: 140px;
      border-radius: 50%; background: rgba(255,255,255,0.08);
      border: 2px solid rgba(255,255,255,0.25); z-index: 200;
      backdrop-filter: blur(4px); touch-action: none; }
    .tstick.left  { left: 20px; }
    .tstick.right { right: 20px; }
    .tstick .knob { position: absolute; left: 50%; top: 50%;
      width: 56px; height: 56px; margin-left: -28px; margin-top: -28px;
      border-radius: 50%; background: rgba(255,255,255,0.85);
      box-shadow: 0 0 16px rgba(255,255,255,0.5); pointer-events: none; }
    .tstick .label { position: absolute; top: -22px; left: 50%;
      transform: translateX(-50%); font: 700 10px Orbitron, sans-serif;
      color: #fff; letter-spacing: 2px; opacity: 0.55; }
    @media (hover: hover) and (pointer: fine) { .tstick { display: none; } }
  `;
  document.head.appendChild(style);

  function makeStick(side, label, onMove) {
    const el = document.createElement('div');
    el.className = `tstick ${side}`;
    el.innerHTML = `<div class="label">${label}</div><div class="knob"></div>`;
    document.body.appendChild(el);
    const knob = el.querySelector('.knob');
    let activeId = null;
    const r = 50;

    function onStart(e) {
      const t = e.changedTouches[0];
      activeId = t.identifier;
      sound.start();
    }
    function onMoveEv(e) {
      for (const t of e.changedTouches) {
        if (t.identifier !== activeId) continue;
        const rect = el.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        let dx = t.clientX - cx;
        let dy = t.clientY - cy;
        const len = Math.hypot(dx, dy);
        if (len > r) { dx = dx * r / len; dy = dy * r / len; }
        knob.style.transform = `translate(${dx}px, ${dy}px)`;
        onMove(dx / r, dy / r);
      }
    }
    function onEnd(e) {
      for (const t of e.changedTouches) {
        if (t.identifier !== activeId) continue;
        activeId = null;
        knob.style.transform = '';
        onMove(0, 0);
      }
    }
    el.addEventListener('touchstart', onStart, { passive: true });
    el.addEventListener('touchmove', onMoveEv, { passive: true });
    el.addEventListener('touchend', onEnd, { passive: true });
    el.addEventListener('touchcancel', onEnd, { passive: true });
  }
  // Left: throttle (y) + yaw (x). Right: pitch (y) + roll (x).
  makeStick('left',  'THR / YAW',   (x, y) => { touchInput.lx = x;  touchInput.ly = -y; });
  makeStick('right', 'PITCH / ROLL', (x, y) => { touchInput.rx = x; touchInput.ry = -y; });
}
setupTouchSticks();

// ── Input sampling ──────────────────────────────────────
function sampleInput() {
  // Keyboard: W/S pitch, A/D yaw, Q/E roll, Space/Shift throttle
  let pitch = 0, yaw = 0, roll = 0, throttleDelta = 0;
  if (keys['KeyW']) pitch -= 1;
  if (keys['KeyS']) pitch += 1;
  if (keys['KeyA']) yaw   += 1;
  if (keys['KeyD']) yaw   -= 1;
  if (keys['KeyQ']) roll  += 1;
  if (keys['KeyE']) roll  -= 1;
  if (keys['Space']) throttleDelta += 1;
  if (keys['ShiftLeft'] || keys['ShiftRight']) throttleDelta -= 1;

  // Touch sticks add on top of keyboard.
  pitch += touchInput.ry;
  yaw   += touchInput.lx * -1;
  roll  += touchInput.rx;
  throttleDelta += touchInput.ly;

  return {
    pitch: clamp(pitch, -1, 1),
    yaw:   clamp(yaw,   -1, 1),
    roll:  clamp(roll,  -1, 1),
    throttleDelta: clamp(throttleDelta, -1, 1),
  };
}

// ── Camera follow ───────────────────────────────────────
const cameraOffset = new THREE.Vector3();
const cameraLookAt = new THREE.Vector3();
const tiltQuat     = new THREE.Quaternion().setFromAxisAngle(
  new THREE.Vector3(1, 0, 0), -CAMERA_TILT
);
const fpvLocalOffset = new THREE.Vector3(0, 0.2, 0);

function updateCamera(dt) {
  if (gameState.cameraMode === 'fpv') {
    // Lock camera to drone with slight forward tilt.
    cameraOffset.copy(fpvLocalOffset).applyQuaternion(drone.state.quaternion);
    camera.position.copy(drone.state.position).add(cameraOffset);
    const targetQuat = drone.state.quaternion.clone().multiply(tiltQuat);
    camera.quaternion.slerp(targetQuat, 0.35);
  } else {
    // Chase cam: trail behind the drone, look at it.
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(drone.state.quaternion);
    const desired = drone.state.position.clone()
      .sub(fwd.clone().multiplyScalar(CHASE_DIST))
      .add(new THREE.Vector3(0, CHASE_HEIGHT, 0));
    camera.position.x = smoothDamp(camera.position.x, desired.x, 0.12, dt);
    camera.position.y = smoothDamp(camera.position.y, desired.y, 0.12, dt);
    camera.position.z = smoothDamp(camera.position.z, desired.z, 0.12, dt);
    cameraLookAt.copy(drone.state.position).add(fwd.clone().multiplyScalar(4));
    camera.lookAt(cameraLookAt);
  }
}

// ── Race logic ──────────────────────────────────────────
function resetRace() {
  drone.resetToHover(spawnPos, Math.PI);
  track.resetForLap();
  gameState.phase = 'countdown';
  gameState.countdown = 3.2;
  gameState.lap = 1;
  gameState.currentSplits = [];
  gameState.finishTime = null;
  gameState.offCourseFlash = 0;
  hideResults();
}

function resetToCheckpoint() {
  // Snap back to just before the next gate with a small offset.
  const next = track.getNextGate();
  if (!next) return;
  const back = next.normal.clone().multiplyScalar(14);
  const pos = next.position.clone().add(back);
  pos.y = Math.max(pos.y, RESET_HOVER_Y);
  // Heading = toward gate
  const heading = Math.atan2(-next.normal.x, -next.normal.z);
  drone.resetToHover(pos, heading);
  gameState.offCourseFlash = 1.5;
}

function togglePause() {
  if (gameState.phase === 'racing') {
    gameState.phase = 'paused';
    sound.pause();
  } else if (gameState.phase === 'paused') {
    gameState.phase = 'racing';
    sound.resume();
  }
}

// ── Pass-through & lap completion handling ──────────────
function onGatePassed(gate) {
  const now = performance.now() / 1000;
  const lapTime = now - gameState.currentLapStartTime;
  gameState.currentSplits.push(lapTime);

  // Last gate of the lap: close the lap.
  if (track.getNextGateIndex() >= track.getGateCount()) {
    gameState.lastLapTime = lapTime;
    // New best?
    if (gameState.bestLapTime === null || lapTime < gameState.bestLapTime) {
      gameState.bestLapTime = lapTime;
      gameState.lapSplits = gameState.currentSplits.slice();
      showGoldToast('NEW BEST LAP!');
    }
    gameState.currentSplits = [];
    gameState.currentLapStartTime = now;

    if (gameState.lap >= TOTAL_LAPS) {
      gameState.phase = 'finished';
      gameState.finishTime = now - gameState.raceStartTime;
      showResults();
    } else {
      gameState.lap++;
      track.resetForLap();
      env.advanceSun(gameState.lap - 1);
    }
  }
}

// ── Toast & result shell ────────────────────────────────
function showGoldToast(text) {
  const el = document.createElement('div');
  el.textContent = text;
  el.style.cssText = `
    position: fixed; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    font: 900 44px Orbitron, sans-serif;
    color: #ffd700;
    text-shadow: 0 0 30px #ffd700, 0 4px 18px rgba(0,0,0,0.8);
    letter-spacing: 6px;
    pointer-events: none; z-index: 400;
    animation: toastGoldIn 2.0s ease-out forwards;
  `;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2100);
}

let resultsEl = null;
function showResults() {
  if (resultsEl) return;
  resultsEl = document.createElement('div');
  resultsEl.style.cssText = `
    position: fixed; inset: 0; z-index: 500;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    background: radial-gradient(ellipse at center, rgba(30,8,40,0.92), rgba(5,5,18,0.96));
    font-family: Orbitron, sans-serif; color: #fff;
    backdrop-filter: blur(6px);
  `;
  const t = gameState.finishTime;
  const best = gameState.bestLapTime;
  resultsEl.innerHTML = `
    <div style="font-weight:900;font-size:72px;letter-spacing:10px;text-shadow:0 0 40px rgba(255,160,80,0.8);">FINISHED</div>
    <div style="font-weight:700;font-size:14px;letter-spacing:4px;opacity:0.65;margin-top:4px;">TOTAL TIME</div>
    <div style="font-weight:900;font-size:48px;margin-top:6px;">${formatTime(t)}</div>
    <div style="font-weight:700;font-size:14px;letter-spacing:4px;opacity:0.65;margin-top:24px;">BEST LAP</div>
    <div style="font-weight:900;font-size:32px;color:#ffd700;margin-top:4px;text-shadow:0 0 20px rgba(255,215,0,0.6);">★ ${formatTime(best)}</div>
    <div id="retry-btn" style="margin-top:42px;padding:14px 42px;border:2px solid rgba(255,255,255,0.6);border-radius:4px;font-weight:900;font-size:16px;letter-spacing:4px;cursor:pointer;">PRESS R TO RETRY</div>
  `;
  document.body.appendChild(resultsEl);
  resultsEl.querySelector('#retry-btn').addEventListener('click', resetRace);
}
function hideResults() {
  if (resultsEl) { resultsEl.remove(); resultsEl = null; }
}

function formatTime(s) {
  if (s === null || !isFinite(s)) return '--:--.---';
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  const whole = Math.floor(sec);
  const ms = Math.round((sec - whole) * 1000);
  return `${m}:${String(whole).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

// ── Countdown overlay ───────────────────────────────────
const countdownEl = document.createElement('div');
countdownEl.style.cssText = `
  position: fixed; top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font: 900 180px Orbitron, sans-serif; color: #fff;
  text-shadow: 0 0 60px rgba(255,106,61,0.9), 0 10px 40px rgba(0,0,0,0.9);
  pointer-events: none; z-index: 250; opacity: 0;
`;
document.body.appendChild(countdownEl);
let lastCountdownDigit = -1;
function updateCountdown() {
  if (gameState.phase !== 'countdown') {
    countdownEl.style.opacity = '0';
    return;
  }
  const c = gameState.countdown;
  let text = '';
  let digit = -1;
  if (c > 2) { text = '3'; digit = 3; }
  else if (c > 1) { text = '2'; digit = 2; }
  else if (c > 0) { text = '1'; digit = 1; }
  else { text = 'GO'; digit = 0; }
  if (digit !== lastCountdownDigit) {
    lastCountdownDigit = digit;
    countdownEl.textContent = text;
    countdownEl.style.opacity = '1';
    countdownEl.style.animation = 'none';
    void countdownEl.offsetWidth;
    countdownEl.style.animation = 'countdownPop 0.5s ease-out';
  }
}

// ── Resize ──────────────────────────────────────────────
window.addEventListener('resize', () => {
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
});

// ── Main loop ───────────────────────────────────────────
const FIXED_DT = 1 / 120;
let accumulator = 0;
let lastTime = performance.now() / 1000;
const prevPos = new THREE.Vector3();

function loop() {
  requestAnimationFrame(loop);
  const now = performance.now() / 1000;
  let dt = now - lastTime;
  lastTime = now;
  if (dt > 0.1) dt = 0.1; // cap after tab-switch
  accumulator += dt;

  // Countdown phase
  if (gameState.phase === 'countdown') {
    gameState.countdown -= dt;
    updateCountdown();
    if (gameState.countdown <= -0.5) {
      gameState.phase = 'racing';
      gameState.raceStartTime = now;
      gameState.currentLapStartTime = now;
      sound.start();
    }
    // Still render the scene behind the countdown.
    renderer.render(scene, camera);
    return;
  }

  // Pause phase: just draw what we had.
  if (gameState.phase === 'paused') {
    renderer.render(scene, camera);
    return;
  }

  // Fixed-step physics
  prevPos.copy(drone.state.position);
  if (gameState.phase === 'racing') {
    const input = sampleInput();
    while (accumulator >= FIXED_DT) {
      drone.step(input, FIXED_DT);
      accumulator -= FIXED_DT;
    }
  } else if (gameState.phase === 'finished') {
    // Idle drift — zero input, gravity still wins but throttle hold keeps it aloft.
    const idle = { pitch: 0, yaw: 0, roll: 0, throttleDelta: 0 };
    while (accumulator >= FIXED_DT) {
      drone.step(idle, FIXED_DT);
      accumulator -= FIXED_DT;
    }
  }

  // Sync visual mesh
  droneMesh.group.position.copy(drone.state.position);
  droneMesh.group.quaternion.copy(drone.state.quaternion);
  droneMesh.spinProps(drone.state.propPhase);

  // Gate pass detection (only while racing)
  if (gameState.phase === 'racing') {
    const passed = track.update(prevPos, drone.state.position, dt);
    if (passed) onGatePassed(passed);

    // Off-course detection: are we crazy far from the next gate?
    const next = track.getNextGate();
    if (next) {
      const d2 = drone.state.position.distanceToSquared(next.position);
      if (d2 > OFF_COURSE_RADIUS * OFF_COURSE_RADIUS) resetToCheckpoint();
    }
  } else {
    track.update(prevPos, drone.state.position, dt); // still breathe-animate
  }

  // Camera
  updateCamera(dt);

  // Sound
  const speed = drone.state.velocity.length();
  sound.update(drone.state.throttle, speed, dt);

  // HUD
  const euler = new THREE.Euler().setFromQuaternion(drone.state.quaternion, 'YXZ');
  const pitchRad = euler.x;
  const rollRad  = euler.z;
  const altitude = drone.state.position.y;
  const curLapTime = gameState.phase === 'racing'
    ? now - gameState.currentLapStartTime : 0;

  // Real-time delta vs best: compare current split to best split at same gate index.
  let delta = null;
  if (gameState.bestLapTime !== null && gameState.phase === 'racing') {
    const idx = track.getNextGateIndex();
    if (idx > 0 && gameState.lapSplits[idx - 1] !== undefined) {
      delta = gameState.currentSplits[idx - 1] - gameState.lapSplits[idx - 1];
    }
  }

  if (gameState.offCourseFlash > 0) gameState.offCourseFlash -= dt;

  hud.draw({
    speed, throttle: drone.state.throttle, altitude,
    pitch: pitchRad, roll: rollRad,
    lap: gameState.lap, totalLaps: TOTAL_LAPS,
    gateIdx: track.getNextGateIndex(),
    totalGates: track.getGateCount(),
    currentLapTime: curLapTime,
    bestLapTime: gameState.bestLapTime,
    deltaVsBest: delta,
    offCourseFlash: gameState.offCourseFlash > 0,
  });

  renderer.render(scene, camera);
}

// ── Kick off ────────────────────────────────────────────
env.advanceSun(0);
requestAnimationFrame(() => {
  const veil = document.getElementById('loading-veil');
  if (veil) {
    veil.classList.add('hidden');
    setTimeout(() => veil.remove(), 800);
  }
  loop();
});
