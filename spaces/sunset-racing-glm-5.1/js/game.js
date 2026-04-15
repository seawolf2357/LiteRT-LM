// ═══════════════════════════════════════════════════════
//  GAME — entry point: scene, camera, renderer, input, game loop
// ═══════════════════════════════════════════════════════
import * as THREE from 'three';
import { MAX_SPEED, ACCEL, BRAKE, DRAG, TURN_RATE, GRIP_TRACK, GRIP_GRASS, TRACK_WIDTH } from './config.js';
import { frame, nearestTrackT, trackLen } from './track.js';
import { createSky, createLights, createGround } from './environment.js';
import { createRoadSurface, createDirtStrips, createCurbs, createCenterDashes, createStartFinish, createSectorMarkers, createBarriers } from './track-meshes.js';
import { placeScenery } from './scenery.js';
import { createCar } from './cars.js';
import { createAICars, updateAI } from './ai.js';
import { createSmokeSystem, createDustSystem, createSpeedLineSystem } from './particles.js';
import { createTireMarkSystem } from './tire-marks.js';
import { createMinimap } from './minimap.js';
import { createHUD } from './hud.js';
import { TelemetrySession, scheduleSave, loadBestLap, saveBestLap, loadGhost, saveGhost } from './telemetry.js';
import { createSoundEngine } from './sound.js';
import { createMusic } from './music.js';
import { createAISound } from './ai-sound.js';

// ══ GLOBALS ══
const G = {
  player: { x: 0, z: 0, heading: 0, velHeading: 0, speed: 0, lap: 0, onTrack: true },
  keys: {},
  lapMarker: 0,
};
window.G = G;
window.keys = G.keys;
window.trackCurve = (await import('./track.js')).trackCurve;
window.trackLen = trackLen;
window.frameFn = frame;
window.nearestTrackT = nearestTrackT;

// ══ RENDERER & SCENE ══
const canvas = document.getElementById('game');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.3;

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0xc8ddf0, 0.0022);

const camera = new THREE.PerspectiveCamera(65, window.innerWidth / window.innerHeight, 0.5, 600);

// ══ BUILD WORLD ══
createSky(scene);
const { sun } = createLights(scene);
createGround(scene, renderer);
createRoadSurface(scene, renderer);
createDirtStrips(scene, renderer);
createCurbs(scene);
createCenterDashes(scene);
createStartFinish(scene);
createSectorMarkers(scene);
createBarriers(scene);
placeScenery(scene);

const playerCar = createCar(0xff2200);
scene.add(playerCar);

const aiCars = createAICars(scene);
window.aiCars = aiCars;
window.scene = scene;
window.__playerFinished = () => playerFinished;
window.__raceResults = () => raceResults;
window.__raceEndTimer = () => raceEndTimer;
window.__raceState = () => raceState;
window.__resultsShown = () => resultsShown;
const smoke = createSmokeSystem(scene);
const dust = createDustSystem(scene);
const speedLines = createSpeedLineSystem(scene);
const tireMarks = createTireMarkSystem(scene);

const minimap = createMinimap(aiCars);
minimap.setFrame(frame);

const hud = createHUD();
const telemetry = new TelemetrySession();
let sound = null;
let music = null;
let aiSound = null;

// ══ BEST LAP & GHOST CAR ══
let bestLapRecord = loadBestLap();           // { time, lapNumber, ... } or null
let bestLapTime = bestLapRecord ? bestLapRecord.time : null;
let currentLapStart = 0;                     // elapsed time when current lap started
let currentLapTime = 0;                      // elapsed - currentLapStart
let lastLapTime = null;                      // most recently completed lap
let currentLapSamples = [];                  // [{t, x, z, heading}, ...] for potential ghost save
let ghostData = loadGhost();                 // saved best-lap replay
let ghostCar = null;                         // THREE.Group for ghost visualization
let ghostEnabled = true;                     // user toggle (G key)

// ══ NITRO ══
let nitroCharge = 1.0;                       // 0..1
let nitroActive = false;
const NITRO_DURATION = 2.5;                  // seconds of boost
const NITRO_RECHARGE = 12;                   // seconds to full recharge
const NITRO_MULT = 1.35;                     // top-speed multiplier while active
const NITRO_ACCEL_MULT = 1.6;                // acceleration multiplier
let nitroTimer = 0;                          // remaining boost time

// ══ CAMERA MODES ══
const CAM_THIRD = 0;
const CAM_COCKPIT = 1;
const CAM_TOP = 2;
const CAM_NAMES = ['THIRD-PERSON', 'COCKPIT', 'TOP-DOWN'];
let cameraMode = CAM_THIRD;

// ══ PAUSE ══
let paused = false;

// ══ TOUCH CONTROLS (mobile) ══
const touchState = { accel: false, brake: false, left: false, right: false, drift: false, nitro: false };

// ══ GHOST CAR (translucent replay of best lap) ══
function createGhostCar() {
  const g = new THREE.Group();
  const mat = new THREE.MeshBasicMaterial({ color: 0x00eaff, transparent: true, opacity: 0.35 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(2, 0.7, 4), mat);
  body.position.y = 0.6;
  g.add(body);
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.5, 2), mat);
  cabin.position.set(0, 1.15, -0.3);
  g.add(cabin);
  g.visible = false;
  return g;
}
ghostCar = createGhostCar();
scene.add(ghostCar);

// ══ INPUT ══
window.addEventListener('keydown', (e) => {
  // Start audio on first interaction
  if (!sound) {
    sound = createSoundEngine();
    aiSound = createAISound(sound.ctx, sound.master, sound.noiseBuf);
    for (const ai of aiCars) ai.soundIdx = aiSound.addCar();
    music = createMusic(); music.start();
  }

  // Pause/resume (Escape or P) — don't record as game input
  if (e.code === 'Escape' || e.code === 'KeyP') {
    if (raceState === 'racing' || raceState === 'countdown' || paused) {
      togglePause();
      e.preventDefault();
      return;
    }
  }
  // Fullscreen toggle (F) — don't record as game input
  if (e.code === 'KeyF') {
    toggleFullscreen();
    e.preventDefault();
    return;
  }
  // Camera mode (C)
  if (e.code === 'KeyC') {
    cameraMode = (cameraMode + 1) % 3;
    showToast(`CAMERA: ${CAM_NAMES[cameraMode]}`);
    e.preventDefault();
    return;
  }
  // Ghost toggle (G)
  if (e.code === 'KeyG') {
    ghostEnabled = !ghostEnabled;
    ghostCar.visible = ghostEnabled && ghostData !== null && raceState === 'racing';
    showToast(`GHOST: ${ghostEnabled ? 'ON' : 'OFF'}`);
    e.preventDefault();
    return;
  }

  G.keys[e.code] = true;
});
window.addEventListener('keyup', (e) => { G.keys[e.code] = false; });

// ══ RACE STATE ══
const TOTAL_LAPS = 3;
let raceState = 'attract'; // attract → grid → countdown → racing → finished
let countdownStartTime = 0;
let raceStartTime = 0;
let raceResults = [];
let playerFinished = false;
let playerFinishTime = 0;
let playerHasPassedHalf = false;
let raceEndTimer = -1;
let resultsShown = false;
let gridTimer = 1.5;
let attractAIIdx = 0; // which AI car to follow in attract mode
let attractT = 0; // track position for attract AI

// Hide player car during attract mode
playerCar.visible = false;

