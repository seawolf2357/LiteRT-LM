// ═══════════════════════════════════════════════════════
//  SOUND — propeller whine synthesized from a bandpass
//  filtered noise source + a low-rumble oscillator. No
//  external audio files — everything is built in
//  WebAudio at runtime so the Space loads instantly.
//
//  API:  sound.update(throttle, speedMps, dt)
//        sound.start()    — lazy, call after user gesture
//        sound.setMuted(muted)
// ═══════════════════════════════════════════════════════

export function createDroneSound() {
  let ctx = null;
  let started = false;
  let muted = false;

  // Nodes we need references to so we can modulate them.
  let noise, bpFilter, noiseGain;
  let rumble, rumbleGain;
  let masterGain;

  function ensureContext() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    return ctx;
  }

  function start() {
    if (started) return;
    const c = ensureContext();
    if (!c) return;

    // ── Master gain so we can duck on pause + mute. ──
    masterGain = c.createGain();
    masterGain.gain.value = 0.0;
    masterGain.connect(c.destination);

    // ── Noise source (pink-ish via bandpass) ──
    // Create a 2-second white-noise buffer and loop it.
    const bufferSize = c.sampleRate * 2;
    const buffer = c.createBuffer(1, bufferSize, c.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;

    noise = c.createBufferSource();
    noise.buffer = buffer;
    noise.loop = true;

    bpFilter = c.createBiquadFilter();
    bpFilter.type = 'bandpass';
    bpFilter.frequency.value = 320;
    bpFilter.Q.value = 1.8;

    noiseGain = c.createGain();
    noiseGain.gain.value = 0.0;

    noise.connect(bpFilter);
    bpFilter.connect(noiseGain);
    noiseGain.connect(masterGain);
    noise.start();

    // ── Low-frequency sine rumble for thrust body ──
    rumble = c.createOscillator();
    rumble.type = 'sine';
    rumble.frequency.value = 55;

    rumbleGain = c.createGain();
    rumbleGain.gain.value = 0.0;
    rumble.connect(rumbleGain);
    rumbleGain.connect(masterGain);
    rumble.start();

    // Fade in master over 0.4s to avoid a click.
    masterGain.gain.linearRampToValueAtTime(muted ? 0.0 : 0.55, c.currentTime + 0.4);
    started = true;
  }

  /**
   * Per-frame update. Maps throttle → bandpass cutoff and
   * gain; speed adds a tiny bit of extra whoosh.
   */
  function update(throttle, speedMps, dt) {
    if (!started || !ctx || muted) return;
    const t = ctx.currentTime;

    const th = Math.max(0, Math.min(1, throttle));
    const spdNorm = Math.max(0, Math.min(1, speedMps / 35));

    // Bandpass climbs from ~240Hz idle to ~2200Hz full throttle.
    const targetFreq = 240 + th * 1960 + spdNorm * 240;
    bpFilter.frequency.setTargetAtTime(targetFreq, t, 0.05);
    // Q sharpens slightly at high throttle for that whine.
    bpFilter.Q.setTargetAtTime(1.4 + th * 2.5, t, 0.08);

    // Noise gain: idle ~0.08, full ~0.32.
    const targetNoise = 0.08 + th * 0.24 + spdNorm * 0.04;
    noiseGain.gain.setTargetAtTime(targetNoise, t, 0.06);

    // Rumble: ride on throttle, with slight frequency modulation.
    const rumFreq = 50 + th * 40;
    rumble.frequency.setTargetAtTime(rumFreq, t, 0.1);
    rumbleGain.gain.setTargetAtTime(0.04 + th * 0.08, t, 0.1);
  }

  function setMuted(m) {
    muted = m;
    if (!ctx || !started) return;
    const t = ctx.currentTime;
    masterGain.gain.setTargetAtTime(m ? 0.0 : 0.55, t, 0.15);
  }

  function pause() {
    if (!ctx) return;
    ctx.suspend();
  }
  function resume() {
    if (!ctx) return;
    ctx.resume();
  }

  return { start, update, setMuted, pause, resume };
}
