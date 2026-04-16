// ═══════════════════════════════════════════════════════
//  CONFIG — drone constants & utilities
//  Units: meters, seconds, radians. "Up" is +Y (three.js
//  convention). All rates are in radians/second.
// ═══════════════════════════════════════════════════════

// ── Drone physics ────────────────────────────────────────
// Thrust magnitude when throttle = 1.0 (gravity is 9.81,
// so MAX_THRUST > 9.81 means we can hover + climb).
// Hover throttle ≈ GRAVITY / MAX_THRUST.
export const MAX_THRUST     = 17;   // ~58% hover, 42% headroom
export const GRAVITY        = 9.81;
export const DRAG_LINEAR    = 0.9;  // stronger air drag for stable feel
export const DRAG_ANGULAR   = 5.5;

// Input → target angular-rate. Tuned down from raw acro
// to keep the sim readable with keyboard-only input.
export const PITCH_RATE     = 2.4;
export const YAW_RATE       = 1.9;
export const ROLL_RATE      = 2.8;

// How quickly commanded rates override current angular
// velocity. Softer than competitive acro.
export const RATE_RESPONSE  = 6.5;

// Throttle slew so spamming Space/Shift doesn't teleport thrust.
export const THROTTLE_SLEW  = 1.6;

// Default hover throttle (applied on spawn + reset).
export const HOVER_THROTTLE = 0.60;

// ── Track / gates ────────────────────────────────────────
export const GATE_COUNT     = 10;
export const GATE_RADIUS    = 5.0;   // slightly bigger — more forgiving
export const GATE_TUBE      = 0.38;
export const TOTAL_LAPS     = 3;

// Gate pass detection tolerance along the normal axis.
export const GATE_PLANE_EPS = 0.2;

// ── Off-course recovery ──────────────────────────────────
export const OFF_COURSE_RADIUS = 95;
export const RESET_HOVER_Y     = 8;

// ── Camera ───────────────────────────────────────────────
export const FOV_FPV        = 90;
export const FOV_CHASE      = 72;
export const CAMERA_TILT    = 0.22;  // mild forward tilt in FPV
export const CHASE_DIST     = 7.5;
export const CHASE_HEIGHT   = 2.8;

// ── World ────────────────────────────────────────────────
export const SUN_BASE_ANGLE   = 0.12;
export const SUN_DROP_PER_LAP = 0.035;
export const FOG_NEAR         = 120;  // pushed out — gates read at distance
export const FOG_FAR          = 900;

// ── Colors ───────────────────────────────────────────────
export const C_NEXT_GATE   = 0x00eaff; // next gate = cyan
export const C_FUTURE_GATE = 0xff6a3d; // upcoming = warm orange
export const C_DONE_GATE   = 0x5a2456; // passed = muted violet
export const C_FLASH       = 0xffffff;
export const C_BEACON      = 0x00eaff; // sky beacon column

// ── Utilities ────────────────────────────────────────────
export function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
export function lerp(a, b, t)    { return a + (b - a) * t; }
export function rand(a, b)       { return a + Math.random() * (b - a); }

export function smoothDamp(current, target, tau, dt) {
  if (tau <= 0) return target;
  const alpha = 1 - Math.exp(-dt / tau);
  return current + (target - current) * alpha;
}