// ══ POSITION ALL CARS ON GRID ══
function positionOnGrid() {
  const { point: startPt, tangent: startTan, side: startSide } = frame(0);
  const startHeading = Math.atan2(startTan.x, startTan.z);

  // 2-wide grid: AI in front, player back-left (like real racing)
  const gridSlots = [
    { row: 0, col: -1, type: 'ai', idx: 0 },   // BLUE - pole left
    { row: 0, col:  1, type: 'ai', idx: 1 },   // GOLD - pole right
    { row: 1, col: -1, type: 'ai', idx: 2 },   // JADE - 2nd row left
    { row: 1, col:  1, type: 'ai', idx: 3 },   // BLAZE - 2nd row right
    { row: 2, col: -1, type: 'player' },         // YOU - back left
  ];

  const ROW_SPACING = 12 / trackLen;  // ~12 world units between rows (track-t units)
  const COL_OFFSET = 4;

  for (const slot of gridSlots) {
    // Place each row at a different track-t so cars follow the curve
    const rowT = ((0 - slot.row * ROW_SPACING) % 1 + 1) % 1;
    const { point: rowPt, tangent: rowTan, side: rowSide } = frame(rowT);
    const rowHeading = Math.atan2(rowTan.x, rowTan.z);
    const pos = rowPt.clone().add(rowSide.clone().multiplyScalar(slot.col * COL_OFFSET));

    if (slot.type === 'player') {
      G.player.x = pos.x;
      G.player.z = pos.z;
      G.player.heading = rowHeading;
      G.player.velHeading = rowHeading;
      G.player.lap = 0;
      playerCar.position.set(pos.x, 0.05, pos.z);
      playerCar.rotation.set(0, rowHeading, 0);
    } else {
      const ai = aiCars[slot.idx];
      ai.x = pos.x;
      ai.z = pos.z;
      ai.heading = rowHeading;
      ai.velHeading = rowHeading;
      ai.speed = 0;
      ai.impulseX = 0;
      ai.impulseZ = 0;
      ai.lap = 0;
      ai.prevTrackT = 0;
      ai.finished = false;
      ai.finishTime = 0;
      ai.hasPassedHalf = false;
      ai.mesh.position.set(pos.x, 0.05, pos.z);
      ai.mesh.rotation.set(0, rowHeading, 0);
    }
  }
}

// Place AI cars around track for attract mode
function positionForAttract() {
  for (let i = 0; i < aiCars.length; i++) {
    const ai = aiCars[i];
    const t = (0.1 + i * 0.22) % 1; // spread around the track
    const lateral = (i % 2 === 0 ? 0.3 : -0.3); // alternate sides
    const { point, tangent, side } = frame(t);
    const heading = Math.atan2(tangent.x, tangent.z);
    ai.x = point.x + side.x * lateral * 3;
    ai.z = point.z + side.z * lateral * 3;
    ai.heading = heading;
    ai.velHeading = heading;
    ai.speed = 30 + Math.random() * 10; // start with some speed
    ai.lap = 0;
    ai.prevTrackT = t;
    ai._trackT = t;
    ai.finished = false;
    ai.finishTime = 0;
    ai.hasPassedHalf = false;
    ai.impulseX = 0;
    ai.impulseZ = 0;
    ai.mesh.position.set(ai.x, 0.05, ai.z);
    ai.mesh.rotation.set(0, heading, 0);
  }
}
positionForAttract();

// ══ PAUSE OVERLAY ══
const pauseEl = document.createElement('div');
pauseEl.id = 'pause-overlay';
pauseEl.style.cssText = `
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.72);
  display: none; align-items: center; justify-content: center;
  z-index: 400; pointer-events: auto;
  font-family: 'Orbitron', sans-serif;
  backdrop-filter: blur(10px) saturate(120%);
  -webkit-backdrop-filter: blur(10px) saturate(120%);
`;
pauseEl.innerHTML = `
  <div style="text-align:center; color:white;">
    <div style="font-size:72px; font-weight:900; letter-spacing:8px; margin-bottom:36px;
                text-shadow:0 0 40px rgba(255,255,255,0.6);">PAUSED</div>
    <div style="display:flex; flex-direction:column; gap:16px; align-items:center;">
      <button id="pause-resume"  class="pause-btn">RESUME (ESC)</button>
      <button id="pause-restart" class="pause-btn">RESTART (R)</button>
      <button id="pause-camera"  class="pause-btn">CAMERA (C)</button>
      <button id="pause-ghost"   class="pause-btn">GHOST (G)</button>
      <button id="pause-fullscreen" class="pause-btn">FULLSCREEN (F)</button>
    </div>
    <div style="margin-top:40px; font-size:13px; color:rgba(255,255,255,0.5); letter-spacing:2px;">
      WASD/ARROWS · SPACE DRIFT · SHIFT NITRO · P/ESC PAUSE
    </div>
  </div>
`;
const pauseStyle = document.createElement('style');
pauseStyle.textContent = `
  .pause-btn {
    font-family: Orbitron, sans-serif;
    font-weight: 900; font-size: 18px;
    background: rgba(255,255,255,0.08);
    color: white;
    border: 2px solid rgba(255,255,255,0.3);
    padding: 12px 36px;
    letter-spacing: 2px;
    cursor: pointer;
    min-width: 280px;
    text-transform: uppercase;
    outline: none;
    transition: background 0.15s, border-color 0.15s, transform 0.1s, box-shadow 0.15s;
  }
  .pause-btn:hover {
    background: rgba(255,34,0,0.3);
    border-color: #ff4422;
    transform: translateY(-1px);
    box-shadow: 0 6px 18px rgba(255,34,0,0.25);
  }
  .pause-btn:active {
    background: rgba(255,34,0,0.55);
    border-color: #ff6644;
    transform: translateY(0);
    box-shadow: 0 2px 8px rgba(255,34,0,0.3);
  }
  .pause-btn:focus-visible {
    border-color: #00eaff;
    box-shadow: 0 0 0 3px rgba(0,234,255,0.25);
  }
`;
document.head.appendChild(pauseStyle);
document.body.appendChild(pauseEl);

// Pause button handlers (added after function definitions)
setTimeout(() => {
  document.getElementById('pause-resume').onclick = () => togglePause();
  document.getElementById('pause-restart').onclick = () => { togglePause(); restartRace(); };
  document.getElementById('pause-camera').onclick = () => {
    cameraMode = (cameraMode + 1) % 3;
    showToast(`CAMERA: ${CAM_NAMES[cameraMode]}`);
  };
  document.getElementById('pause-ghost').onclick = () => {
    ghostEnabled = !ghostEnabled;
    ghostCar.visible = ghostEnabled && ghostData !== null && raceState === 'racing';
    showToast(`GHOST: ${ghostEnabled ? 'ON' : 'OFF'}`);
  };
  document.getElementById('pause-fullscreen').onclick = () => toggleFullscreen();
}, 0);

function togglePause() {
  paused = !paused;
  pauseEl.style.display = paused ? 'flex' : 'none';
  if (paused) {
    if (music && music.pause) music.pause();
  } else {
    if (music && music.resume) music.resume();
    clock.getDelta(); // reset delta so dt doesn't spike
  }
}

// ══ FULLSCREEN ══
function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen().catch(() => {});
  }
}

