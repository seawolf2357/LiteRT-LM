// ═══════════════════════════════════════════════════════
//  CONFIG — drone constants & utilities
//  Units: meters, seconds, radians. "Up" is +Y (three.js
//  convention). All rates are in radians/second.
// ═══════════════════════════════════════════════════════

// ── Drone physics ────────────────────────────────────────
// Thrust magnitude when throttle = 1.0 (gravity is 9.81,
// so MAX_THRUST > 9.81 means we can hover + climb).
export const MAX_THRUST     = 22;   // m/s^2 acceleration along drone local +Y
export const GRAVITY        = 9.81; // m/s^2, world -Y
export const DRAG_LINEAR    = 0.55; // per-second linear velocity damping
export const DRAG_ANGULAR   = 4.0;  // per-second angular velocity damping

// Input → target angular-rate (acro mode has no level lock)
export const PITCH_RATE     = 3.8;  // rad/s at full stick
export const YAW_RATE       = 2.4;
export const ROLL_RATE      = 4.6;

// How quickly commanded rates override current angular velocity.
// Higher = snappier / twitchier; lower = floaty.
export const RATE_RESPONSE  = 9.0;  // 1/s

// Throttle slew so spamming Space/Shift doesn't teleport thrust.
export const THROTTLE_SLEW  = 2.8;  // 0..1 per second (full travel ~0.36s)

// ── Track / gates ────────────────────────────────────────
export const GATE_COUNT     = 10;
export const GATE_RADIUS    = 4.2;   // inner radius (pass if <= this)
export const GATE_TUBE      = 0.32;  // torus tube radius (visual thickness)
export const TOTAL_LAPS     = 3;

// Gate pass detection tolerance along the normal axis
// (how "in front of" vs "behind" counts as crossing).
export const GATE_PLANE_EPS = 0.15;

// ── Off-course recovery ──────────────────────────────────
// If the drone strays too far from the previous gate, snap
// back to a hover checkpoint. Radius is large so it only
// triggers on genuine failures, not near-misses.
export const OFF_COURSE_RADIUS = 80;
export const RESET_HOVER_Y     = 6;   // altitude of reset hover

// ── Camera ───────────────────────────────────────────────
export const FOV_FPV        = 95;    // wide FOV like a real FPV quad
export const FOV_CHASE      = 70;
export const CAMERA_TILT    = 0.42;  // radians forward-tilt in FPV (~24°)
export const CHASE_DIST     = 5.2;
export const CHASE_HEIGHT   = 1.8;

// ── World ────────────────────────────────────────────────
export const SUN_BASE_ANGLE   = 0.12;  // sun elevation at race start (rad)
export const SUN_DROP_PER_LAP = 0.04;  // sun descends each completed lap
export const FOG_NEAR         = 40;
export const FOG_FAR          = 420;

// ── Colors ───────────────────────────────────────────────
export const C_NEXT_GATE   = 0x00eaff; // highlighted next gate
export const C_FUTURE_GATE = 0xff6a3d; // upcoming dim gates
export const C_DONE_GATE   = 0x6b3a66; // already-passed gates
export const C_FLASH       = 0xffffff;

// ── Utilities ────────────────────────────────────────────
export function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
export function lerp(a, b, t)    { return a + (b - a) * t; }
export function rand(a, b)       { return a + Math.random() * (b - a); }

// Exponential smoothing that is framerate-independent:
// result approaches `target` with time constant `tau` seconds.
export function smoothDamp(current, target, tau, dt) {
  if (tau <= 0) return target;
  const alpha = 1 - Math.exp(-dt / tau);
  return current + (target - current) * alpha;
}
