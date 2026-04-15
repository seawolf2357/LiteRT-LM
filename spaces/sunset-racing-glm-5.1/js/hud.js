// ═══════════════════════════════════════════════════════
//  HUD — Daytona-style minimal white gauge
//  Features: speedometer, position, lap, current/best lap time,
//  AI gap, off-track warning, nitro bar
// ═══════════════════════════════════════════════════════

export function createHUD() {
  const canvas = document.createElement('canvas');
  canvas.id = 'hud-canvas';
  const SIZE = 220;
  canvas.width = SIZE;
  canvas.height = SIZE;
  canvas.style.cssText = `
    position: fixed;
    bottom: 18px;
    left: 18px;
    pointer-events: none;
    z-index: 100;
    opacity: 0.88;
  `;
  document.body.appendChild(canvas);

  const ctx = canvas.getContext('2d');
  let smoothSpeed = 0;

  // Wait for font to load
  document.fonts.load('900 24px Orbitron').catch(() => {});

  // ── Single speed gauge ──
  function drawGauge(speed, nitroCharge) {
    const cx = SIZE / 2;
    const cy = SIZE / 2 + 10;
    const r = 88;
    const maxSpeed = 160;

    const startA = Math.PI * 0.8;
    const endA = Math.PI * 2.2;
    const sweep = endA - startA;

    ctx.clearRect(0, 0, SIZE, SIZE);

    const clamped = Math.max(0, Math.min(speed / maxSpeed, 1.05));

    // Outer arc track
    ctx.beginPath();
    ctx.arc(cx, cy, r, startA, endA);
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = 6;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Active arc
    const activeEnd = startA + clamped * sweep;
    if (clamped > 0.005) {
      ctx.save();
      ctx.shadowColor = 'rgba(255,255,255,0.5)';
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(cx, cy, r, startA, activeEnd);
      ctx.strokeStyle = 'rgba(255,255,255,0.7)';
      ctx.lineWidth = 5;
      ctx.lineCap = 'round';
      ctx.stroke();
      ctx.restore();

      ctx.beginPath();
      ctx.arc(cx, cy, r, startA, activeEnd);
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 4;
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    // Redline
    const redlineT = 0.78;
    const redlineA = startA + redlineT * sweep;
    ctx.beginPath();
    ctx.arc(cx, cy, r + 10, redlineA, endA);
    ctx.strokeStyle = 'rgba(255,60,40,0.35)';
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.stroke();

    if (clamped > redlineT) {
      ctx.save();
      ctx.shadowColor = 'rgba(255,60,40,0.6)';
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.arc(cx, cy, r + 10, redlineA, activeEnd);
      ctx.strokeStyle = 'rgba(255,60,40,0.8)';
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.stroke();
      ctx.restore();
    }

    // Ticks
    const majorTicks = [0, 20, 40, 60, 80, 100, 120, 140, 160];
    const minorPerMajor = 5;
    for (let i = 0; i < majorTicks.length - 1; i++) {
      for (let j = 1; j < minorPerMajor; j++) {
        const t = (majorTicks[i] + (majorTicks[i + 1] - majorTicks[i]) * j / minorPerMajor) / maxSpeed;
        const a = startA + t * sweep;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * (r - 14), cy + Math.sin(a) * (r - 14));
        ctx.lineTo(cx + Math.cos(a) * (r - 8), cy + Math.sin(a) * (r - 8));
        ctx.strokeStyle = 'rgba(255,255,255,0.18)';
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }
    for (const val of majorTicks) {
      const t = val / maxSpeed;
      const a = startA + t * sweep;
      const isRed = t >= redlineT;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * (r - 16), cy + Math.sin(a) * (r - 16));
      ctx.lineTo(cx + Math.cos(a) * (r - 6), cy + Math.sin(a) * (r - 6));
      ctx.strokeStyle = isRed ? 'rgba(255,80,60,0.8)' : 'rgba(255,255,255,0.6)';
      ctx.lineWidth = 2;
      ctx.stroke();
      const lr = r - 26;
      const lx = cx + Math.cos(a) * lr;
      const ly = cy + Math.sin(a) * lr;
      ctx.save();
      ctx.translate(lx, ly);
      ctx.fillStyle = isRed ? 'rgba(255,80,60,0.85)' : 'rgba(255,255,255,0.55)';
      ctx.font = '700 10px Orbitron, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(val, 0, 0);
      ctx.restore();
    }

    // Needle
    const needleA = startA + clamped * sweep;
    const nLen = r - 4;
    const nTail = 14;
    const tipX = cx + Math.cos(needleA) * nLen;
    const tipY = cy + Math.sin(needleA) * nLen;
    const tailX = cx - Math.cos(needleA) * nTail;
    const tailY = cy - Math.sin(needleA) * nTail;
    ctx.save();
    ctx.shadowColor = clamped > redlineT ? 'rgba(255,60,40,0.8)' : 'rgba(255,255,255,0.6)';
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.moveTo(tailX, tailY);
    ctx.lineTo(tipX, tipY);
    ctx.strokeStyle = clamped > redlineT ? '#ff4030' : '#ffffff';
    ctx.lineWidth = 2.5;
    ctx.lineCap = 'round';
    ctx.stroke();
    ctx.restore();

    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#fff';
    ctx.fill();

    // Digital speed
    const speedVal = Math.round(speed);
    ctx.save();
    ctx.shadowColor = 'rgba(255,255,255,0.4)';
    ctx.shadowBlur = 8;
    ctx.fillStyle = '#ffffff';
    ctx.font = '900 36px Orbitron, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(speedVal, cx, cy + 32);
    ctx.restore();

    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '700 10px Orbitron, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('km/h', cx, cy + 50);

    // ── Nitro bar (below gauge) ──
    if (nitroCharge !== null && nitroCharge !== undefined) {
      const barY = SIZE - 8;
      const barW = 140;
      const barH = 5;
      const barX = (SIZE - barW) / 2;
      ctx.fillStyle = 'rgba(255,255,255,0.15)';
      ctx.fillRect(barX, barY, barW, barH);
      const fillW = barW * Math.max(0, Math.min(1, nitroCharge));
      ctx.fillStyle = nitroCharge >= 1 ? '#00eaff' : 'rgba(0,200,255,0.7)';
      ctx.fillRect(barX, barY, fillW, barH);
      if (nitroCharge >= 1) {
        ctx.save();
        ctx.shadowColor = '#00eaff';
        ctx.shadowBlur = 8;
        ctx.fillStyle = '#00eaff';
        ctx.fillRect(barX, barY, fillW, barH);
        ctx.restore();
      }
    }
  }

  // ── Top overlay (position, lap, times, gap) ──
  const overlay = document.createElement('canvas');
  overlay.id = 'hud-overlay';
  overlay.width = window.innerWidth;
  overlay.height = 120;
  overlay.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    pointer-events: none;
    z-index: 100;
    opacity: 0.95;
  `;
  document.body.appendChild(overlay);
  const octx = overlay.getContext('2d');

  function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '--:--.---';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    const wholeSecs = Math.floor(secs);
    const ms = Math.floor((secs - wholeSecs) * 1000);
    return `${mins}:${String(wholeSecs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
  }

  function drawOverlay(data) {
    octx.clearRect(0, 0, overlay.width, overlay.height);
    const {
      position, lap, totalLaps, onTrack, time,
      currentLapTime, bestLapTime, lastLapTime,
      gapAhead, gapBehind, aheadName, behindName,
      ghostDelta,
    } = data;

    // Position — top left
    const posText = `${position}`;
    octx.save();
    octx.font = '900 56px Orbitron, sans-serif';
    octx.textAlign = 'left';
    octx.textBaseline = 'top';
    octx.strokeStyle = 'rgba(0,0,0,0.7)';
    octx.lineWidth = 6;
    octx.lineJoin = 'round';
    octx.strokeText(posText, 22, 10);
    const posColors = { 1: '#ffd700', 2: '#e0e0e0', 3: '#cd7f32' };
    octx.fillStyle = posColors[position] || '#ffffff';
    octx.fillText(posText, 22, 10);
    octx.restore();

    // POSITION label
    octx.save();
    octx.font = '700 11px Orbitron, sans-serif';
    octx.textAlign = 'left';
    octx.strokeStyle = 'rgba(0,0,0,0.6)';
    octx.lineWidth = 3;
    octx.lineJoin = 'round';
    octx.strokeText('POSITION', 24, 68);
    octx.fillStyle = 'rgba(255,255,255,0.5)';
    octx.fillText('POSITION', 24, 68);
    octx.restore();

    // Gap ahead / behind (below POSITION label)
    if (gapAhead !== null && aheadName) {
      octx.save();
      octx.font = '700 13px Orbitron, sans-serif';
      octx.textAlign = 'left';
      octx.strokeStyle = 'rgba(0,0,0,0.7)';
      octx.lineWidth = 3;
      octx.strokeText(`▲ ${aheadName}  -${gapAhead.toFixed(1)}s`, 24, 86);
      octx.fillStyle = 'rgba(200,220,255,0.85)';
      octx.fillText(`▲ ${aheadName}  -${gapAhead.toFixed(1)}s`, 24, 86);
      octx.restore();
    }
    if (gapBehind !== null && behindName) {
      octx.save();
      octx.font = '700 13px Orbitron, sans-serif';
      octx.textAlign = 'left';
      octx.strokeStyle = 'rgba(0,0,0,0.7)';
      octx.lineWidth = 3;
      octx.strokeText(`▼ ${behindName}  +${gapBehind.toFixed(1)}s`, 24, 102);
      octx.fillStyle = 'rgba(255,200,180,0.85)';
      octx.fillText(`▼ ${behindName}  +${gapBehind.toFixed(1)}s`, 24, 102);
      octx.restore();
    }

    // Lap — top right
    const lapText = `LAP ${lap}/${totalLaps}`;
    octx.save();
    octx.font = '900 28px Orbitron, sans-serif';
    octx.textAlign = 'right';
    octx.textBaseline = 'top';
    octx.strokeStyle = 'rgba(0,0,0,0.7)';
    octx.lineWidth = 5;
    octx.lineJoin = 'round';
    octx.strokeText(lapText, overlay.width - 22, 10);
    octx.fillStyle = '#ffffff';
    octx.fillText(lapText, overlay.width - 22, 10);
    octx.restore();

    // Current lap time
    if (currentLapTime !== null && currentLapTime !== undefined) {
      const curText = formatTime(currentLapTime);
      octx.save();
      octx.font = '700 20px Orbitron, sans-serif';
      octx.textAlign = 'right';
      octx.strokeStyle = 'rgba(0,0,0,0.7)';
      octx.lineWidth = 4;
      octx.strokeText(curText, overlay.width - 22, 44);
      octx.fillStyle = '#ffffff';
      octx.fillText(curText, overlay.width - 22, 44);
      octx.restore();

      // CURRENT label
      octx.save();
      octx.font = '700 9px Orbitron, sans-serif';
      octx.textAlign = 'right';
      octx.strokeStyle = 'rgba(0,0,0,0.6)';
      octx.lineWidth = 2;
      octx.strokeText('CURRENT', overlay.width - 22, 68);
      octx.fillStyle = 'rgba(255,255,255,0.5)';
      octx.fillText('CURRENT', overlay.width - 22, 68);
      octx.restore();
    }

    // Best lap time (smaller, below current)
    if (bestLapTime !== null && bestLapTime !== undefined) {
      const bestText = formatTime(bestLapTime);
      octx.save();
      octx.font = '700 14px Orbitron, sans-serif';
      octx.textAlign = 'right';
      octx.strokeStyle = 'rgba(0,0,0,0.7)';
      octx.lineWidth = 3;
      octx.strokeText(`★ BEST  ${bestText}`, overlay.width - 22, 84);
      octx.fillStyle = '#ffd700';
      octx.fillText(`★ BEST  ${bestText}`, overlay.width - 22, 84);
      octx.restore();
    }

    // Ghost delta
    if (ghostDelta !== null && ghostDelta !== undefined && isFinite(ghostDelta)) {
      const sign = ghostDelta >= 0 ? '+' : '';
      const color = ghostDelta >= 0 ? '#ff6644' : '#44ff88';
      const text = `GHOST ${sign}${ghostDelta.toFixed(2)}s`;
      octx.save();
      octx.font = '700 12px Orbitron, sans-serif';
      octx.textAlign = 'right';
      octx.strokeStyle = 'rgba(0,0,0,0.7)';
      octx.lineWidth = 3;
      octx.strokeText(text, overlay.width - 22, 103);
      octx.fillStyle = color;
      octx.fillText(text, overlay.width - 22, 103);
      octx.restore();
    }

    // Off-track warning
    if (!onTrack) {
      const flash = Math.sin(time * 10) > 0;
      if (flash) {
        octx.save();
        octx.font = '900 22px Orbitron, sans-serif';
        octx.textAlign = 'center';
        octx.strokeStyle = 'rgba(0,0,0,0.8)';
        octx.lineWidth = 5;
        octx.lineJoin = 'round';
        octx.strokeText('OFF TRACK', overlay.width / 2, 26);
        octx.fillStyle = '#ff3333';
        octx.fillText('OFF TRACK', overlay.width / 2, 26);
        octx.restore();
      }
    }
  }

  window.addEventListener('resize', () => {
    overlay.width = window.innerWidth;
  });

  // ── Main entry (backward compatible) ──
  function draw(speed, onTrack, lap, position, totalLaps, totalRacers, time, extras = {}) {
    smoothSpeed += (speed - smoothSpeed) * 0.14;
    drawGauge(smoothSpeed, extras.nitroCharge);
    drawOverlay({
      position, lap, totalLaps, onTrack, time,
      currentLapTime: extras.currentLapTime ?? null,
      bestLapTime: extras.bestLapTime ?? null,
      lastLapTime: extras.lastLapTime ?? null,
      gapAhead: extras.gapAhead ?? null,
      gapBehind: extras.gapBehind ?? null,
      aheadName: extras.aheadName ?? null,
      behindName: extras.behindName ?? null,
      ghostDelta: extras.ghostDelta ?? null,
    });
  }

  return { draw };
}