// ══ TOUCH CONTROLS (mobile) ══
const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
if (isTouchDevice) {
  const touchStyle = document.createElement('style');
  touchStyle.textContent = `
    .touch-btn {
      position: fixed;
      font-family: Orbitron, sans-serif;
      font-weight: 900;
      font-size: 26px;
      background: rgba(0,0,0,0.38);
      color: #fff;
      border: 2px solid rgba(255,255,255,0.45);
      border-radius: 50%;
      width: 72px; height: 72px;
      display: flex; align-items: center; justify-content: center;
      z-index: 150;
      touch-action: manipulation;
      user-select: none; -webkit-user-select: none;
      -webkit-tap-highlight-color: transparent;
      backdrop-filter: blur(6px);
      -webkit-backdrop-filter: blur(6px);
      text-shadow: 0 2px 6px rgba(0,0,0,0.7);
      box-shadow: 0 4px 14px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1);
      transition: transform 0.08s ease-out, background 0.08s ease-out, border-color 0.12s ease-out;
    }
    .touch-btn.wide { width: 96px; border-radius: 14px; font-size: 16px; letter-spacing: 2px; }
    .touch-btn:active { background: rgba(255,34,0,0.5); transform: scale(0.94); }
    .touch-btn.pressed {
      background: rgba(255,34,0,0.65);
      border-color: #ffb0a0;
      transform: scale(0.92);
      box-shadow: 0 0 22px rgba(255,68,34,0.6), inset 0 1px 0 rgba(255,255,255,0.15);
    }
  `;
  document.head.appendChild(touchStyle);

  function makeBtn(label, style, key) {
    const btn = document.createElement('div');
    btn.className = 'touch-btn' + (style.wide ? ' wide' : '');
    btn.textContent = label;
    Object.assign(btn.style, style.css || {});
    btn.addEventListener('touchstart', (e) => { touchState[key] = true; btn.classList.add('pressed'); e.preventDefault(); }, { passive: false });
    btn.addEventListener('touchend',   (e) => { touchState[key] = false; btn.classList.remove('pressed'); e.preventDefault(); }, { passive: false });
    btn.addEventListener('touchcancel',(e) => { touchState[key] = false; btn.classList.remove('pressed'); }, { passive: true });
    document.body.appendChild(btn);
    return btn;
  }
  // Left cluster — steering
  makeBtn('◀', { css: { left: '24px', bottom: '100px' } }, 'left');
  makeBtn('▶', { css: { left: '116px', bottom: '100px' } }, 'right');
  // Right cluster — pedals
  makeBtn('▲', { css: { right: '24px', bottom: '180px' } }, 'accel');
  makeBtn('▼', { css: { right: '24px', bottom: '100px' } }, 'brake');
  // Drift
  makeBtn('DRIFT', { wide: true, css: { right: '116px', bottom: '100px' } }, 'drift');
  // Nitro
  makeBtn('NITRO', { wide: true, css: { right: '116px', bottom: '180px' } }, 'nitro');
}

// ══ TOAST (transient notification) ══
const toastEl = document.createElement('div');
toastEl.style.cssText = `
  position: fixed; top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-family: Orbitron, sans-serif;
  font-weight: 900; font-size: 28px;
  color: #fff;
  text-shadow: 0 0 20px rgba(255,255,255,0.6), 0 2px 8px rgba(0,0,0,0.9);
  z-index: 350; pointer-events: none;
  opacity: 0; transition: opacity 0.2s;
`;
document.body.appendChild(toastEl);
let toastTimer = 0;
function showToast(msg, variant) {
  toastEl.textContent = msg;
  toastEl.style.opacity = '1';
  // Reset any gold animation/class left over from a previous best-lap toast
  toastEl.classList.remove('toast-gold');
  // offset reflow so re-adding the class restarts the keyframes
  void toastEl.offsetWidth;
  if (variant === 'gold') {
    toastEl.style.color = '#ffd700';
    toastEl.style.fontSize = '42px';
    toastEl.style.letterSpacing = '3px';
    toastEl.style.textShadow = '0 0 36px rgba(255,215,0,0.9), 0 4px 14px rgba(0,0,0,0.9)';
    toastEl.style.animation = 'toastGoldIn 2s ease-out forwards';
    toastTimer = 2;
  } else {
    toastEl.style.color = '#fff';
    toastEl.style.fontSize = '28px';
    toastEl.style.letterSpacing = '0';
    toastEl.style.textShadow = '0 0 20px rgba(255,255,255,0.6), 0 2px 8px rgba(0,0,0,0.9)';
    toastEl.style.animation = 'none';
    toastTimer = 1.2;
  }
}

// ══ COUNTDOWN OVERLAY ══
const countdownEl = document.createElement('div');
countdownEl.style.cssText = `
  position: fixed; top: 25%; left: 50%;
  transform: translate(-50%, -50%);
  font-family: 'Orbitron', sans-serif;
  font-weight: 900; font-size: 200px;
  color: white;
  text-shadow: 0 0 80px rgba(255,255,255,0.6), 0 4px 20px rgba(0,0,0,0.8);
  z-index: 200; pointer-events: none;
  opacity: 0; transition: opacity 0.15s;
`;
document.body.appendChild(countdownEl);

// ══ RESULTS OVERLAY ══
const resultsEl = document.createElement('div');
resultsEl.id = 'results-overlay';
resultsEl.style.cssText = `
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.0);
  display: flex; align-items: center; justify-content: center;
  z-index: 300; pointer-events: none;
  font-family: 'Orbitron', sans-serif;
  transition: background 1s;
`;
document.body.appendChild(resultsEl);

// ══ LAP NOTIFICATION ══
const lapNotifyEl = document.createElement('div');
lapNotifyEl.style.cssText = `
  position: fixed; top: 35%; left: 50%;
  transform: translate(-50%, -50%);
  font-family: 'Orbitron', sans-serif;
  font-weight: 900; font-size: 48px;
  color: #ffd700;
  text-shadow: 0 0 30px rgba(255,215,0,0.6), 0 2px 10px rgba(0,0,0,0.8);
  z-index: 200; pointer-events: none;
  opacity: 0; transition: opacity 0.3s;
`;
document.body.appendChild(lapNotifyEl);
let lapNotifyTimer = 0;

// ══ ATTRACT MODE OVERLAY ══
const attractEl = document.createElement('div');
attractEl.style.cssText = `
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  z-index: 250; pointer-events: none;
  font-family: 'Orbitron', sans-serif;
`;
const attractTitle = document.createElement('div');
attractTitle.style.cssText = `
  font-weight: 900; font-size: clamp(32px, 10vw, 72px); color: #ffffff;
  text-shadow: 0 0 60px rgba(255,60,30,0.8), 0 4px 20px rgba(0,0,0,0.9);
  margin-bottom: 30px; letter-spacing: clamp(2px, 0.8vw, 6px);
  text-align: center; word-break: break-word; max-width: 90vw;
`;
attractTitle.textContent = 'SUNSET RACING';
const attractSub = document.createElement('div');
attractSub.style.cssText = `
  font-weight: 700; font-size: clamp(14px, 3.5vw, 24px); color: rgba(255,255,255,0.9);
  text-shadow: 0 0 20px rgba(255,255,255,0.4), 0 2px 8px rgba(0,0,0,0.8);
  text-align: center; max-width: 90vw;
  animation: attractPulse 1.2s ease-in-out infinite;
`;
attractSub.textContent = 'PRESS SPACE TO RACE';
// Add pulse animation
const attractStyle = document.createElement('style');
attractStyle.textContent = `
  @keyframes attractPulse {
    0%, 100% { opacity: 0.5; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.05); }
  }
`;
document.head.appendChild(attractStyle);
attractEl.appendChild(attractTitle);
attractEl.appendChild(attractSub);
document.body.appendChild(attractEl);

