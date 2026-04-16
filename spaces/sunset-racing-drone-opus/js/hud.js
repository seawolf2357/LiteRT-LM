// ═══════════════════════════════════════════════════════
//  HUD — three canvas layers:
//    1. Attitude indicator (centre-top, small) — artificial
//       horizon with pitch ladder + roll tick.
//    2. Gauge canvas (bottom-left) — speed dial + throttle
//       + altitude bars.
//    3. Overlay canvas (top) — lap, gate count, time,
//       lap delta vs best, off-track flash.
// ═══════════════════════════════════════════════════════

export function createHUD() {
  // ── 1. Attitude indicator canvas ───────────────────────
  const ai = document.createElement('canvas');
  ai.id = 'attitude-canvas';
  ai.width = 220;
  ai.height = 220;
  ai.style.cssText = `
    position: fixed; top: 130px; left: 50%;
    transform: translateX(-50%);
    pointer-events: none;
    z-index: 120;
    opacity: 0.92;
  `;
  document.body.appendChild(ai);
  const aictx = ai.getContext('2d');

  // ── 2. Gauge canvas ────────────────────────────────────
  const gauge = document.createElement('canvas');
  gauge.id = 'hud-canvas';
  gauge.width = 240;
  gauge.height = 240;
  gauge.style.cssText = `
    position: fixed; bottom: 18px; left: 18px;
    pointer-events: none;
    z-index: 110;
  `;
  document.body.appendChild(gauge);
  const gctx = gauge.getContext('2d');

  // ── 3. Top overlay canvas ──────────────────────────────
  const overlay = document.createElement('canvas');
  overlay.id = 'hud-overlay';
  overlay.width = window.innerWidth;
  overlay.height = 130;
  overlay.style.cssText = `
    position: fixed; top: 0; left: 0;
    pointer-events: none;
    z-index: 115;
  `;
  document.body.appendChild(overlay);
  const octx = overlay.getContext('2d');

  window.addEventListener('resize', () => {
    overlay.width = window.innerWidth;
  });

  // Smoothed display values so HUD doesn't twitch.
  let smoothSpeed = 0;
  let smoothAlt   = 0;

  // ── Attitude indicator drawing ─────────────────────────
  function drawAttitude(pitchRad, rollRad) {
    const w = ai.width, h = ai.height;
    const cx = w / 2, cy = h / 2;
    const radius = 92;

    aictx.clearRect(0, 0, w, h);

    // Clip to circle
    aictx.save();
    aictx.beginPath();
    aictx.arc(cx, cy, radius, 0, Math.PI * 2);
    aictx.clip();

    // Sky / ground split, rotated by roll + offset by pitch.
    // 1 radian pitch ≈ half the disc.
    const pitchOffset = Math.max(-radius, Math.min(radius, pitchRad * radius * 1.1));
    aictx.translate(cx, cy);
    aictx.rotate(-rollRad);

    // Sky
    aictx.fillStyle = '#2a4a8a';
    aictx.fillRect(-radius * 2, -radius * 2 + pitchOffset, radius * 4, radius * 2);
    // Ground
    aictx.fillStyle = '#8a4a20';
    aictx.fillRect(-radius * 2, pitchOffset, radius * 4, radius * 2);
    // Horizon line
    aictx.strokeStyle = '#ffffff';
    aictx.lineWidth = 2;
    aictx.beginPath();
    aictx.moveTo(-radius * 2, pitchOffset);
    aictx.lineTo(radius * 2, pitchOffset);
    aictx.stroke();

    // Pitch ladder (every 10° = radius/6 pixels)
    aictx.strokeStyle = 'rgba(255,255,255,0.7)';
    aictx.lineWidth = 1.5;
    aictx.font = '700 9px Orbitron, sans-serif';
    aictx.fillStyle = 'rgba(255,255,255,0.8)';
    aictx.textAlign = 'center';
    for (let deg = -30; deg <= 30; deg += 10) {
      if (deg === 0) continue;
      const y = pitchOffset - deg * (radius / 60);
      const len = deg % 20 === 0 ? 28 : 14;
      aictx.beginPath();
      aictx.moveTo(-len, y);
      aictx.lineTo(len, y);
      aictx.stroke();
      if (deg % 20 === 0) {
        aictx.fillText(Math.abs(deg) + '°', -len - 10, y + 3);
        aictx.fillText(Math.abs(deg) + '°',  len + 10, y + 3);
      }
    }

    aictx.restore();

    // Fixed-aircraft reticle (stays upright)
    aictx.strokeStyle = '#ffdf6a';
    aictx.lineWidth = 3;
    aictx.lineCap = 'round';
    aictx.beginPath();
    aictx.moveTo(cx - 36, cy);
    aictx.lineTo(cx - 10, cy);
    aictx.moveTo(cx + 10, cy);
    aictx.lineTo(cx + 36, cy);
    aictx.moveTo(cx, cy - 3);
    aictx.lineTo(cx, cy + 3);
    aictx.stroke();

    // Outer ring
    aictx.strokeStyle = 'rgba(255,255,255,0.35)';
    aictx.lineWidth = 2;
    aictx.beginPath();
    aictx.arc(cx, cy, radius, 0, Math.PI * 2);
    aictx.stroke();

    // Roll tick at top
    aictx.fillStyle = '#ffdf6a';
    aictx.beginPath();
    aictx.moveTo(cx, cy - radius - 4);
    aictx.lineTo(cx - 6, cy - radius - 14);
    aictx.lineTo(cx + 6, cy - radius - 14);
    aictx.closePath();
    aictx.fill();
  }

  // ── Speed gauge + throttle bar + altitude bar ──────────
  function drawGauge(speedMps, throttle, altitude) {
    const w = gauge.width, h = gauge.height;
    gctx.clearRect(0, 0, w, h);

    const cx = w / 2 - 20;
    const cy = h / 2 + 10;
    const r  = 92;

    // Speed track arc
    gctx.strokeStyle = 'rgba(255,255,255,0.22)';
    gctx.lineWidth = 8;
    gctx.lineCap = 'round';
    gctx.beginPath();
    gctx.arc(cx, cy, r, Math.PI * 0.8, Math.PI * 2.2);
    gctx.stroke();

    // Active speed arc (0 .. ~35 m/s maps to 0..1)
    const speedNorm = Math.min(1, Math.max(0, speedMps / 35));
    const arcStart  = Math.PI * 0.8;
    const arcSweep  = Math.PI * 1.4;
    gctx.strokeStyle = '#ffffff';
    gctx.shadowColor = 'rgba(255,255,255,0.55)';
    gctx.shadowBlur = 10;
    gctx.lineWidth = 8;
    gctx.beginPath();
    gctx.arc(cx, cy, r, arcStart, arcStart + speedNorm * arcSweep);
    gctx.stroke();
    gctx.shadowBlur = 0;

    // Ticks
    gctx.strokeStyle = 'rgba(255,255,255,0.55)';
    gctx.lineWidth = 1.5;
    for (let i = 0; i <= 7; i++) {
      const t = i / 7;
      const a = arcStart + t * arcSweep;
      const ix = cx + Math.cos(a) * (r - 16);
      const iy = cy + Math.sin(a) * (r - 16);
      const ox = cx + Math.cos(a) * (r - 4);
      const oy = cy + Math.sin(a) * (r - 4);
      gctx.beginPath();
      gctx.moveTo(ix, iy);
      gctx.lineTo(ox, oy);
      gctx.stroke();
    }

    // Digital speed readout
    gctx.fillStyle = '#ffffff';
    gctx.font = '900 36px Orbitron, sans-serif';
    gctx.textAlign = 'center';
    gctx.shadowColor = 'rgba(255,255,255,0.45)';
    gctx.shadowBlur = 8;
    gctx.fillText(Math.round(speedMps).toString(), cx, cy + 10);
    gctx.shadowBlur = 0;
    gctx.font = '700 10px Orbitron, sans-serif';
    gctx.fillStyle = 'rgba(255,255,255,0.65)';
    gctx.fillText('M/S', cx, cy + 26);

    // Throttle vertical bar (right of gauge)
    const barX = w - 32;
    const barY = 30;
    const barW = 10;
    const barH = h - 60;
    gctx.fillStyle = 'rgba(255,255,255,0.15)';
    gctx.fillRect(barX, barY, barW, barH);
    const thrFill = Math.max(0, Math.min(1, throttle));
    gctx.fillStyle = '#00eaff';
    gctx.shadowColor = 'rgba(0,234,255,0.55)';
    gctx.shadowBlur = 10;
    gctx.fillRect(barX, barY + barH * (1 - thrFill), barW, barH * thrFill);
    gctx.shadowBlur = 0;
    gctx.fillStyle = 'rgba(255,255,255,0.7)';
    gctx.font = '700 9px Orbitron, sans-serif';
    gctx.textAlign = 'center';
    gctx.fillText('THR', barX + barW / 2, barY - 4);

    // Altitude vertical bar (left edge)
    const aX = 4;
    const aW = 8;
    const aBarY = 30;
    const aBarH = h - 60;
    gctx.fillStyle = 'rgba(255,255,255,0.15)';
    gctx.fillRect(aX, aBarY, aW, aBarH);
    const altNorm = Math.max(0, Math.min(1, altitude / 40));
    gctx.fillStyle = '#ffaa44';
    gctx.fillRect(aX, aBarY + aBarH * (1 - altNorm), aW, aBarH * altNorm);
    gctx.fillStyle = 'rgba(255,255,255,0.7)';
    gctx.font = '700 9px Orbitron, sans-serif';
    gctx.textAlign = 'left';
    gctx.fillText('ALT', aX, aBarY - 4);
    gctx.fillStyle = '#ffffff';
    gctx.font = '700 11px Orbitron, sans-serif';
    gctx.fillText(`${Math.round(altitude)}m`, aX, aBarY + aBarH + 14);
  }

  // ── Next-gate direction arrow (centred on screen) ─────
  // Drawn into the overlay canvas so it composites cleanly
  // above the 3D scene. Angle: 0 = dead ahead, + = right.
  function drawGateArrow(angle, distance, w) {
    if (angle === null || angle === undefined) return;

    const cx = w / 2;
    const cy = 104; // just below the time readout

    // Clamp to half-screen range so the arrow always points
    // somewhere sensible.
    const clamped = Math.max(-Math.PI, Math.min(Math.PI, angle));

    // If the gate is close to dead-ahead, show a centered triangle.
    // If it's off to the side, show a directional chevron.
    octx.save();
    octx.translate(cx, cy);
    octx.rotate(clamped);

    // Pulse scale with a little "urgency" when distance is small.
    const near = distance !== null && distance < 30;
    const pulse = near ? 1 + 0.1 * Math.sin(performance.now() * 0.012) : 1;

    octx.shadowColor = 'rgba(0, 234, 255, 0.8)';
    octx.shadowBlur = 14;
    octx.fillStyle = '#00eaff';
    octx.beginPath();
    // Arrow shape: elongated triangle pointing up (= toward gate)
    const s = 18 * pulse;
    octx.moveTo(0, -s * 1.3);
    octx.lineTo(s, s * 0.7);
    octx.lineTo(0, s * 0.2);
    octx.lineTo(-s, s * 0.7);
    octx.closePath();
    octx.fill();
    octx.restore();

    // Distance readout just below the arrow
    if (distance !== null) {
      octx.textAlign = 'center';
      octx.font = '700 12px Orbitron, sans-serif';
      octx.fillStyle = 'rgba(0, 234, 255, 0.95)';
      octx.shadowColor = 'rgba(0, 0, 0, 0.85)';
      octx.shadowBlur = 6;
      octx.fillText(`${Math.round(distance)}m`, cx, cy + 32);
    }
  }

  // ── Top overlay: lap / gate / time / delta ─────────────
  function drawOverlay(data) {
    const w = overlay.width;
    octx.clearRect(0, 0, w, overlay.height);
    octx.font = '900 28px Orbitron, sans-serif';
    octx.fillStyle = '#ffffff';
    octx.shadowColor = 'rgba(0,0,0,0.85)';
    octx.shadowBlur = 6;

    // Left: lap + gate
    octx.textAlign = 'left';
    octx.fillText(`LAP ${data.lap}/${data.totalLaps}`, 22, 36);
    octx.font = '700 14px Orbitron, sans-serif';
    octx.fillStyle = 'rgba(255,255,255,0.75)';
    octx.fillText(`GATE ${data.gateIdx + 1}/${data.totalGates}`, 22, 58);

    // Center: current lap time
    octx.textAlign = 'center';
    octx.font = '900 32px Orbitron, sans-serif';
    octx.fillStyle = '#ffffff';
    octx.fillText(formatTime(data.currentLapTime), w / 2, 38);
    octx.font = '700 11px Orbitron, sans-serif';
    octx.fillStyle = 'rgba(255,255,255,0.65)';
    octx.fillText('CURRENT LAP', w / 2, 56);

    // Real-time lap delta vs best (if we have a best)
    if (data.deltaVsBest !== null && !isNaN(data.deltaVsBest)) {
      const d = data.deltaVsBest;
      const sign = d >= 0 ? '+' : '-';
      const col  = d >= 0 ? '#ff5544' : '#44ff99';
      octx.font = '900 18px Orbitron, sans-serif';
      octx.fillStyle = col;
      octx.shadowColor = 'rgba(0,0,0,0.85)';
      octx.shadowBlur = 6;
      octx.fillText(`${sign}${Math.abs(d).toFixed(2)}s`, w / 2, 80);
    }

    // Right: best lap
    octx.textAlign = 'right';
    if (data.bestLapTime !== null) {
      octx.font = '900 22px Orbitron, sans-serif';
      octx.fillStyle = '#ffd700';
      octx.fillText(`★ ${formatTime(data.bestLapTime)}`, w - 22, 38);
      octx.font = '700 11px Orbitron, sans-serif';
      octx.fillStyle = 'rgba(255,215,0,0.75)';
      octx.fillText('BEST LAP', w - 22, 56);
    } else {
      octx.font = '700 13px Orbitron, sans-serif';
      octx.fillStyle = 'rgba(255,255,255,0.5)';
      octx.fillText('NO BEST YET', w - 22, 40);
    }

    // Next-gate arrow (points toward upcoming gate)
    drawGateArrow(data.gateArrowAngle, data.gateDistance, w);

    // Off-track / reset warning (flashing)
    if (data.offCourseFlash) {
      const flash = Math.sin(performance.now() * 0.02) > 0;
      if (flash) {
        octx.textAlign = 'center';
        octx.font = '900 22px Orbitron, sans-serif';
        octx.fillStyle = '#ff5544';
        octx.fillText('OFF COURSE — RESETTING', w / 2, 110);
      }
    }
  }

  function formatTime(s) {
    if (s === null || !isFinite(s)) return '--:--.---';
    const m = Math.floor(s / 60);
    const sec = s - m * 60;
    const whole = Math.floor(sec);
    const ms = Math.round((sec - whole) * 1000);
    return `${m}:${String(whole).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
  }

  // ── Main entry: called by game.js every frame ──────────
  function draw({ speed, throttle, altitude, pitch, roll, lap, totalLaps,
                  gateIdx, totalGates, currentLapTime, bestLapTime,
                  deltaVsBest, offCourseFlash, gateArrowAngle, gateDistance }) {
    smoothSpeed += (speed - smoothSpeed) * 0.18;
    smoothAlt   += (altitude - smoothAlt) * 0.3;
    drawAttitude(pitch, roll);
    drawGauge(smoothSpeed, throttle, smoothAlt);
    drawOverlay({
      lap, totalLaps, gateIdx, totalGates,
      currentLapTime, bestLapTime, deltaVsBest, offCourseFlash,
      gateArrowAngle, gateDistance,
    });
  }

  return { draw };
}