function formatRaceTime(seconds) {
  if (!isFinite(seconds)) return 'DNF';
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  const wholeSecs = Math.floor(secs);
  const ms = Math.floor((secs - wholeSecs) * 1000);
  return `${mins}:${String(wholeSecs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function showResults() {
  raceResults.sort((a, b) => {
    if (a.dnf && !b.dnf) return 1;
    if (!a.dnf && b.dnf) return -1;
    return a.time - b.time;
  });

  const posLabels = ['1ST', '2ND', '3RD', '4TH', '5TH'];
  const posColors = ['#ffd700', '#e0e0e0', '#cd7f32', '#cccccc', '#aaaaaa'];

  let html = '<div style="text-align:center; color:white;">';
  html += '<div style="font-size:52px; margin-bottom:8px; color:#ffd700;">🏁</div>';

  const playerResult = raceResults.find(r => r.name === 'YOU');
  const playerPos = raceResults.indexOf(playerResult) + 1;

  if (playerPos === 1) {
    html += '<div style="font-size:42px; font-weight:900; color:#ffd700; margin-bottom:20px;">YOU WIN!</div>';
  } else {
    html += `<div style="font-size:36px; font-weight:900; color:${posColors[playerPos-1]}; margin-bottom:20px;">${posLabels[playerPos-1]} PLACE</div>`;
  }

  for (let i = 0; i < raceResults.length; i++) {
    const r = raceResults[i];
    const isPlayer = r.name === 'YOU';
    const bg = isPlayer ? 'background:rgba(255,34,0,0.3); border:2px solid #ff2200;' : 'background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1);';
    const carColors = { 'YOU': '#ff2200', 'BLUE': '#3366ff', 'GOLD': '#ffcc00', 'JADE': '#00cc66', 'BLAZE': '#ff6600' };
    html += `<div style="display:flex; align-items:center; justify-content:center; gap:24px; padding:10px 36px; margin:6px auto; max-width:460px; ${bg} border-radius:8px;">`;
    html += `<span style="font-size:28px; font-weight:900; color:${posColors[i]}; min-width:55px;">${posLabels[i]}</span>`;
    html += `<span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:${carColors[r.name] || '#fff'};"></span>`;
    html += `<span style="font-size:22px; font-weight:700; min-width:80px; ${isPlayer ? 'color:#ff4422;' : ''}">${r.name}</span>`;
    html += `<span style="font-size:18px; color:#aaa; min-width:90px;">${r.dnf ? 'DNF' : formatRaceTime(r.time)}</span>`;
    html += '</div>';
  }

  // Best lap for this race + all-time
  if (lastLapTime !== null) {
    html += '<div style="margin-top:24px; display:flex; gap:36px; justify-content:center; font-size:16px;">';
    html += `<div><span style="color:#888;">LAST LAP:</span> <span style="color:#fff; font-weight:700;">${formatRaceTime(lastLapTime)}</span></div>`;
    if (bestLapTime !== null) {
      html += `<div><span style="color:#888;">★ BEST:</span> <span style="color:#ffd700; font-weight:700;">${formatRaceTime(bestLapTime)}</span></div>`;
    }
    html += '</div>';
  }

  html += '<div style="margin-top:36px; font-size:15px; color:#666; letter-spacing:3px;">PRESS R TO RESTART · ESC TO PAUSE · C CAMERA · G GHOST</div>';
  html += '</div>';

  resultsEl.innerHTML = html;
  resultsEl.style.background = 'rgba(0,0,0,0.85)';
  resultsEl.style.pointerEvents = 'auto';
}

function startRace() {
  raceState = 'grid';
  gridTimer = 1.5;
  raceResults = [];
  playerFinished = false;
  playerFinishTime = 0;
  playerHasPassedHalf = false;
  raceEndTimer = -1;
  resultsShown = false;
  prevTrackT = 0;
  lapNotifyTimer = 0;

  // Lap timing reset
  currentLapStart = 0;
  currentLapTime = 0;
  lastLapTime = null;
  currentLapSamples = [];

  // Nitro reset
  nitroCharge = 1.0;
  nitroActive = false;
  nitroTimer = 0;

  G.player.speed = 0;
  G.player.impulseX = 0;
  G.player.impulseZ = 0;

  for (const ai of aiCars) {
    ai.speed = 0;
    ai.impulseX = 0;
    ai.impulseZ = 0;
  }

  // Reset sound engines to idle
  if (sound) sound.reset();
  if (aiSound) aiSound.reset();

  positionOnGrid();
  playerCar.visible = true;

  // Hide attract overlay
  attractEl.style.display = 'none';

  resultsEl.innerHTML = '';
  resultsEl.style.background = 'rgba(0,0,0,0.0)';
  resultsEl.style.pointerEvents = 'none';
  countdownEl.style.opacity = '0';
  lapNotifyEl.style.opacity = '0';

  clock.start();
}

function restartRace() {
  raceState = 'grid';
  gridTimer = 1.5;
  raceResults = [];
  playerFinished = false;
  playerFinishTime = 0;
  playerHasPassedHalf = false;
  raceEndTimer = -1;
  resultsShown = false;
  prevTrackT = 0;
  lapNotifyTimer = 0;

  // Lap timing reset
  currentLapStart = 0;
  currentLapTime = 0;
  lastLapTime = null;
  currentLapSamples = [];

  // Nitro reset
  nitroCharge = 1.0;
  nitroActive = false;
  nitroTimer = 0;

  G.player.speed = 0;
  G.player.impulseX = 0;
  G.player.impulseZ = 0;

  for (const ai of aiCars) {
    ai.speed = 0;
    ai.impulseX = 0;
    ai.impulseZ = 0;
  }

  // Reset sound engines to idle
  if (sound) sound.reset();
  if (aiSound) aiSound.reset();

  positionOnGrid();
  playerCar.visible = true;

  resultsEl.innerHTML = '';
  resultsEl.style.background = 'rgba(0,0,0,0.0)';
  resultsEl.style.pointerEvents = 'none';
  countdownEl.style.opacity = '0';
  lapNotifyEl.style.opacity = '0';

  clock.start();
}

// R key to restart
window.addEventListener('keydown', (e) => {
  // Space to start from attract, or R to restart
  if (e.code === 'Space' && raceState === 'attract') {
    startRace();
  }
  if (e.code === 'KeyR' && (raceState === 'finished' || raceState === 'racing' || raceState === 'countdown' || raceState === 'grid')) {
    restartRace();
  }
});

// ══ GAME LOOP ══
const clock = new THREE.Clock();
let prevTrackT = 0;

// ── Check if car crosses finish line ──
function checkLapCrossing(prevT, currentT, speed) {
  // Forward lap: prev was near end of lap (>0.9), now near start (<0.1)
  if (prevT > 0.9 && currentT < 0.1 && speed > 0) return 1;
  // Backward lap: prev near start, now near end, going backward
  if (prevT < 0.1 && currentT > 0.9 && speed < 0) return -1;
  return 0;
}

// ── Check if car has passed halfway point (anti-cheat) ──
function updateHalfPassed(currentT, car) {
  if (currentT > 0.4 && currentT < 0.6) {
    car.hasPassedHalf = true;
  }
}

// ── Calculate race position (1st = most progress) ──
function getPosition(playerT) {
  // Total progress = completed laps + current track position
  const playerProgress = G.player.lap + playerT;
  let pos = 1;
  for (const ai of aiCars) {
    const aiProgress = ai.lap + ai._trackT;
    if (aiProgress > playerProgress) pos++;
  }
  return pos;
}

// ── Player physics (extracted so we can skip it during grid/countdown) ──
function updatePlayerPhysics(dt) {
  const p = G.player;

  const nearest = nearestTrackT(p.x, p.z);
  const onRoad = nearest.dist < TRACK_WIDTH / 2;
  p.onTrack = onRoad;

  // Combine keyboard + touch input
  const keyAccel  = G.keys['KeyW'] || G.keys['ArrowUp']    || touchState.accel;
  const keyBrake  = G.keys['KeyS'] || G.keys['ArrowDown']  || touchState.brake;
  const keyLeft   = G.keys['KeyA'] || G.keys['ArrowLeft']  || touchState.left;
  const keyRight  = G.keys['KeyD'] || G.keys['ArrowRight'] || touchState.right;
  const handbrake = G.keys['Space'] || touchState.drift || false;
  const nitroKey  = G.keys['ShiftLeft'] || G.keys['ShiftRight'] || touchState.nitro;

  // ── Nitro: activate if pressed and have charge ──
  if (nitroKey && !nitroActive && nitroCharge >= 0.25) {
    nitroActive = true;
    nitroTimer = NITRO_DURATION * nitroCharge;  // proportional to charge
  }
  if (nitroActive) {
    nitroTimer -= dt;
    nitroCharge = Math.max(0, nitroCharge - dt / NITRO_DURATION);
    if (nitroTimer <= 0 || nitroCharge <= 0) {
      nitroActive = false;
      nitroTimer = 0;
    }
  } else {
    nitroCharge = Math.min(1, nitroCharge + dt / NITRO_RECHARGE);
  }

  const accelNow = nitroActive ? ACCEL * NITRO_ACCEL_MULT : ACCEL;
  const maxNow = nitroActive ? MAX_SPEED * NITRO_MULT : MAX_SPEED;

  if (keyAccel) p.speed += accelNow * dt;
  else if (keyBrake) p.speed -= BRAKE * dt;
  else {
    if (p.speed > 0) p.speed = Math.max(0, p.speed - DRAG * dt);
    else p.speed = Math.min(0, p.speed + DRAG * dt);
  }
  if (handbrake && Math.abs(p.speed) > 2) {
    const hbDrag = 18;
    if (p.speed > 0) p.speed = Math.max(0, p.speed - hbDrag * dt);
    else p.speed = Math.min(0, p.speed + hbDrag * dt);
  }

  if (!onRoad) {
    const grassDrag = 25;
    p.speed *= Math.max(0, 1 - grassDrag * dt / Math.max(Math.abs(p.speed), 8));
  }

  p.speed = THREE.MathUtils.clamp(p.speed, -MAX_SPEED * 0.3, maxNow);

  const absSpeed = Math.abs(p.speed);
  const steerInput = keyLeft ? 1 : (keyRight ? -1 : 0);

  const turnAuthority = Math.min(absSpeed / 12, 1) * Math.max(0.45, 1 - (absSpeed / MAX_SPEED) * 0.55);
  const isBraking = (G.keys['KeyS'] || G.keys['ArrowDown']) && p.speed > 2;
  const brakeTurnBonus = isBraking ? 1.45 : 1.0;
  const handbrakeTurnBonus = handbrake ? 1.8 : 1.0;

  const turnDelta = steerInput * TURN_RATE * turnAuthority * brakeTurnBonus * handbrakeTurnBonus * dt;
  p.heading += turnDelta;

  let grip = onRoad ? GRIP_TRACK : GRIP_GRASS;
  if (handbrake) grip *= 0.35;

  let velHeadingDiff = p.heading - p.velHeading;
  while (velHeadingDiff > Math.PI) velHeadingDiff -= 2 * Math.PI;
  while (velHeadingDiff < -Math.PI) velHeadingDiff += 2 * Math.PI;
  p.velHeading += velHeadingDiff * grip * 5 * dt;
  while (p.velHeading > Math.PI) p.velHeading -= 2 * Math.PI;
  while (p.velHeading < -Math.PI) p.velHeading += 2 * Math.PI;

  const moveDir = new THREE.Vector3(Math.sin(p.velHeading), 0, Math.cos(p.velHeading));
  p.x += moveDir.x * p.speed * dt;
  p.z += moveDir.z * p.speed * dt;

  const surfaceFrame = frame(nearest.t);
  const surfaceY = surfaceFrame.point.y + 0.05;
  playerCar.position.set(p.x, surfaceY, p.z);
  playerCar.rotation.y = p.heading;

  // Front wheel visual
  const frontWheels = playerCar.userData.frontWheels;
  if (frontWheels) {
    const maxSteerAngle = 0.44 * Math.max(0.35, 1 - (absSpeed / MAX_SPEED) * 0.5);
    const targetSteerAngle = steerInput * maxSteerAngle;
    const currentSteer = frontWheels[0].rotation.y;
    const newSteer = THREE.MathUtils.lerp(currentSteer, targetSteerAngle, 8 * dt);
    for (const fw of frontWheels) fw.rotation.y = newSteer;
  }

  // Drift visuals
  const driftAngle = (() => {
    let d = p.heading - p.velHeading;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    return d;
  })();
  const targetRoll = driftAngle * 0.4;
  playerCar.rotation.z = THREE.MathUtils.lerp(playerCar.rotation.z, targetRoll, 5 * dt);
  const targetPitch = (G.keys['KeyW'] || G.keys['ArrowUp']) ? -0.03 :
                      (G.keys['KeyS'] || G.keys['ArrowDown']) ? 0.04 : 0;
  playerCar.rotation.x = THREE.MathUtils.lerp(playerCar.rotation.x, targetPitch * (p.speed / MAX_SPEED), 5 * dt);

  // Brake lights
  const isBrakingOrReversing = (G.keys['KeyS'] || G.keys['ArrowDown']) || handbrake || p.speed < -1;
  const tlm = playerCar.userData.tailLightMat;
  if (tlm) {
    tlm.emissive.setHex(isBrakingOrReversing ? 0xff0000 : 0x000000);
    tlm.emissiveIntensity = isBrakingOrReversing ? 1.5 : 0;
  }

  // Tire marks
  const absDrift = Math.abs(driftAngle);
  const isDrifting = absDrift > 0.15 && absSpeed > 3;
  const isHardBraking = handbrake && absSpeed > 3;
  const isAggressiveTurn = absDrift > 0.08 && absSpeed > 10 && onRoad;
  if (isDrifting || isHardBraking || isAggressiveTurn) {
    const intensity = Math.min(1, (absSpeed / MAX_SPEED) * (absDrift / 0.5 + 0.3));
    const rearOffset = -1.3;
    const rearX = p.x + moveDir.x * rearOffset;
    const rearZ = p.z + moveDir.z * rearOffset;
    const rightX = Math.cos(p.heading);
    const rightZ = -Math.sin(p.heading);
    const sideDist = 1.1;
    tireMarks.addMark(rearX - rightX * sideDist, rearZ - rightZ * sideDist, p.heading, intensity, -1, 'player');
    tireMarks.addMark(rearX + rightX * sideDist, rearZ + rightZ * sideDist, p.heading, intensity, 1, 'player');
  } else {
    tireMarks.breakChain('player');
  }

  // Particles
  if ((absSpeed > 15 && absDrift > 0.2) || (absSpeed > 25 && absDrift > 0.1)) {
    const behindOffset = moveDir.clone().multiplyScalar(-2);
    for (const side of [-1.2, 1.2]) {
      const sideVec = new THREE.Vector3(moveDir.z, 0, -moveDir.x).multiplyScalar(side);
      smoke.emit(
        p.x + behindOffset.x + sideVec.x, 0.2, p.z + behindOffset.z + sideVec.z,
        (Math.random() - 0.5) * 3, 1.5 + Math.random(), (Math.random() - 0.5) * 3
      );
    }
  }
  if (!onRoad && Math.abs(p.speed) > 5 && Math.random() < 0.4) {
    const behindOffset = moveDir.clone().multiplyScalar(-1.5);
    dust.emit(p.x + behindOffset.x + (Math.random() - 0.5), 0.3, p.z + behindOffset.z + (Math.random() - 0.5));
  }

  return { nearest, absSpeed, moveDir, driftAngle };
}

function update() {
  // Pause: render only, no physics
  if (paused) {
    clock.getDelta();  // drain to prevent dt spike on resume
    renderer.render(scene, camera);
    return;
  }

  const dt = Math.min(clock.getDelta(), 0.05);
  const p = G.player;
  const elapsed = clock.elapsedTime;

  // Toast fade
  if (toastTimer > 0) {
    toastTimer -= dt;
    if (toastTimer <= 0) toastEl.style.opacity = '0';
  }

  // ══════════════════════════════════════════
  //  STATE: ATTRACT — AI car racing, helicopter cam
  // ══════════════════════════════════════════
  if (raceState === 'attract') {
    // Run AI cars around the track
    const fakePlayer = { x: 99999, z: 99999, heading: 0, speed: 0, impulseX: 0, impulseZ: 0 };
    try { updateAI(aiCars, fakePlayer, dt, 'racing'); } catch(e) {}

    // Update AI sound
    if (aiSound) {
      const leadAI = aiCars[attractAIIdx];
      const px = leadAI.x;
      const py = 0;
      const pz = leadAI.z;
      for (const ai of aiCars) {
        if (ai.soundIdx !== undefined) {
          aiSound.updateCar(ai.soundIdx,
            ai.mesh.position.x, ai.mesh.position.y, ai.mesh.position.z,
            ai.speed, px, py, pz, leadAI.heading, dt);
        }
      }
    }
    if (sound) sound.update(0, 0, false, dt);

    // Follow lead AI car with helicopter camera
    const leadAI = aiCars[attractAIIdx];
    const leadPos = leadAI.mesh.position;
    const leadDir = new THREE.Vector3(Math.sin(leadAI.heading), 0, Math.cos(leadAI.heading));

    // Helicopter cam: high above and behind, slightly to the side for cinematic feel
    const heliHeight = 35;
    const heliBehind = 30;
    const heliSide = 15;
    const targetCamPos = leadPos.clone()
      .add(leadDir.clone().multiplyScalar(-heliBehind))
      .add(new THREE.Vector3(0, heliHeight, 0))
      .add(new THREE.Vector3(leadDir.z, 0, -leadDir.x).multiplyScalar(heliSide));

    camera.position.lerp(targetCamPos, 1.5 * dt);
    const lookTarget = leadPos.clone();
    lookTarget.y += 2;
    camera.lookAt(lookTarget);

    sun.position.copy(leadPos).add(new THREE.Vector3(60, 80, 40));
    sun.target.position.copy(leadPos);

    minimap.draw(leadAI);
    hud.draw(Math.abs(Math.round(leadAI.speed * 4)), true, 0, 1, TOTAL_LAPS, aiCars.length + 1, elapsed);

    smoke.update(dt);
    dust.update(dt);
    speedLines.update(dt, leadAI);

    return;
  }

  // ══════════════════════════════════════════
  //  STATE: GRID — cars staged, brief pause
  // ══════════════════════════════════════════
  if (raceState === 'grid') {
    gridTimer -= dt;
    if (gridTimer <= 0) {
      raceState = 'countdown';
      countdownStartTime = elapsed;
    }

    // Camera behind player on grid
    const moveDir = new THREE.Vector3(Math.sin(p.heading), 0, Math.cos(p.heading));
    const camBehind = moveDir.clone().multiplyScalar(-14);
    const camUp = new THREE.Vector3(0, 7, 0);
    const targetCamPos = playerCar.position.clone().add(camBehind).add(camUp);
    camera.position.lerp(targetCamPos, 3 * dt);
    const lookTarget = playerCar.position.clone();
    lookTarget.y += 1;
    camera.lookAt(lookTarget);
    sun.position.copy(playerCar.position).add(new THREE.Vector3(60, 80, 40));
    sun.target.position.copy(playerCar.position);

    minimap.draw(p);
    hud.draw(0, true, 0, 5, TOTAL_LAPS, aiCars.length + 1, elapsed);

    smoke.update(dt);
    dust.update(dt);
    speedLines.update(dt, p);
    return;
  }

  // ══════════════════════════════════════════
  //  STATE: COUNTDOWN — 3, 2, 1, GO!
  // ══════════════════════════════════════════
  if (raceState === 'countdown') {
    const countdownElapsed = elapsed - countdownStartTime;

    // Show 3, 2, 1, GO
    if (countdownElapsed < 1) {
      countdownEl.textContent = '3';
      countdownEl.style.color = '#ff3333';
      countdownEl.style.opacity = '1';
    } else if (countdownElapsed < 2) {
      countdownEl.textContent = '2';
      countdownEl.style.color = '#ffaa00';
      countdownEl.style.opacity = '1';
    } else if (countdownElapsed < 3) {
      countdownEl.textContent = '1';
      countdownEl.style.color = '#00ff66';
      countdownEl.style.opacity = '1';
    } else if (countdownElapsed < 3.8) {
      countdownEl.textContent = 'GO!';
      countdownEl.style.color = '#ffffff';
      countdownEl.style.opacity = '1';
    } else {
      countdownEl.style.opacity = '0';
    }

    // Transition to racing 0.4s after GO!
    if (countdownElapsed >= 3.4) {
      countdownEl.style.opacity = '0';
      if (raceState !== 'racing') {
        raceState = 'racing';
        raceStartTime = elapsed;
        prevTrackT = 0;
        for (const ai of aiCars) {
          ai.prevTrackT = 0;
        }
      }
    }

    // Camera behind player
    const moveDir = new THREE.Vector3(Math.sin(p.heading), 0, Math.cos(p.heading));
    const camBehind = moveDir.clone().multiplyScalar(-14);
    const camUp = new THREE.Vector3(0, 7, 0);
    const targetCamPos = playerCar.position.clone().add(camBehind).add(camUp);
    camera.position.lerp(targetCamPos, 3 * dt);
    const lookTarget = playerCar.position.clone();
    lookTarget.y += 1;
    camera.lookAt(lookTarget);
    sun.position.copy(playerCar.position).add(new THREE.Vector3(60, 80, 40));
    sun.target.position.copy(playerCar.position);

    minimap.draw(p);
    hud.draw(0, true, 0, 5, TOTAL_LAPS, aiCars.length + 1, elapsed);

    smoke.update(dt);
    dust.update(dt);
    speedLines.update(dt, p);
    return;
  }

  // ══════════════════════════════════════════
  //  STATE: FINISHED — show results, slow cars
  // ══════════════════════════════════════════
  if (raceState === 'finished') {
    // Show results on first frame of finished state
    if (!resultsShown) {
      // DNF any car that hasn't finished
      if (!playerFinished) {
        raceResults.push({ name: 'YOU', time: 0, dnf: true });
      }
      for (const ai of aiCars) {
        if (!ai.finished) {
          raceResults.push({ name: ai.name, time: 0, dnf: true });
        }
      }
      showResults();
      resultsShown = true;
      countdownEl.style.opacity = '0';
    }

    // Gradually slow player
    p.speed *= Math.max(0, 1 - 3 * dt);
    const moveDir = new THREE.Vector3(Math.sin(p.velHeading), 0, Math.cos(p.velHeading));
    p.x += moveDir.x * p.speed * dt;
    p.z += moveDir.z * p.speed * dt;

    const nearest = nearestTrackT(p.x, p.z);
    const surfaceFrame = frame(nearest.t);
    playerCar.position.set(p.x, surfaceFrame.point.y + 0.05, p.z);

    // Update AI positions (they're already decelerating in updateAI)
    G.player._trackT = nearest.t;
    try { updateAI(aiCars, G.player, dt, 'finished'); } catch(e) {}

    // Camera
    const camBehind = moveDir.clone().multiplyScalar(-14);
    const camUp = new THREE.Vector3(0, 7, 0);
    const targetCamPos = playerCar.position.clone().add(camBehind).add(camUp);
    camera.position.lerp(targetCamPos, 3 * dt);
    const lookTarget = playerCar.position.clone();
    lookTarget.y += 1;
    camera.lookAt(lookTarget);
    sun.position.copy(playerCar.position).add(new THREE.Vector3(60, 80, 40));
    sun.target.position.copy(playerCar.position);

    smoke.update(dt);
    dust.update(dt);
    minimap.draw(p);
    hud.draw(Math.abs(Math.round(p.speed * 4)), p.onTrack, TOTAL_LAPS, getPosition(nearest.t), TOTAL_LAPS, aiCars.length + 1, elapsed);
    return;
  }

  // ══════════════════════════════════════════
  //  STATE: RACING — full gameplay
  // ══════════════════════════════════════════

  // ── Player physics ──
  const { nearest, absSpeed, moveDir } = updatePlayerPhysics(dt);
  const currentTrackT = nearest.t;

  // ── Player lap tracking (anti-cheat: must pass halfway) ──
  currentLapTime = elapsed - currentLapStart;

  // Record ghost samples every ~0.1s during current lap (if still possibly best)
  if (!playerFinished) {
    // Limit sample count to avoid memory blowup (max ~600 samples @ 0.1s = 60s lap)
    if (currentLapSamples.length < 1000) {
      const lastSample = currentLapSamples[currentLapSamples.length - 1];
      if (!lastSample || currentLapTime - lastSample.t >= 0.1) {
        currentLapSamples.push({
          t: currentLapTime,
          x: p.x,
          z: p.z,
          heading: p.heading,
        });
      }
    }
  }

  if (!playerFinished) {
    // Only set hasPassedHalf when ACTUALLY near the halfway point
    if (currentTrackT > 0.4 && currentTrackT < 0.6) {
      playerHasPassedHalf = true;
    }

    const lapCross = checkLapCrossing(prevTrackT, currentTrackT, p.speed);
    if (lapCross === 1 && playerHasPassedHalf) {
      p.lap++;
      playerHasPassedHalf = false; // reset for next lap

      // ── Capture lap time ──
      lastLapTime = currentLapTime;
      const isNewBest = bestLapTime === null || lastLapTime < bestLapTime;

      if (isNewBest) {
        bestLapTime = lastLapTime;
        saveBestLap(lastLapTime, p.lap, telemetry.id);
        // Save samples as ghost data
        if (currentLapSamples.length > 10) {
          const saved = saveGhost(currentLapSamples, lastLapTime);
          if (saved) ghostData = loadGhost();
        }
        showToast(`NEW BEST LAP! ${formatRaceTime(lastLapTime)}`, 'gold');
      }

      // Reset for next lap
      currentLapStart = elapsed;
      currentLapSamples = [];

      // Show lap notification
      if (p.lap < TOTAL_LAPS) {
        const lapMsg = isNewBest
          ? `LAP ${p.lap + 1}/${TOTAL_LAPS}  ⭐ ${formatRaceTime(lastLapTime)}`
          : `LAP ${p.lap + 1}/${TOTAL_LAPS}  ${formatRaceTime(lastLapTime)}`;
        lapNotifyEl.textContent = lapMsg;
        lapNotifyEl.style.opacity = '1';
        lapNotifyTimer = 2;
      }

      // Check finish
      if (p.lap >= TOTAL_LAPS) {
        playerFinished = true;
        playerFinishTime = elapsed - raceStartTime;
        raceResults.push({ name: 'YOU', time: playerFinishTime, dnf: false });
        lapNotifyEl.textContent = '🏁 FINISHED!';
        lapNotifyEl.style.opacity = '1';
        lapNotifyTimer = 3;
      }
    }
  }
  prevTrackT = currentTrackT;

  // ── AI lap tracking ──
  for (const ai of aiCars) {
    if (ai.finished) continue;

    // Anti-cheat: must actually pass halfway point
    if (ai._trackT > 0.4 && ai._trackT < 0.6) {
      ai.hasPassedHalf = true;
    }

    const aiLapCross = checkLapCrossing(ai.prevTrackT, ai._trackT, ai.speed);
    if (aiLapCross === 1 && ai.hasPassedHalf) {
      ai.lap++;
      ai.hasPassedHalf = false;

      if (ai.lap >= TOTAL_LAPS) {
        ai.finished = true;
        ai.finishTime = elapsed - raceStartTime;
        raceResults.push({ name: ai.name, time: ai.finishTime, dnf: false });
      }
    }
    ai.prevTrackT = ai._trackT;
  }

  // ── AI update ──
  G.player._trackT = currentTrackT;
  try {
    updateAI(aiCars, G.player, dt, 'racing');
  } catch(e) {
    console.error('AI error:', e.message, e.stack);
  }

  // ── AI tire marks & particles ──
  for (const ai of aiCars) {
    const aiAbsSpeed = Math.abs(ai.speed);
    let aiDrift = ai.heading - ai.velHeading;
    while (aiDrift > Math.PI) aiDrift -= 2 * Math.PI;
    while (aiDrift < -Math.PI) aiDrift += 2 * Math.PI;
    const aiAbsDrift = Math.abs(aiDrift);

    if ((aiAbsDrift > 0.15 && aiAbsSpeed > 3) || ai.handbrake && aiAbsSpeed > 3) {
      const aiMoveX = Math.sin(ai.velHeading);
      const aiMoveZ = Math.cos(ai.velHeading);
      const rearX = ai.x + aiMoveX * -1.3;
      const rearZ = ai.z + aiMoveZ * -1.3;
      const rightX = Math.cos(ai.heading);
      const rightZ = -Math.sin(ai.heading);
      tireMarks.addMark(rearX - rightX * 1.1, rearZ - rightZ * 1.1, ai.heading, 0.5, -1, 'ai_' + aiCars.indexOf(ai));
      tireMarks.addMark(rearX + rightX * 1.1, rearZ + rightZ * 1.1, ai.heading, 0.5, 1, 'ai_' + aiCars.indexOf(ai));
    } else {
      tireMarks.breakChain('ai_' + aiCars.indexOf(ai));
    }

    if (aiAbsSpeed > 15 && aiAbsDrift > 0.2) {
      const behindX = -Math.sin(ai.velHeading) * 2;
      const behindZ = -Math.cos(ai.velHeading) * 2;
      for (const side of [-1.2, 1.2]) {
        smoke.emit(
          ai.x + behindX + Math.cos(ai.heading) * side,
          0.2,
          ai.z + behindZ - Math.sin(ai.heading) * side,
          (Math.random() - 0.5) * 3, 1.5 + Math.random(), (Math.random() - 0.5) * 3
        );
      }
    }
  }

  // ── Particle updates ──
  smoke.update(dt);
  dust.update(dt);
  speedLines.update(dt, p);

  // ── Lap notification fade ──
  if (lapNotifyTimer > 0) {
    lapNotifyTimer -= dt;
    if (lapNotifyTimer <= 0) {
      lapNotifyEl.style.opacity = '0';
    }
  }

  // ── Telemetry ──
  telemetry.update(p, currentTrackT, dt, elapsed);
  if (Math.floor(elapsed) % 5 === 0 && Math.floor(elapsed) !== telemetry._lastSave) {
    telemetry._lastSave = Math.floor(elapsed);
    scheduleSave(telemetry);
  }

  // ── Camera follow (3 modes) ──
  let targetCamPos, lookTarget;
  if (cameraMode === CAM_THIRD) {
    const camBehind = moveDir.clone().multiplyScalar(-14);
    const camUp = new THREE.Vector3(0, 7, 0);
    targetCamPos = playerCar.position.clone().add(camBehind).add(camUp);
    lookTarget = playerCar.position.clone();
    lookTarget.y += 1;
    camera.position.lerp(targetCamPos, 5 * dt);
  } else if (cameraMode === CAM_COCKPIT) {
    // Cockpit: just above/behind the driver's seat
    const forward = moveDir.clone().multiplyScalar(-0.2);
    const up = new THREE.Vector3(0, 1.2, 0);
    targetCamPos = playerCar.position.clone().add(forward).add(up);
    const aheadVec = moveDir.clone().multiplyScalar(10);
    lookTarget = playerCar.position.clone().add(aheadVec);
    lookTarget.y += 0.6;
    camera.position.copy(targetCamPos);  // snap, not lerp
  } else if (cameraMode === CAM_TOP) {
    targetCamPos = playerCar.position.clone().add(new THREE.Vector3(0, 40, 0));
    lookTarget = playerCar.position.clone();
    camera.position.lerp(targetCamPos, 8 * dt);
  }
  camera.lookAt(lookTarget);

  const targetFov = 65 + (Math.abs(p.speed) / MAX_SPEED) * 15 + (nitroActive ? 8 : 0);
  camera.fov = THREE.MathUtils.lerp(camera.fov, targetFov, 3 * dt);
  camera.updateProjectionMatrix();

  sun.position.copy(playerCar.position).add(new THREE.Vector3(60, 80, 40));
  sun.target.position.copy(playerCar.position);

  // ── Ghost car update (replay of best lap) ──
  if (ghostEnabled && ghostData && ghostData.samples && ghostData.samples.length > 0) {
    ghostCar.visible = true;
    // Loop the ghost in sync with current lap time
    const lapDur = ghostData.lapTime;
    const t = currentLapTime % lapDur;
    // Find closest sample (binary search would be faster, but linear is fine for 600 samples)
    let sample = ghostData.samples[0];
    for (let i = 1; i < ghostData.samples.length; i++) {
      if (ghostData.samples[i].t > t) break;
      sample = ghostData.samples[i];
    }
    ghostCar.position.set(sample.x, 0.05, sample.z);
    ghostCar.rotation.y = sample.heading;
  } else {
    ghostCar.visible = false;
  }

  // ── AI car sounds ──
  if (aiSound) {
    const px = p.x, pz = p.z, py = playerCar.position.y;
    for (const ai of aiCars) {
      if (ai.soundIdx !== undefined) {
        aiSound.updateCar(ai.soundIdx,
          ai.mesh.position.x, ai.mesh.position.y, ai.mesh.position.z,
          ai.speed, px, py, pz, p.heading, dt);
      }
    }
  }

  // ── HUD ──
  const displaySpeed = Math.abs(Math.round(p.speed * 4));
  const pos = getPosition(currentTrackT);
  const playerLap = Math.min(p.lap + 1, TOTAL_LAPS);

  // ── Compute AI gaps (ahead/behind player) ──
  const playerProgressTotal = p.lap + currentTrackT;
  let aheadGap = null, aheadName = null, behindGap = null, behindName = null;
  let closestAheadProgress = Infinity;
  let closestBehindProgress = -Infinity;
  // Player speed in world units/sec (avg); approximate gap in seconds as distance/speed
  const avgSpeed = Math.max(Math.abs(p.speed), 10); // avoid divide-by-zero
  for (const ai of aiCars) {
    const aiProg = ai.lap + ai._trackT;
    const delta = aiProg - playerProgressTotal;
    if (delta > 0 && aiProg < closestAheadProgress) {
      closestAheadProgress = aiProg;
      // Convert track-t delta to world distance (approximate)
      aheadGap = (delta * trackLen) / avgSpeed;
      aheadName = ai.name || 'AI';
    } else if (delta < 0 && aiProg > closestBehindProgress) {
      closestBehindProgress = aiProg;
      behindGap = (-delta * trackLen) / avgSpeed;
      behindName = ai.name || 'AI';
    }
  }

  // ── Compute ghost delta (seconds ahead/behind ghost) ──
  let ghostDelta = null;
  if (ghostData && ghostData.samples && ghostData.samples.length > 0) {
    // Find ghost's track position at current lap time
    const lapDur = ghostData.lapTime;
    const t = currentLapTime % lapDur;
    let ghostSample = ghostData.samples[0];
    for (let i = 1; i < ghostData.samples.length; i++) {
      if (ghostData.samples[i].t > t) break;
      ghostSample = ghostData.samples[i];
    }
    // Find ghost track-t and compare with player
    const ghostNearest = nearestTrackT(ghostSample.x, ghostSample.z);
    const ghostProgress = ghostNearest.t;
    const playerProgress = currentTrackT;
    // Approx delta: if player is ahead on track, negative = faster than ghost
    let delta = (ghostProgress - playerProgress) * trackLen / avgSpeed;
    // wrap
    if (delta > trackLen / (2 * avgSpeed)) delta -= trackLen / avgSpeed;
    if (delta < -trackLen / (2 * avgSpeed)) delta += trackLen / avgSpeed;
    ghostDelta = delta;
  }

  hud.draw(displaySpeed, p.onTrack, playerLap, pos, TOTAL_LAPS, aiCars.length + 1, elapsed, {
    currentLapTime: currentLapTime,
    bestLapTime: bestLapTime,
    lastLapTime: lastLapTime,
    gapAhead: aheadGap,
    gapBehind: behindGap,
    aheadName: aheadName,
    behindName: behindName,
    nitroCharge: nitroCharge,
    ghostDelta: ghostDelta,
  });

  // ── Minimap ──
  minimap.draw(p);

  // ── Sound engine ──
  if (sound) {
    const isThrottle = G.keys['KeyW'] || G.keys['ArrowUp'];
    sound.update(p.speed, absSpeed, isThrottle, dt);
  }

  // ── Check if race is finished ──
  const allCarsFinished = playerFinished && aiCars.every(ai => ai.finished);
  const anyCarFinished = playerFinished || aiCars.some(ai => ai.finished);

  if (anyCarFinished && raceEndTimer < 0) {
    raceEndTimer = 30;
  }
  if (raceEndTimer >= 0) {
    raceEndTimer -= dt;
  }

  // Transition to finished state
  if (allCarsFinished || (raceEndTimer >= 0 && raceEndTimer <= 0.01)) {
    raceState = 'finished';
  }
}

let loadingVeilHidden = false;
function hideLoadingVeil() {
  if (loadingVeilHidden) return;
  const veil = document.getElementById('loading-veil');
  if (!veil) { loadingVeilHidden = true; return; }
  veil.classList.add('hidden');
  // Remove from DOM after the fade-out transition so it can't steal clicks.
  setTimeout(() => { veil.remove(); }, 700);
  loadingVeilHidden = true;
}

function animate() {
  requestAnimationFrame(animate);
  update();
  renderer.render(scene, camera);
  if (!loadingVeilHidden) hideLoadingVeil();
}

animate();

// ══ RESIZE ══
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
